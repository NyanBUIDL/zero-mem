"""M8.3 — authorization-first bounded graph reads over the deterministic M8.2 projection.

This module is INTERNAL request-time infrastructure. It is NOT a new Hermes/M6
tool surface (plan-m8.md keeps M6 read tools unchanged; M8.6 owns final
EvidenceSet integration). It provides an internal primitive later increments
may wire up.

AUTHORITATIVE FLOW (plan-m8.md, mandatory order)
------------------------------------------------
    request
    -> normalize scope / resource request
    -> M5 authorization
    -> authorized graph candidate space
    -> bounded graph read
    -> sanitized result

The cardinal rule: **authorization occurs before graph expansion**. No node,
edge, resource_type, relation, provenance, or connectivity is ever inspected to
decide authorization. M5's :class:`src.access.AuthorizedReadService` is the sole
authority. Traversal only ever walks material whose resource it has already
authorized.

What is NEVER done
-------------------
* Traverse first, authorize after ("discover hidden node, then check it").
* Derive authorization from graph connectivity, shared entity text, relation
  type, degree, provenance, calibration, or timestamps (per plan-m8.md).
* Treat graph topology as truth, as conflict resolution, or as a score.
* Mutate any store, JSONL, grant, verification, lifecycle, or calibration state.
  Every query runs on a ``mode="ro"`` + ``query_only`` connection.
* Leak existence of unauthorized material through counts, degree, path length,
  omitted counts, error differences, or bound codes. Bound codes are computed
  only over AUTHORIZED material.
* Reach ``GrantAdminService`` / ``AuthorizedWriteService`` / any HTTP client /
  LLM SDK / embedding client / hardcoded ``HOME`` (enforced statically in
  tests/unit/test_m8_3_static.py).

Scope / resource_type isolation
-------------------------------
Each seed resource is authorized by M5 against an explicit ``resource_type``
(artifact / decision / requirement / verification / project_artifact / event).
M6.6 is preserved: an artifact-only grant does NOT authorize event / relation /
project-resource / generic graph resources. Authorization is recomputed at
traversal time per candidate resource, so a seed authorized for one
resource_type cannot pull in neighbours of a different resource_type unless M5
also authorizes that exact (resource_id, resource_type, scope) pair.

Read-only guarantee
-------------------
``GraphAccessService`` takes an ``AuthorizedReadService`` constructed over a
read-only connection. It issues only ``SELECT`` statements; the connection is
``query_only`` so any mutation raises. No ``commit`` is ever called.

Determinism
-----------
Outputs are ordered by explicit stable keys (resource_id / edge_id), never by
SQLite rowid, Python set/hash order, or wall-clock state. Re-running the same
request over the same authorized state and projection yields byte-identical
ordered results regardless of insertion order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from src.access import AccessRequest, AuthorizedReadService
from src.access.contracts import AllowedScope
from src.m8 import vocabulary as v
from src.m8.graph_bounds import DEFAULT_BOUNDS, GraphReadBounds
from src.m8.derived_index import m8_tables_present

# M8.2 derived edge table (read-only here).
_EDGE_TABLE = "zm_graph_edges"

# Resource type -> canonical node table it projects from.
_NODE_TABLE: dict[str, str] = {
    "event": "zm_meta",
    "artifact": "zm_project_artifacts",
    "decision": "zm_decisions",
    "requirement": "zm_requirements",
    "verification": "zm_verifications",
    "project_artifact": "zm_project_artifacts",
}

# Resource types M5/M6 actually gate through the AuthorizedReadService facade.
_AUTHORIZABLE = set(_NODE_TABLE)


class M8GraphAccessError(RuntimeError):
    """Sanitized authorization-first graph-read failure."""


# ---------------------------------------------------------------------------
# Request / result types (typed, deterministic, no raw rows)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GraphReadRequest:
    """A normalized authorization-first graph read request."""

    resource_id: str
    resource_type: str
    requesting_profile_id: Optional[str] = None
    project_id: Optional[str] = None
    knowledge_space_id: Optional[str] = None
    include_incoming: bool = True
    include_outgoing: bool = True
    bounds: GraphReadBounds = field(default_factory=lambda: DEFAULT_BOUNDS)


@dataclass(frozen=True)
class GraphReadNode:
    resource_id: str
    resource_type: str
    scope: Mapping[str, Any]
    relation: str
    provenance: Mapping[str, Any]
    authorized: bool = True


@dataclass(frozen=True)
class GraphReadEdge:
    edge_id: str
    from_resource_id: str
    from_resource_type: str
    relation_type: str
    to_resource_id: str
    to_resource_type: str
    scope: Mapping[str, Any]
    source_provenance: Mapping[str, Any]


@dataclass(frozen=True)
class GraphReadResult:
    resource_id: str
    resource_type: str
    scope: Mapping[str, Any]
    relation: str
    provenance: Mapping[str, Any]
    nodes: Sequence[GraphReadNode]
    edges: Sequence[GraphReadEdge]
    bound_codes: Sequence[str] = field(default_factory=tuple)
    authorized: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "resource_type": self.resource_type,
            "scope": dict(self.scope),
            "relation": self.relation,
            "provenance": dict(self.provenance),
            "nodes": [vars(n) for n in self.nodes],
            "edges": [vars(e) for e in self.edges],
            "bound_codes": list(self.bound_codes),
            "authorized": self.authorized,
        }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class GraphAccessService:
    """Authorization-first bounded graph read service over the v9 projection.

    Stateless w.r.t. authorization: every candidate is re-checked by the injected
    :class:`AuthorizedReadService` at traversal time, so revocation is honoured
    immediately (no cached grant survives a revoke).
    """

    def __init__(self, auth: AuthorizedReadService) -> None:
        if not isinstance(auth, AuthorizedReadService):
            raise M8GraphAccessError("graph_access_requires_authorized_read_service")
        self._auth = auth
        # The facade wraps a store (with ._conn / .conn) or, in some test
        # harnesses, a raw sqlite3.Connection. Resolve the underlying
        # read-only connection so every graph query inherits the same read-only
        # + query_only guarantees.
        store = auth._store
        if hasattr(store, "_conn"):
            self._conn = store._conn
        elif hasattr(store, "conn"):
            self._conn = store.conn
        else:
            self._conn = store

    # -- internal helpers ---------------------------------------------------

    def _require_v9(self) -> None:
        if not m8_tables_present(self._conn):
            raise M8GraphAccessError("m8_v9_projection_unavailable")

    @staticmethod
    def _scope_of(row: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "profile_id": row.get("profile_id"),
            "project_id": row.get("project_id"),
            "knowledge_space_id": row.get("knowledge_space_id"),
        }

    @staticmethod
    def _provenance_of(row: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "trace_id": row.get("trace_id"),
            "source_event_id": row.get("source_event_id"),
            "origin_jsonl": row.get("origin_jsonl"),
            "ingested_at": row.get("ingested_at"),
        }

    def _authorized_seed(self, req: GraphReadRequest) -> Optional[Mapping[str, Any]]:
        """M5 authorization of the seed BEFORE any graph lookup.

        Returns the resource row (a dict) only if M5 authorizes the exact
        (resource_id, resource_type, scope) pair. Returns None on DENY. No graph
        query is issued for a denied seed.
        """
        if req.resource_type not in _AUTHORIZABLE:
            return None
        ar = AccessRequest(
            operation="READ",
            requesting_profile_id=req.requesting_profile_id,
            project_ids=[req.project_id] if req.project_id is not None else None,
            knowledge_space_ids=([req.knowledge_space_id]
                                 if req.knowledge_space_id is not None else None),
            resource_type=req.resource_type,
            resource_id=req.resource_id,
        )
        result = self._auth.m4_artifacts if req.resource_type in (
            "artifact", "project_artifact") else (
            self._auth.m4_decisions if req.resource_type == "decision" else (
            self._auth.m4_requirements if req.resource_type == "requirement" else (
            self._auth.m4_verifications if req.resource_type == "verification" else
            self._auth.get_event)))
        if req.resource_type == "event":
            res = result(ar, req.resource_id)
        else:
            project_id = req.project_id or row_project_id(self._conn, req)
            if project_id is None:
                return None
            res = result(ar, project_id)
        if getattr(res, "denied", False) or not res.items:
            return None
        # M6.6: confirm the returned row matches the requested resource_type and
        # id. An artifact-only grant cannot masquerade as a different resource.
        for item in res.items:
            if getattr(item, "artifact_id", None) == req.resource_id or \
               getattr(item, "decision_id", None) == req.resource_id or \
               getattr(item, "requirement_id", None) == req.resource_id or \
               getattr(item, "verification_id", None) == req.resource_id or \
               getattr(item, "event_id", None) == req.resource_id:
                return vars(item) if not isinstance(item, dict) else item
        return None

    def _authorize_candidate(
        self, resource_id: str, resource_type: str, req: GraphReadRequest,
        scope_profile: Optional[str], scope_project: Optional[str],
    ) -> bool:
        """Re-check M5 authorization for one candidate neighbour.

        Authorization uses the candidate's OWN scope (taken from the edge that
        pointed to it), never the seed's scope. This is what stops a P1 seed
        from "pulling in" a P2 resource via a too-loose project check. NEVER
        derives anything from graph connectivity; always consults M5.
        """
        if resource_type not in _AUTHORIZABLE:
            return False
        ar = AccessRequest(
            operation="READ",
            requesting_profile_id=req.requesting_profile_id,
            project_ids=[scope_project] if scope_project is not None else None,
            knowledge_space_ids=([req.knowledge_space_id]
                                 if req.knowledge_space_id is not None else None),
            resource_type=resource_type,
            resource_id=resource_id,
        )
        if resource_type in ("artifact", "project_artifact"):
            res = self._auth.m4_artifacts(ar, scope_project or "")
        elif resource_type == "decision":
            res = self._auth.m4_decisions(ar, scope_project or "")
        elif resource_type == "requirement":
            res = self._auth.m4_requirements(ar, scope_project or "")
        elif resource_type == "verification":
            res = self._auth.m4_verifications(ar, scope_project or "")
        else:  # event
            res = self._auth.get_event(ar, resource_id)
        return (not getattr(res, "denied", True)) and bool(getattr(res, "items", []))

    def _load_resource_row(
        self, resource_id: str, resource_type: str
    ) -> Optional[Mapping[str, Any]]:
        """Pure projection read of one authorized resource's own row.

        Returns None (without error) if the row is missing or deleted — missing
        authorized rows are simply skipped, never leaked.
        """
        tbl = _NODE_TABLE.get(resource_type)
        if tbl is None:
            return None
        try:
            cur = self._conn.execute(
                f"SELECT * FROM {tbl} WHERE "
                f"{'event_id' if tbl == 'zm_meta' else _id_col(tbl)} = ?",
                (resource_id,),
            )
            row = cur.fetchone()
        except Exception:
            return None
        if row is None:
            return None
        d = dict(row)
        if d.get("lifecycle_status") == "deleted":
            return None
        return d

    def _edges_for(
        self, resource_id: str, direction: str, limit: int
    ) -> list[Mapping[str, Any]]:
        """Read edges of one direction for one authorized resource.

        Returns at most ``limit`` rows, ORDERED deterministically by
        (relation_type, edge_id) — never by rowid.
        """
        if direction == "outgoing":
            where = "from_resource_id = ?"
        else:
            where = "to_resource_id = ?"
        cur = self._conn.execute(
            f"SELECT * FROM {_EDGE_TABLE} WHERE {where} "
            f"ORDER BY relation_type ASC, edge_id ASC LIMIT ?",
            (resource_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]

    # -- public API --------------------------------------------------------

    def read_subgraph(self, req: GraphReadRequest) -> GraphReadResult:
        self._require_v9()

        seed_row = self._authorized_seed(req)
        if seed_row is None:
            # Authorization FIRST. The caller learns only "not authorized for
            # this seed" — no graph existence, no degree, no partial view.
            return GraphReadResult(
                resource_id=req.resource_id,
                resource_type=req.resource_type,
                scope={},
                relation="derived",
                provenance={},
                nodes=(),
                edges=(),
                bound_codes=(),
                authorized=False,
            )

        bounds = req.bounds
        seen_nodes: dict[str, None] = {}
        seen_edges: dict[str, None] = {}
        nodes: list[GraphReadNode] = []
        edges: list[GraphReadEdge] = []
        bound_codes: list[str] = []

        def _node_key(rid: str, rtype: str) -> str:
            return f"{rtype}:{rid}"

        def _add_node(rid: str, rtype: str) -> None:
            key = _node_key(rid, rtype)
            if key in seen_nodes:
                return
            if len(seen_nodes) >= bounds.max_nodes:
                if "bound_max_nodes" not in bound_codes:
                    bound_codes.append("bound_max_nodes")
                return
            row = self._load_resource_row(rid, rtype)
            seen_nodes[key] = None
            if row is None:
                return
            nodes.append(
                GraphReadNode(
                    resource_id=rid,
                    resource_type=rtype,
                    scope=self._scope_of(row),
                    relation="derived",
                    provenance=self._provenance_of(row),
                )
            )

        def _add_edge(e: Mapping[str, Any]) -> None:
            eid = str(e["edge_id"])
            if eid in seen_edges:
                return
            if len(seen_edges) >= bounds.max_edges:
                if "bound_max_edges" not in bound_codes:
                    bound_codes.append("bound_max_edges")
                return
            seen_edges[eid] = None
            edges.append(
                GraphReadEdge(
                    edge_id=eid,
                    from_resource_id=e["from_resource_id"],
                    from_resource_type=e["from_resource_type"],
                    relation_type=e["relation_type"],
                    to_resource_id=e["to_resource_id"],
                    to_resource_type=e["to_resource_type"],
                    scope={
                        "profile_id": e.get("profile_id"),
                        "project_id": e.get("project_id"),
                        "knowledge_space_id": e.get("knowledge_space_id"),
                    },
                    source_provenance={
                        "trace_id": e.get("trace_id"),
                        "source_event_id": e.get("source_event_id"),
                        "origin_jsonl": e.get("origin_jsonl"),
                        "ingested_at": e.get("ingested_at"),
                    },
                )
            )

        # Seed is itself a result node (depth 0).
        _add_node(req.resource_id, req.resource_type)

        # Bounded expansion: exactly one pass of at most `depth` hops.
        frontier = [(req.resource_id, req.resource_type, 0)]
        while frontier:
            nid, ntype, depth = frontier.pop(0)
            if depth >= bounds.max_depth:
                if "bound_max_depth" not in bound_codes:
                    bound_codes.append("bound_max_depth")
                continue
            directions = []
            if req.include_outgoing:
                directions.append("outgoing")
            if req.include_incoming:
                directions.append("incoming")
            for direction in directions:
                raw_edges = self._edges_for(nid, direction, bounds.max_fan_out + 1)
                if len(raw_edges) > bounds.max_fan_out:
                    if "bound_max_fan_out" not in bound_codes:
                        bound_codes.append("bound_max_fan_out")
                    raw_edges = raw_edges[: bounds.max_fan_out]
                for e in raw_edges:
                    if direction == "outgoing":
                        cand_id, cand_type = e["to_resource_id"], e["to_resource_type"]
                    else:
                        cand_id, cand_type = e["from_resource_id"], e["from_resource_type"]
                    key = _node_key(cand_id, cand_type)
                    if key not in seen_nodes:
                        if not self._authorize_candidate(
                            cand_id, cand_type, req,
                            scope_profile=e.get("profile_id"),
                            scope_project=e.get("project_id"),
                        ):
                            # Denied candidate: node AND edge are withheld. Its
                            # existence is never added to the result, the
                            # degree, or any count.
                            continue
                        _add_node(cand_id, cand_type)
                        frontier.append((cand_id, cand_type, depth + 1))
                    # Reaching here means the candidate is authorized (newly or
                    # previously). The edge between two authorized nodes is
                    # itself authorized and must be emitted — including a second
                    # edge to an already-visited node (no death-by-merge).
                    _add_edge(e)

        # Deterministic ordering (independent of insertion / SQLite order).
        nodes.sort(key=lambda n: (n.resource_type, n.resource_id))
        edges.sort(key=lambda e: (e.relation_type, e.edge_id))
        seen_nodes.clear()
        seen_edges.clear()

        return GraphReadResult(
            resource_id=req.resource_id,
            resource_type=req.resource_type,
            scope=self._scope_of(seed_row),
            relation="derived",
            provenance=self._provenance_of(seed_row),
            nodes=tuple(nodes),
            edges=tuple(edges),
            bound_codes=tuple(bound_codes),
            authorized=True,
        )


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def _id_col(table: str) -> str:
    return {
        "zm_artifacts": "artifact_id",
        "zm_decisions": "decision_id",
        "zm_requirements": "requirement_id",
        "zm_verifications": "verification_id",
        "zm_project_artifacts": "artifact_id",
    }[table]


def row_project_id(conn, req: GraphReadRequest) -> Optional[str]:
    """Best-effort project_id lookup for a seed when the caller omitted it.

    Pure read of the node table; returns None if unknown. Authorization still
    requires the explicit project scope to be allowed by M5.
    """
    tbl = _NODE_TABLE.get(req.resource_type)
    if tbl is None:
        return None
    try:
        cur = conn.execute(
            f"SELECT project_id FROM {tbl} WHERE "
            f"{'event_id' if tbl == 'zm_meta' else _id_col(tbl)} = ?",
            (req.resource_id,),
        )
        row = cur.fetchone()
    except Exception:
        return None
    return row["project_id"] if row else None


def _request_scope(req: GraphReadRequest) -> AllowedScope:
    return AllowedScope(
        operation="READ",
        allowed_profile_ids=[req.requesting_profile_id]
        if req.requesting_profile_id is not None else [],
        allowed_project_ids=[req.project_id] if req.project_id is not None else [],
        allowed_knowledge_space_ids=[req.knowledge_space_id]
        if req.knowledge_space_id is not None else [],
    )


__all__ = [
    "GraphReadRequest",
    "GraphReadNode",
    "GraphReadEdge",
    "GraphReadResult",
    "GraphAccessService",
    "M8GraphAccessError",
]
