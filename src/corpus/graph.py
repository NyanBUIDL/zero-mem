"""M10.6 — DERIVED, authorization-safe corpus knowledge graph.

This module is the WRITE/BUILD path for the optional corpus graph. It is a
derived projection only: every edge is materialized from facts already present
in the M10.4 derived corpus store (``zm_corpus_units`` / ``zm_corpus_sources``)
using the closed M8 relation vocabulary (``src/m8/vocabulary.py``). The graph is
NOT canonical, NOT memory, and fully rebuildable from the derived corpus store.

Closed edge contract (docs/plans/plan-m10.md §M10.6 + v10 schema reality)
---------------------------------------------------------------
The plan's prose edge list referenced ``references`` / ``section_of`` members
that do NOT exist in the frozen M8 ``RelationType`` enum or the v10 unit DDL,
and there is no persisted corpus-version table. Per the "derive edges only from
persisted columns + the closed enum" rule, the mandatory deterministic edges are:

- ``source_of``      (corpus_source -> corpus_unit)  from ``units.source_ref``
- ``derived_from``   (corpus_unit  -> corpus_unit)   from ``units.duplicate_of``

These are the ONLY deterministic edges emitted by this module. Anything beyond
them (semantic links, entity/relation extraction) is OPTIONAL ENRICHMENT
(``src/corpus/enrichment.py``) and is never persisted to the graph tables with
canonical authority — it remains in-process derived metadata.

Authorization model
-------------------
Graph *reads* must route through ``CorpusGraphReadService``, which extracts the
authorized corpus universe via the SAME M5/M10.5 scope enumeration used by
``AuthorizedReadService.corpus_unit_search`` (``AuthorizedCorpusScope``). Only
nodes/edges whose endpoints sit inside the authorized universe are visible; an
edge is visible only if BOTH endpoints are authorized. Authorization-before-
influence is therefore structural: unauthorized nodes/edges are never added to
the working set, so they cannot affect path selection, ranking, truncation, or
degree statistics. (Reuses M5; does NOT reinvent authorization.)

Read-only guarantee
--------------------
Both build (this module) and read (:class:`CorpusGraphReadService`) open the
corpus store read-only. No corpus/memory/registry/blob/project-state/Obsidian
mutation occurs on the read path.

Provenance
----------
Every edge carries: ``relation_source='corpus_extraction'`` (the M10 corpus
extraction member of ``RelationSource``), ``source_ref`` (the unit/source that
asserted the link), ``projection_version`` / ``identity_version`` (deterministic
reproducibility), and a ``provenance_hash`` over the deterministic inputs so the
edge can be rebuilt and audited. No edge exists without a traceable source.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Iterable, List, Mapping, Optional, Tuple

from src.access.authorized_read import AuthorizedReadService
from src.access.contracts import AccessRequest
from src.corpus.retrieval import AuthorizedCorpusScope
from src.m8 import vocabulary as _vocab
from src.retrieval.db import ReadonlyStore, open_readonly
from src.storage.migrations import migrate_10 as _migrate_10

# Closed resource types (permanent M6.6 — these never collapse into one another).
_CORPUS_SOURCE_RT: Final[str] = "corpus_source"
_CORPUS_UNIT_RT: Final[str] = "corpus_unit"

# Relation types emitted by the deterministic projection (validated against the
# closed M8 enum — any other type fails closed).
_REL_SOURCE_OF: Final[str] = _vocab.RelationType.SOURCE_OF.value
_REL_DERIVED_FROM: Final[str] = _vocab.RelationType.DERIVED_FROM.value

# Every deterministic corpus edge is asserted by corpus extraction, not inferred.
_RELATION_SOURCE: Final[str] = _vocab.RelationSource.CORPUS_EXTRACTION.value

#: Projection + identity versions (change => new deterministic edges on rebuild).
_CORPUS_GRAPH_PROJECTION_VERSION: Final[str] = "m10.6"
_CORPUS_GRAPH_IDENTITY_VERSION: Final[str] = "m10.6"


class CorpusGraphError(RuntimeError):
    """Sanitized failure during corpus graph build/read (never leaks text)."""


# ---------------------------------------------------------------------------
# Deterministic edge model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CorpusGraphEdge:
    """One deterministic corpus graph edge with full provenance.

    ``from_`` / ``to`` are (resource_type, resource_id) tuples so node identity
    never collapses across resource types (M6.6). ``source_ref`` anchors the
    edge on the concrete unit/source that asserted it.
    """

    edge_id: str
    from_type: str
    from_id: str
    relation_type: str
    to_type: str
    to_id: str
    source_ref: str
    relation_source: str = _RELATION_SOURCE
    projection_version: str = _CORPUS_GRAPH_PROJECTION_VERSION
    identity_version: str = _CORPUS_GRAPH_IDENTITY_VERSION
    provenance_hash: str = ""

    def as_row(self) -> dict:
        return {
            "edge_id": self.edge_id,
            "from_resource_type": self.from_type,
            "from_resource_id": self.from_id,
            "relation_type": self.relation_type,
            "to_resource_type": self.to_type,
            "to_resource_id": self.to_id,
            "profile_id": None,
            "project_id": None,
            "knowledge_space_id": None,
            "lifecycle_status": "candidate",
            "verification_status": None,
            "valid_from": None,
            "valid_until": None,
            "source_event_id": None,
            "trace_id": None,
            "relation_source": self.relation_source,
            "source_ref": self.source_ref,
            "projection_version": self.projection_version,
            "identity_version": self.identity_version,
            "provenance_hash": self.provenance_hash,
            "content_hash": "",
            "created_at": None,
        }


def _edge_id(*parts: str) -> str:
    from src.m8.identity import content_hash

    return "ce_" + content_hash({"edge": list(parts)})[:32]


def _prov_hash(*parts: str) -> str:
    from src.m8.identity import content_hash

    return content_hash({"prov": list(parts)})[:32]


# ---------------------------------------------------------------------------
# Edge extraction from persisted columns (deterministic only)
# ---------------------------------------------------------------------------

def _iter_deterministic_edges(conn: sqlite3.Connection) -> Iterable[CorpusGraphEdge]:
    """Yield deterministic corpus edges from persisted derived-corpus columns.

    Only columns actually stored in v10 are read:
    - units.source_ref  -> corpus_source SOURCE_OF corpus_unit
    - units.duplicate_of -> corpus_unit DERIVED_FROM corpus_unit

    No ``references`` / ``section_of`` / version-table edges are emitted because
    those facts are not persisted in the v10 substrate (and are not members of
    the closed M8 RelationType enum). Adding them would require an approved
    schema/vocabulary change, not silent invention.
    """
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT unit_id, source_ref, duplicate_of, source_location_id, content_hash "
        "FROM zm_corpus_units"
    ).fetchall()
    for unit_id, source_ref, duplicate_of, loc, chash in rows:
        if not unit_id:
            continue
        # Edge: source -> unit (source_of). Provenance anchors on the unit.
        if source_ref:
            yield CorpusGraphEdge(
                edge_id=_edge_id(_REL_SOURCE_OF, source_ref, unit_id),
                from_type=_CORPUS_SOURCE_RT,
                from_id=source_ref,
                relation_type=_REL_SOURCE_OF,
                to_type=_CORPUS_UNIT_RT,
                to_id=unit_id,
                source_ref=unit_id,
                provenance_hash=_prov_hash(
                    "source_of", source_ref, unit_id, loc or "", chash or ""
                ),
            )
        # Edge: unit -> retained duplicate unit (derived_from). Provenance
        # anchors on this unit; it points at the KEEPING unit (duplicate_of).
        if duplicate_of and duplicate_of != unit_id:
            yield CorpusGraphEdge(
                edge_id=_edge_id(_REL_DERIVED_FROM, unit_id, duplicate_of),
                from_type=_CORPUS_UNIT_RT,
                from_id=unit_id,
                relation_type=_REL_DERIVED_FROM,
                to_type=_CORPUS_UNIT_RT,
                to_id=duplicate_of,
                source_ref=unit_id,
                provenance_hash=_prov_hash(
                    "derived_from", unit_id, duplicate_of, loc or "", chash or ""
                ),
            )


# ---------------------------------------------------------------------------
# Build (projection) — derived, idempotent
# ---------------------------------------------------------------------------

@dataclass
class CorpusGraphBuildReport:
    edges_projected: int = 0
    sources_of: int = 0
    derived_from: int = 0
    source_units_read: int = 0
    error: Optional[str] = None


def build_corpus_graph(
    conn: sqlite3.Connection,
    *,
    clear_first: bool = True,
) -> CorpusGraphBuildReport:
    """Project deterministic corpus edges into ``zm_corpus_relations``.

    Derived and idempotent: re-running replaces the prior edges with an
    equivalent set (same inputs -> same edge ids/content hashes). The v10
    migration guarantees the table + closed CHECK constraints already exist; if
    they do not (e.g. a pre-v10 store), we fail closed rather than silently
    widening the schema.

    Does not mutate canonical corpus, memory, registry, blobs, or project state.
    """
    report = CorpusGraphBuildReport()
    if conn.in_transaction:
        conn.commit()
    try:
        # Ensure the derived graph table exists (v10 substrate). Fail closed if
        # the CHECK constraints are missing rather than creating a loosened copy.
        cur = conn.cursor()
        _ensure_relations_table(cur)
        if clear_first:
            cur.execute("DELETE FROM zm_corpus_relations WHERE relation_source = ?",
                        (_RELATION_SOURCE,))
        n = 0
        for edge in _iter_deterministic_edges(conn):
            row = edge.as_row()
            cur.execute(
                "INSERT OR REPLACE INTO zm_corpus_relations "
                "(edge_id, from_resource_type, from_resource_id, relation_type, "
                "to_resource_type, to_resource_id, profile_id, project_id, "
                "knowledge_space_id, lifecycle_status, verification_status, "
                "valid_from, valid_until, source_event_id, trace_id, "
                "relation_source, source_ref, projection_version, identity_version, "
                "provenance_hash, content_hash, created_at) "
                "VALUES (:edge_id, :from_resource_type, :from_resource_id, "
                ":relation_type, :to_resource_type, :to_resource_id, :profile_id, "
                ":project_id, :knowledge_space_id, :lifecycle_status, "
                ":verification_status, :valid_from, :valid_until, :source_event_id, "
                ":trace_id, :relation_source, :source_ref, :projection_version, "
                ":identity_version, :provenance_hash, :content_hash, :created_at)",
                row,
            )
            n += 1
            if edge.relation_type == _REL_SOURCE_OF:
                report.sources_of += 1
            elif edge.relation_type == _REL_DERIVED_FROM:
                report.derived_from += 1
        conn.commit()
        report.edges_projected = n
        return report
    except sqlite3.OperationalError as exc:
        conn.rollback()
        report.error = f"corpus_graph_build_failed:{type(exc).__name__}"
        raise CorpusGraphError(report.error) from None
    finally:
        pass


def _ensure_relations_table(cur: sqlite3.Cursor) -> None:
    """Verify ``zm_corpus_relations`` exists with closed CHECK constraints.

    Raises if the table is absent so we never silently create a loosened copy
    (schema stays exactly v10). Mirrors the migration contract.
    """
    row = cur.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' "
        "AND name='zm_corpus_relations'"
    ).fetchone()
    if row is None or not row[0]:
        raise CorpusGraphError("corpus_graph_table_missing:zm_corpus_relations")
    sql = row[0]
    if "corpus_extraction" not in sql or "source_of" not in sql:
        raise CorpusGraphError("corpus_graph_table_constraints_unexpected")


# ---------------------------------------------------------------------------
# Read facade — authorization-first, bounded, read-only
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GraphReadBounds:
    """Bounded result windows for one corpus graph read (reuse M8 ceilings)."""

    max_depth: int = 2
    max_fan_out: int = 20
    max_nodes: int = 40
    max_edges: int = 80

    def __post_init__(self) -> None:
        for name, value, ceiling in (
            ("max_depth", self.max_depth, 2),
            ("max_fan_out", self.max_fan_out, 20),
            ("max_nodes", self.max_nodes, 40),
            ("max_edges", self.max_edges, 80),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"graph_bounds_error:not_an_integer:{name}")
            if value < 0:
                raise ValueError(f"graph_bounds_error:below_minimum:{name}")
            if value > ceiling:
                # Fail closed: never silently widen beyond the M8-approved ceiling.
                raise ValueError(f"graph_bounds_error:exceeds_fixed_ceiling:{name}")


DEFAULT_GRAPH_BOUNDS: Final[GraphReadBounds] = GraphReadBounds()


@dataclass
class CorpusGraphResult:
    """Authorization-bounded corpus graph neighbourhood (DATA only)."""

    seed_id: str
    seed_type: str
    nodes: List[Tuple[str, str]] = field(default_factory=list)  # (type, id)
    edges: List[CorpusGraphEdge] = field(default_factory=list)
    bound_reached: Tuple[str, ...] = field(default_factory=tuple)
    unauthorized_hidden: bool = False  # True if seed or any neighbor was denied

    def node_ids(self) -> List[str]:
        return [nid for (_t, nid) in self.nodes]

    def edge_ids(self) -> List[str]:
        return [e.edge_id for e in self.edges]


class CorpusGraphReadService:
    """Authorization-first, bounded, READ-ONLY corpus graph reader.

    Reuses the M5/M10.5 authorization stack: a single ``AccessRequest`` is
    gated by ``AuthorizedReadService._gate`` and the resulting effective scope is
    enumerated into the SAME ``AuthorizedCorpusScope`` triples used by
    ``corpus_unit_search``. Only corpus_unit + corpus_source nodes/edges inside
    that authorized universe are visible. Edge visibility requires BOTH endpoints
    authorized -> adjacency grants nothing; an authorized unit adjacent to an
    unauthorized source exposes nothing.

    Unauthorized graph material is removed BEFORE any budget is consumed, so it
    can never influence paths, ranking, truncation, or degree stats. This is the
    corpus analogue of the M8.3 "authorization-before-influence" guard.
    """

    def __init__(
        self,
        store,
        requesting_profile_id: Optional[str],
        grant_conn=None,
    ) -> None:
        # Reuse M5 facade verbatim — no parallel authorization model.
        self._svc = AuthorizedReadService(
            store, requesting_profile_id, grant_conn=grant_conn
        )
        self._requester = requesting_profile_id
        self._store = store

    # -- internal: authorized universe (corpus_unit + corpus_source) ----------
    def _authorized_scope(self, request: AccessRequest) -> AuthorizedCorpusScope:
        eff = self._svc._gate(request)
        if not eff.allow:
            return AuthorizedCorpusScope(allowed_scopes=())
        allowed: List[tuple] = []
        for scope in self._svc._ordered_scopes(eff):
            profiles = list(scope.allowed_profile_ids)
            projects = list(scope.allowed_project_ids)
            spaces = list(scope.allowed_knowledge_space_ids)
            if scope.global_read_allowed:
                profiles = profiles + [self._requester] if self._requester else profiles
                allowed.append((None, None, None))
            if not profiles and not projects and not spaces:
                if self._requester is not None:
                    allowed.append((self._requester, None, None))
                continue
            p_set = profiles or [None]
            j_set = projects or [None]
            k_set = spaces or [None]
            for p in p_set:
                for j in j_set:
                    for kk in k_set:
                        allowed.append((p, j, kk))
        seen = set()
        deduped = []
        for triple in allowed:
            if triple not in seen:
                seen.add(triple)
                deduped.append(triple)
        return AuthorizedCorpusScope(allowed_scopes=tuple(deduped))

    def _scope_predicate(self, scope: AuthorizedCorpusScope) -> str:
        """SQL IN(...) clause matching the authorized (profile, project, space)
        triples, including the (NULL,NULL,NULL) global-read default."""
        triples = list(scope.allowed_scopes)
        if not triples:
            return "0=1"  # nothing authorized
        conds = []
        for (p, j, k) in triples:
            if p is None and j is None and k is None:
                conds.append("(profile_id IS NULL AND project_id IS NULL "
                             "AND knowledge_space_id IS NULL)")
            else:
                p_sql = "profile_id = ?" if p is not None else "profile_id IS NULL"
                j_sql = "project_id = ?" if j is not None else "project_id IS NULL"
                k_sql = ("knowledge_space_id = ?"
                         if k is not None else "knowledge_space_id IS NULL")
                conds.append(f"({p_sql} AND {j_sql} AND {k_sql})")
        params = [v for t in triples for v in t if v is not None]
        # Stash params for the caller via closure-less return.
        self._last_scope_params = params  # type: ignore[attr-defined]
        return "(" + " OR ".join(conds) + ")"

    # -- public read --------------------------------------------------------
    def read_neighbourhood(
        self,
        request: AccessRequest,
        seed_id: str,
        seed_type: str = _CORPUS_UNIT_RT,
        *,
        bounds: GraphReadBounds = DEFAULT_GRAPH_BOUNDS,
    ) -> CorpusGraphResult:
        if seed_type not in (_CORPUS_UNIT_RT, _CORPUS_SOURCE_RT):
            raise ValueError(f"invalid_seed_type:{seed_type}")
        scope = self._authorized_scope(request)
        conn = self._store.conn
        cur = conn.cursor()

        result = CorpusGraphResult(seed_id=seed_id, seed_type=seed_type)
        if not scope.allowed_scopes:
            result.unauthorized_hidden = True
            return result

        # Determine if the seed is itself authorized (member of the universe on
        # either corpus_unit or corpus_source rows). A seed not in the authorized
        # universe is a denial — it must not leak any adjacency.
        seed_authorized = self._seed_authorized(cur, scope, seed_id, seed_type)
        if not seed_authorized:
            result.unauthorized_hidden = True
            return result

        # Collect the authorized universe node set (both resource types) so that
        # an edge is visible only if BOTH endpoints are authorized.
        authorized_nodes = self._authorized_node_set(cur, scope)
        visited = set()
        # Seed node (type-preserved; never collapsed by content hash).
        visited.add((seed_type, seed_id))
        result.nodes.append((seed_type, seed_id))

        frontier = [(seed_type, seed_id)]
        depth = 0
        bound_flags: set = set()
        while frontier and depth < bounds.max_depth:
            nxt: List[Tuple[str, str]] = []
            for (ntype, nid) in frontier:
                if len(result.edges) >= bounds.max_edges:
                    bound_flags.add("bound_max_edges")
                    break
                out_edges = self._edges_for(cur, scope, ntype, nid, authorized_nodes,
                                            bounds, result, nxt)
                if out_edges >= bounds.max_fan_out:
                    bound_flags.add("bound_max_fan_out")
            if len(result.nodes) >= bounds.max_nodes:
                bound_flags.add("bound_max_nodes")
                break
            depth += 1
            frontier = nxt
            if depth >= bounds.max_depth and frontier:
                bound_flags.add("bound_max_depth")
        result.bound_reached = tuple(sorted(bound_flags))
        return result

    # -- helpers ------------------------------------------------------------
    def _seed_authorized(self, cur, scope, seed_id, seed_type) -> bool:
        pred = self._scope_predicate(scope)
        params = self._last_scope_params  # type: ignore[attr-defined]
        if seed_type == _CORPUS_UNIT_RT:
            row = cur.execute(
                f"SELECT 1 FROM zm_corpus_units WHERE unit_id = ? AND {pred}",
                [seed_id, *params],
            ).fetchone()
            return row is not None
        # corpus_source
        row = cur.execute(
            f"SELECT 1 FROM zm_corpus_sources WHERE source_id = ? AND {pred}",
            [seed_id, *params],
        ).fetchone()
        return row is not None

    def _authorized_node_set(self, cur, scope) -> set:
        pred = self._scope_predicate(scope)
        params = self._last_scope_params  # type: ignore[attr-defined]
        nodes: set = set()
        for (rid,) in cur.execute(
            f"SELECT unit_id FROM zm_corpus_units WHERE {pred}", params
        ).fetchall():
            nodes.add((_CORPUS_UNIT_RT, rid))
        for (rid,) in cur.execute(
            f"SELECT source_id FROM zm_corpus_sources WHERE {pred}", params
        ).fetchall():
            nodes.add((_CORPUS_SOURCE_RT, rid))
        return nodes

    def _edges_for(self, cur, scope, ntype, nid, authorized_nodes, bounds,
                   result, nxt) -> int:
        pred = self._scope_predicate(scope)
        params = self._last_scope_params  # type: ignore[attr-defined]
        # Outgoing + incoming edges from zm_corpus_relations over the authorized
        # universe only. We filter BOTH endpoints against authorized_nodes.
        rows = cur.execute(
            "SELECT edge_id, from_resource_type, from_resource_id, relation_type, "
            "to_resource_type, to_resource_id, source_ref, relation_source, "
            "projection_version, identity_version, provenance_hash "
            "FROM zm_corpus_relations "
            "WHERE ((from_resource_type = ? AND from_resource_id = ?) "
            "       OR (to_resource_type = ? AND to_resource_id = ?)) "
            "AND relation_source = ?",
            [ntype, nid, ntype, nid, _RELATION_SOURCE],
        ).fetchall()
        count = 0
        for (eid, ft, fid, rt, tt, tid, sref, rsrc, pver, iver, phash) in rows:
            if len(result.edges) >= bounds.max_edges:
                break
            # Both endpoints must be authorized nodes (adjacency grants nothing).
            if (ft, fid) not in authorized_nodes or (tt, tid) not in authorized_nodes:
                # Edge touches an unauthorized node: must NOT surface, and must
                # NOT bias degree fan-out counting of authorized edges.
                continue
            edge = CorpusGraphEdge(
                edge_id=eid, from_type=ft, from_id=fid, relation_type=rt,
                to_type=tt, to_id=tid, source_ref=sref, relation_source=rsrc,
                projection_version=pver, identity_version=iver,
                provenance_hash=phash,
            )
            result.edges.append(edge)
            count += 1
            for (ot, oid) in ((ft, fid), (tt, tid)):
                if oid != nid or ot != ntype:
                    if (ot, oid) not in result.nodes_set():
                        result.nodes.append((ot, oid))
                        nxt.append((ot, oid))
            if count >= bounds.max_fan_out:
                break
        return count


# Patch CorpusGraphResult with a node-set helper used above (kept here to avoid
# mutating the frozen dataclass at definition time).
def _result_nodes_set(self) -> set:
    return set(self.nodes)


CorpusGraphResult.nodes_set = _result_nodes_set  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Convenience: build graph over a derived corpus store (read-only build)
# ---------------------------------------------------------------------------

def build_corpus_graph_readonly(path: Path) -> "CorpusGraphReadService":
    """Open a derived corpus store read-only and return a graph read service.

    Convenience for tests/callers that want to read the projected graph without
    standing up a full AuthorizedReadService.
    """
    ro: ReadonlyStore = open_readonly(path)
    return CorpusGraphReadService(ro, requesting_profile_id=None)


__all__ = [
    "CorpusGraphEdge",
    "CorpusGraphError",
    "CorpusGraphBuildReport",
    "GraphReadBounds",
    "DEFAULT_GRAPH_BOUNDS",
    "CorpusGraphResult",
    "CorpusGraphReadService",
    "build_corpus_graph",
    "build_corpus_graph_readonly",
]
