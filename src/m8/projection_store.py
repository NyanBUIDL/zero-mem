"""M8.2 — persistence and deterministic rebuild for the derived graph.

Writes the output of :mod:`src.m8.graph_projection` into the v9 derived tables,
and rebuilds that derived state from approved sources:

    approved M2/M4 source rows
      -> typed source records (graph_sources)
      -> typed M8.1 contracts (graph_projection)
      -> derived v9 rows (here)

Properties this layer is responsible for:

- **Derived only.** Only the five v9 tables are written. Canonical JSONL, the
  artifact files, and every M0-M7 projection table are read-only from here.
- **Idempotent.** Persistence keys on the deterministic logical identity of the
  record, so projecting the same source twice inserts the row once. Repeated
  rebuild of unchanged sources yields an identical snapshot.
- **Atomic and fail-closed.** A rebuild runs in one transaction. Malformed
  source data aborts it and rolls back, so no partially trusted graph state is
  left behind, and the index version is marked ``failed`` rather than published.
- **No partial publish.** The registry moves ``building -> published`` only
  after the whole projection commits.
- **No authorization, no truth.** Scope and lifecycle are stored as metadata,
  copied from the source. Nothing here decides access or promotes a claim.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Final, Iterable, Optional, Sequence

from .derived_index import (
    DerivedIndexError,
    begin_index_build,
    clear_m8_derived_state,
    compute_canonical_fingerprint,
    fail_index_build,
    m8_tables_present,
    publish_index_build,
)
from .graph_contract import EntityRecord, GraphEdge
from .graph_projection import (
    GRAPH_PROJECTION_VERSION,
    EdgeSourceRecord,
    EntitySourceRecord,
    MentionProjection,
    MentionSourceRecord,
    ProjectionError,
    project_edge,
    project_entity,
    project_mention,
)
from .graph_sources import (
    SkippedSource,
    compute_source_descriptor,
    max_source_timestamp,
    read_all_edge_sources,
)
from .identity import IDENTITY_VERSION

#: Registry entry a graph rebuild publishes.
GRAPH_INDEX_NAME: Final[str] = "zm_graph_edges"

_EDGE_INSERT: Final[str] = (
    "INSERT INTO zm_graph_edges ("
    "edge_id, from_resource_type, from_resource_id, relation_type, "
    "to_resource_type, to_resource_id, profile_id, project_id, "
    "knowledge_space_id, lifecycle_status, verification_status, "
    "valid_from, valid_until, source_event_id, trace_id, relation_source, "
    "source_ref, projection_version, identity_version, provenance_hash, "
    "content_hash, created_at) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
    # Identity is deterministic, so a repeated projection of the same source
    # produces the same edge_id and is a no-op rather than a duplicate row.
    "ON CONFLICT(edge_id) DO NOTHING"
)

_ENTITY_INSERT: Final[str] = (
    "INSERT INTO zm_entities ("
    "entity_id, entity_type, canonical_name, profile_id, project_id, "
    "knowledge_space_id, lifecycle_status, source_event_id, trace_id, "
    "relation_source, source_ref, projection_version, identity_version, "
    "provenance_hash, content_hash, created_at, updated_at) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
    "ON CONFLICT(entity_id) DO NOTHING"
)

_MENTION_INSERT: Final[str] = (
    "INSERT INTO zm_entity_mentions ("
    "mention_id, entity_id, source_event_id, trace_id, span_start, span_end, "
    "mention_text_hash, profile_id, project_id, knowledge_space_id, "
    "provenance_hash, content_hash, created_at) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
    "ON CONFLICT(mention_id) DO NOTHING"
)


class GraphPersistenceError(RuntimeError):
    """Sanitized derived-graph persistence failure."""

    def __init__(self, reason: str, detail: str = "") -> None:
        message = f"graph_persistence_error: {reason}"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class ProjectionReport:
    """Deterministic, sanitized summary of one projection or rebuild.

    Counts and reason codes only. It exposes no payload text and no
    authorization outcome, and its numbers are derived-index bookkeeping — they
    are not a confidence, ranking, or truth signal.
    """

    edges_projected: int = 0
    edges_written: int = 0
    entities_projected: int = 0
    entities_written: int = 0
    mentions_projected: int = 0
    mentions_written: int = 0
    skipped: tuple[SkippedSource, ...] = ()
    canonical_fingerprint: Optional[str] = None
    index_version: Optional[str] = None
    published: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "edges_projected": self.edges_projected,
            "edges_written": self.edges_written,
            "entities_projected": self.entities_projected,
            "entities_written": self.entities_written,
            "mentions_projected": self.mentions_projected,
            "mentions_written": self.mentions_written,
            "skipped": [
                {
                    "relation_source": s.relation_source,
                    "reason_code": s.reason_code,
                    "source_ref": s.source_ref,
                }
                for s in self.skipped
            ],
            "canonical_fingerprint": self.canonical_fingerprint,
            "index_version": self.index_version,
            "published": self.published,
            "projection_version": GRAPH_PROJECTION_VERSION,
        }


def _require_v9(conn: sqlite3.Connection) -> None:
    if not m8_tables_present(conn):
        raise GraphPersistenceError("schema_v9_missing")


def write_edge(
    conn: sqlite3.Connection, edge: GraphEdge, source: EdgeSourceRecord
) -> bool:
    """Persist one derived edge. Returns True when a new row was inserted.

    ``valid_from`` / ``valid_until`` are copied only when the source actually
    carries them; otherwise they stay NULL. No time is invented.
    """
    if not isinstance(edge, GraphEdge):
        raise GraphPersistenceError("invalid_edge")
    cur = conn.execute(
        _EDGE_INSERT,
        (
            edge.edge_id,
            edge.from_ref.resource_type,
            edge.from_ref.resource_id,
            edge.relation_type,
            edge.to_ref.resource_type,
            edge.to_ref.resource_id,
            edge.scope.profile_id,
            edge.scope.project_id,
            edge.scope.knowledge_space_id,
            edge.lifecycle_status,
            edge.verification_status,
            source.valid_from,
            source.valid_until,
            edge.provenance.source_event_id,
            edge.provenance.trace_id,
            edge.provenance.relation_source,
            edge.provenance.source_ref,
            GRAPH_PROJECTION_VERSION,
            IDENTITY_VERSION,
            edge.provenance.compute_hash(),
            edge.compute_content_hash(),
            source.created_at,
        ),
    )
    return cur.rowcount > 0


def write_entity(
    conn: sqlite3.Connection, entity: EntityRecord, source: EntitySourceRecord
) -> bool:
    """Persist one derived entity. Returns True when a new row was inserted."""
    if not isinstance(entity, EntityRecord):
        raise GraphPersistenceError("invalid_entity")
    cur = conn.execute(
        _ENTITY_INSERT,
        (
            entity.entity_id,
            entity.entity_type,
            entity.canonical_name,
            entity.scope.profile_id,
            entity.scope.project_id,
            entity.scope.knowledge_space_id,
            entity.lifecycle_status,
            entity.provenance.source_event_id,
            entity.provenance.trace_id,
            entity.provenance.relation_source,
            entity.provenance.source_ref,
            GRAPH_PROJECTION_VERSION,
            IDENTITY_VERSION,
            entity.provenance.compute_hash(),
            entity.compute_content_hash(),
            source.created_at,
            source.created_at,
        ),
    )
    return cur.rowcount > 0


def write_mention(conn: sqlite3.Connection, mention: MentionProjection) -> bool:
    """Persist one derived mention. Returns True when a new row was inserted."""
    if not isinstance(mention, MentionProjection):
        raise GraphPersistenceError("invalid_mention")
    cur = conn.execute(
        _MENTION_INSERT,
        (
            mention.mention_id,
            mention.entity_id,
            mention.source_event_id,
            mention.trace_id,
            mention.span_start,
            mention.span_end,
            mention.mention_text_hash,
            mention.scope.profile_id,
            mention.scope.project_id,
            mention.scope.knowledge_space_id,
            mention.provenance.compute_hash(),
            mention.compute_content_hash(),
            mention.created_at,
        ),
    )
    return cur.rowcount > 0


def project_edge_records(
    conn: sqlite3.Connection, records: Iterable[EdgeSourceRecord]
) -> tuple[int, int]:
    """Project and persist edge source records. Returns (projected, written)."""
    _require_v9(conn)
    projected = 0
    written = 0
    for record in records:
        edge = project_edge(record)
        projected += 1
        if write_edge(conn, edge, record):
            written += 1
    return projected, written


def project_entity_records(
    conn: sqlite3.Connection, records: Iterable[EntitySourceRecord]
) -> tuple[int, int]:
    """Project and persist explicit entity records. Returns (projected, written)."""
    _require_v9(conn)
    projected = 0
    written = 0
    for record in records:
        entity = project_entity(record)
        projected += 1
        if write_entity(conn, entity, record):
            written += 1
    return projected, written


def project_mention_records(
    conn: sqlite3.Connection, records: Iterable[MentionSourceRecord]
) -> tuple[int, int]:
    """Project and persist explicit mentions plus their entities.

    The mention's entity row is written first, so a mention never references a
    missing entity.
    """
    _require_v9(conn)
    projected = 0
    written = 0
    for record in records:
        entity = project_entity(record.entity)
        write_entity(conn, entity, record.entity)
        mention = project_mention(record)
        projected += 1
        if write_mention(conn, mention):
            written += 1
    return projected, written


def project_graph_from_sources(conn: sqlite3.Connection) -> ProjectionReport:
    """Project every approved source edge into the derived graph.

    Does NOT clear existing derived state and does NOT touch the version
    registry: it is the incremental step that :func:`rebuild_graph` composes.
    """
    _require_v9(conn)
    scan = read_all_edge_sources(conn)
    projected, written = project_edge_records(conn, scan.edges)
    return ProjectionReport(
        edges_projected=projected,
        edges_written=written,
        skipped=scan.skipped,
    )


def rebuild_graph(
    conn: sqlite3.Connection,
    *,
    version: str = "1",
    built_at: Optional[str] = None,
    source_cutoff: Optional[str] = None,
    entity_records: Sequence[EntitySourceRecord] = (),
    mention_records: Sequence[MentionSourceRecord] = (),
) -> ProjectionReport:
    """Deterministically rebuild the derived graph from approved sources.

    Steps, all inside one transaction:

    1. clear the derived M8 tables;
    2. re-project every approved source edge, plus any explicitly supplied
       entity/mention records;
    3. record the canonical fingerprint of the source state consumed;
    4. publish the index version.

    ``built_at`` and ``source_cutoff`` come from real source data, never from
    the wall clock: both default to the largest ``zm_meta.created_at``. When no
    source timestamp exists the caller must supply them, so the projector never
    fabricates a time.

    On any failure the transaction rolls back and the index version is marked
    ``failed``, so a partially built graph is never published or readable as
    complete. Canonical JSONL is never opened, let alone modified.
    """
    _require_v9(conn)
    latest = max_source_timestamp(conn)
    cutoff = source_cutoff if source_cutoff is not None else latest
    stamp = built_at if built_at is not None else latest
    if cutoff is None or stamp is None:
        raise GraphPersistenceError("missing_explicit_build_timestamps")

    descriptor = compute_source_descriptor(conn)
    fingerprint = compute_canonical_fingerprint(descriptor)

    in_transaction = conn.in_transaction
    if not in_transaction:
        conn.execute("BEGIN")
    try:
        begin_index_build(
            conn,
            index_name=GRAPH_INDEX_NAME,
            version=version,
            source_cutoff=cutoff,
            canonical_fingerprint=fingerprint,
            built_at=stamp,
        )
        clear_m8_derived_state(conn)
        scan = read_all_edge_sources(conn)
        edges_projected, edges_written = project_edge_records(conn, scan.edges)
        entities_projected, entities_written = project_entity_records(
            conn, entity_records
        )
        mentions_projected, mentions_written = project_mention_records(
            conn, mention_records
        )
        publish_index_build(conn, GRAPH_INDEX_NAME)
        if not in_transaction:
            conn.commit()
    except (ProjectionError, DerivedIndexError, sqlite3.Error) as exc:
        if not in_transaction:
            try:
                conn.rollback()
            except sqlite3.Error:  # pragma: no cover - defensive
                pass
            # Record the failure outside the rolled-back transaction so an
            # interrupted rebuild leaves no row claiming to be usable.
            try:
                if m8_tables_present(conn):
                    begin_index_build(
                        conn,
                        index_name=GRAPH_INDEX_NAME,
                        version=version,
                        source_cutoff=cutoff,
                        canonical_fingerprint=fingerprint,
                        built_at=stamp,
                    )
                    fail_index_build(conn, GRAPH_INDEX_NAME)
                    conn.commit()
            except (DerivedIndexError, sqlite3.Error):  # pragma: no cover
                pass
        raise

    return ProjectionReport(
        edges_projected=edges_projected,
        edges_written=edges_written,
        entities_projected=entities_projected,
        entities_written=entities_written,
        mentions_projected=mentions_projected,
        mentions_written=mentions_written,
        skipped=scan.skipped,
        canonical_fingerprint=fingerprint,
        index_version=version,
        published=True,
    )


def graph_edge_count(conn: sqlite3.Connection) -> int:
    """Row count of the derived edge table (operational bookkeeping only)."""
    _require_v9(conn)
    return int(conn.execute("SELECT COUNT(*) FROM zm_graph_edges").fetchone()[0])


__all__ = [
    "GRAPH_INDEX_NAME",
    "GraphPersistenceError",
    "ProjectionReport",
    "write_edge",
    "write_entity",
    "write_mention",
    "project_edge_records",
    "project_entity_records",
    "project_mention_records",
    "project_graph_from_sources",
    "rebuild_graph",
    "graph_edge_count",
]
