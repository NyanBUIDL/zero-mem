"""M8.2 — approved source readers for deterministic graph projection.

Reads ONLY explicitly recorded links out of the approved canonical/project
substrate and turns them into typed ``EdgeSourceRecord`` values. It never
writes, never authorizes, and never infers a link that a source did not record.

Approved edge classes (nothing else is projected):

===================  ==========================================================
relation_source      what it reads
===================  ==========================================================
``m2_relation``      ``zm_relations`` rows whose relation name has an approved
                     mapping in the closed M8 vocabulary. ``child_of`` has no
                     approved counterpart and is reported as unmapped.
``m2_artifact``      ``zm_artifacts.origin_event_id`` -> ``event source_of
                     artifact``.
``m4_supersession``  explicit ``zm_decisions.supersedes_id`` and
                     ``zm_requirements.supersedes`` -> ``supersedes``.
``m4_project_link``  explicit ``zm_decisions.linked_requirement_ids`` ->
                     ``decision decision_for requirement``; explicit
                     ``zm_project_artifacts.linked_requirement_ids`` /
                     ``linked_decision_ids`` -> ``project_artifact artifact_of
                     <target>``.
``m4_verification``  ``zm_verifications`` subject linkage -> ``verification
                     verifies <subject>``, when the subject type maps to a
                     typed resource.
===================  ==========================================================

Deliberately NOT projected:

- ``m2_scope``. ``profile_id`` / ``project_id`` / ``knowledge_space_id`` are
  authorization scope coordinates, not content-bearing nodes (docs/plans/plan-m8.md §7).
  They are preserved as scope METADATA on every derived row; turning them into
  graph nodes would invite "shares a project, therefore reachable" reasoning,
  which is exactly the cross-scope inference M8.2 must not enable.
- Any link that requires resolving prose, similarity, or co-occurrence.

Determinism: every query carries an explicit ``ORDER BY`` over stable logical
columns, so a rebuild traverses sources in the same order every time. Nothing
here reads the wall clock or generates randomness.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Final, Optional

from .graph_projection import (
    REASON_MISSING_ENDPOINT,
    REASON_SELF_LINK,
    REASON_UNMAPPED_RELATION_TYPE,
    REASON_UNMAPPED_SUBJECT_TYPE,
    EdgeSourceRecord,
    map_m2_relation_type,
    map_verification_subject_type,
    parse_link_list,
)
from .vocabulary import RelationSource, RelationType

#: Tables an M8.2 source read is allowed to touch. Read-only, and canonical
#: JSONL is not among them: projection consumes the M2/M4 derived projections
#: of canonical data, exactly as the M8.1 foundation and docs/plans/plan-m8.md §14 specify.
APPROVED_SOURCE_TABLES: Final[tuple[str, ...]] = (
    "zm_meta",
    "zm_lifecycle",
    "zm_relations",
    "zm_artifacts",
    "zm_decisions",
    "zm_requirements",
    "zm_verifications",
    "zm_project_artifacts",
)


@dataclass(frozen=True)
class SkippedSource:
    """A source record that was deliberately not projected.

    Sanitized and structural: it names the substrate, a stable reason code, and
    the source reference. It carries no payload text and asserts nothing about
    authorization or truth.
    """

    relation_source: str
    reason_code: str
    source_ref: str


@dataclass(frozen=True)
class SourceScan:
    """Result of one deterministic source scan."""

    edges: tuple[EdgeSourceRecord, ...]
    skipped: tuple[SkippedSource, ...]


def _rows(conn: sqlite3.Connection, sql: str) -> list[Any]:
    return list(conn.execute(sql).fetchall())


def _get(row: Any, key: str) -> Any:
    """Column access that works for both ``sqlite3.Row`` and plain tuples."""
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    found = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (name,)
    ).fetchone()
    return found is not None


def _event_scope(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """Per-event scope, lifecycle, and verification, drawn from M2 projections.

    ``zm_lifecycle.current_state`` wins over ``zm_meta.lifecycle_status`` when
    present, because M2 records supersession and logical deletion there. The
    value is copied, never upgraded: a deleted or superseded source produces a
    derived row that still says deleted or superseded.

    ``zm_meta`` carries no ``knowledge_space_id`` column, so that dimension
    stays ``None`` for M2-derived edges rather than being borrowed from another
    field.
    """
    scope: dict[str, dict[str, Any]] = {}
    for row in _rows(
        conn,
        "SELECT m.event_id AS event_id, m.profile_id AS profile_id, "
        "m.project_id AS project_id, m.trace_id AS trace_id, "
        "m.lifecycle_status AS lifecycle_status, "
        "m.verification_status AS verification_status, "
        "m.created_at AS created_at, l.current_state AS current_state "
        "FROM zm_meta m LEFT JOIN zm_lifecycle l ON l.event_id = m.event_id "
        "ORDER BY m.event_id ASC",
    ):
        current = _get(row, "current_state")
        scope[_get(row, "event_id")] = {
            "profile_id": _get(row, "profile_id"),
            "project_id": _get(row, "project_id"),
            "knowledge_space_id": None,
            "trace_id": _get(row, "trace_id"),
            "lifecycle_status": current or _get(row, "lifecycle_status") or "candidate",
            "verification_status": _get(row, "verification_status"),
            "created_at": _get(row, "created_at"),
        }
    return scope


def read_m2_relation_edges(conn: sqlite3.Connection) -> SourceScan:
    """Project explicit ``zm_relations`` rows into typed event-to-event edges."""
    if not _table_exists(conn, "zm_relations"):
        return SourceScan(edges=(), skipped=())
    scope = _event_scope(conn)
    edges: list[EdgeSourceRecord] = []
    skipped: list[SkippedSource] = []
    for row in _rows(
        conn,
        "SELECT from_event_id, to_event_id, relation, created_at FROM zm_relations "
        "ORDER BY from_event_id ASC, to_event_id ASC, relation ASC",
    ):
        from_id = _get(row, "from_event_id")
        to_id = _get(row, "to_event_id")
        relation = _get(row, "relation")
        source_ref = f"zm_relations:{from_id}:{relation}:{to_id}"
        mapped = map_m2_relation_type(relation)
        if mapped is None:
            # No approved mapping. Reported and dropped — never coerced into
            # 'related_to', which would fabricate graph semantics.
            skipped.append(
                SkippedSource(
                    relation_source=RelationSource.M2_RELATION.value,
                    reason_code=REASON_UNMAPPED_RELATION_TYPE,
                    source_ref=source_ref,
                )
            )
            continue
        if from_id == to_id:
            skipped.append(
                SkippedSource(
                    relation_source=RelationSource.M2_RELATION.value,
                    reason_code=REASON_SELF_LINK,
                    source_ref=source_ref,
                )
            )
            continue
        meta = scope.get(from_id)
        if meta is None:
            skipped.append(
                SkippedSource(
                    relation_source=RelationSource.M2_RELATION.value,
                    reason_code=REASON_MISSING_ENDPOINT,
                    source_ref=source_ref,
                )
            )
            continue
        edges.append(
            EdgeSourceRecord(
                from_resource_type="event",
                from_resource_id=from_id,
                relation_type=mapped,
                to_resource_type="event",
                to_resource_id=to_id,
                relation_source=RelationSource.M2_RELATION.value,
                source_ref=source_ref,
                profile_id=meta["profile_id"],
                project_id=meta["project_id"],
                knowledge_space_id=meta["knowledge_space_id"],
                lifecycle_status=meta["lifecycle_status"],
                verification_status=meta["verification_status"],
                source_event_id=from_id,
                trace_id=meta["trace_id"],
                created_at=_get(row, "created_at"),
            )
        )
    return SourceScan(edges=tuple(edges), skipped=tuple(skipped))


def read_m2_artifact_edges(conn: sqlite3.Connection) -> SourceScan:
    """Project ``zm_artifacts.origin_event_id`` into ``event source_of artifact``."""
    if not _table_exists(conn, "zm_artifacts"):
        return SourceScan(edges=(), skipped=())
    scope = _event_scope(conn)
    edges: list[EdgeSourceRecord] = []
    skipped: list[SkippedSource] = []
    for row in _rows(
        conn,
        "SELECT artifact_id, origin_event_id, created_at FROM zm_artifacts "
        "ORDER BY artifact_id ASC",
    ):
        artifact_id = _get(row, "artifact_id")
        origin = _get(row, "origin_event_id")
        source_ref = f"zm_artifacts:{artifact_id}"
        if not origin:
            skipped.append(
                SkippedSource(
                    relation_source=RelationSource.M2_ARTIFACT.value,
                    reason_code=REASON_MISSING_ENDPOINT,
                    source_ref=source_ref,
                )
            )
            continue
        meta = scope.get(origin)
        if meta is None:
            skipped.append(
                SkippedSource(
                    relation_source=RelationSource.M2_ARTIFACT.value,
                    reason_code=REASON_MISSING_ENDPOINT,
                    source_ref=source_ref,
                )
            )
            continue
        edges.append(
            EdgeSourceRecord(
                from_resource_type="event",
                from_resource_id=origin,
                relation_type=RelationType.SOURCE_OF.value,
                # Endpoint stays typed as 'artifact'. An event grant must never
                # imply artifact access (permanent M6.6 invariant).
                to_resource_type="artifact",
                to_resource_id=artifact_id,
                relation_source=RelationSource.M2_ARTIFACT.value,
                source_ref=source_ref,
                profile_id=meta["profile_id"],
                project_id=meta["project_id"],
                knowledge_space_id=meta["knowledge_space_id"],
                lifecycle_status=meta["lifecycle_status"],
                verification_status=meta["verification_status"],
                source_event_id=origin,
                trace_id=meta["trace_id"],
                created_at=_get(row, "created_at"),
            )
        )
    return SourceScan(edges=tuple(edges), skipped=tuple(skipped))


def read_m4_supersession_edges(conn: sqlite3.Connection) -> SourceScan:
    """Project explicit M4 supersession fields into ``supersedes`` edges.

    The chain is represented exactly as recorded. No winner is selected, no
    chain is flattened, and no competing supersession model is introduced —
    M4 remains the authority for which record is active.
    """
    edges: list[EdgeSourceRecord] = []
    skipped: list[SkippedSource] = []
    specs = (
        ("zm_decisions", "decision_id", "supersedes_id", "decision"),
        ("zm_requirements", "requirement_id", "supersedes", "requirement"),
    )
    for table, id_col, sup_col, resource_type in specs:
        if not _table_exists(conn, table):
            continue
        for row in _rows(
            conn,
            f"SELECT {id_col} AS rid, {sup_col} AS sup, project_id, profile_id, "
            f"lifecycle_status, trace_id, source_event_id FROM {table} "
            f"WHERE {sup_col} IS NOT NULL ORDER BY {id_col} ASC",
        ):
            rid = _get(row, "rid")
            sup = _get(row, "sup")
            source_ref = f"{table}:{rid}:supersedes:{sup}"
            if not sup:
                continue
            if rid == sup:
                skipped.append(
                    SkippedSource(
                        relation_source=RelationSource.M4_SUPERSESSION.value,
                        reason_code=REASON_SELF_LINK,
                        source_ref=source_ref,
                    )
                )
                continue
            edges.append(
                EdgeSourceRecord(
                    from_resource_type=resource_type,
                    from_resource_id=rid,
                    relation_type=RelationType.SUPERSEDES.value,
                    to_resource_type=resource_type,
                    to_resource_id=sup,
                    relation_source=RelationSource.M4_SUPERSESSION.value,
                    source_ref=source_ref,
                    profile_id=_get(row, "profile_id"),
                    project_id=_get(row, "project_id"),
                    knowledge_space_id=None,
                    lifecycle_status=_get(row, "lifecycle_status") or "candidate",
                    verification_status=None,
                    source_event_id=_get(row, "source_event_id"),
                    trace_id=_get(row, "trace_id"),
                )
            )
    return SourceScan(edges=tuple(edges), skipped=tuple(skipped))


def read_m4_project_link_edges(conn: sqlite3.Connection) -> SourceScan:
    """Project explicit M4 ``linked_*_ids`` columns into typed edges."""
    edges: list[EdgeSourceRecord] = []
    skipped: list[SkippedSource] = []

    if _table_exists(conn, "zm_decisions"):
        for row in _rows(
            conn,
            "SELECT decision_id, linked_requirement_ids, project_id, profile_id, "
            "lifecycle_status, trace_id, source_event_id FROM zm_decisions "
            "WHERE linked_requirement_ids IS NOT NULL ORDER BY decision_id ASC",
        ):
            decision_id = _get(row, "decision_id")
            for target in parse_link_list(
                _get(row, "linked_requirement_ids"), "linked_requirement_ids"
            ):
                edges.append(
                    EdgeSourceRecord(
                        from_resource_type="decision",
                        from_resource_id=decision_id,
                        relation_type=RelationType.DECISION_FOR.value,
                        to_resource_type="requirement",
                        to_resource_id=target,
                        relation_source=RelationSource.M4_PROJECT_LINK.value,
                        source_ref=(
                            f"zm_decisions:{decision_id}:linked_requirement_ids:{target}"
                        ),
                        profile_id=_get(row, "profile_id"),
                        project_id=_get(row, "project_id"),
                        knowledge_space_id=None,
                        lifecycle_status=_get(row, "lifecycle_status") or "candidate",
                        verification_status=None,
                        source_event_id=_get(row, "source_event_id"),
                        trace_id=_get(row, "trace_id"),
                    )
                )

    if _table_exists(conn, "zm_project_artifacts"):
        for row in _rows(
            conn,
            "SELECT artifact_id, project_id, linked_requirement_ids, "
            "linked_decision_ids, source_event_id, verification_status "
            "FROM zm_project_artifacts ORDER BY artifact_id ASC, project_id ASC",
        ):
            artifact_id = _get(row, "artifact_id")
            for column, target_type in (
                ("linked_requirement_ids", "requirement"),
                ("linked_decision_ids", "decision"),
            ):
                for target in parse_link_list(_get(row, column), column):
                    edges.append(
                        EdgeSourceRecord(
                            # 'project_artifact' is its own resource type and is
                            # never collapsed into 'artifact'.
                            from_resource_type="project_artifact",
                            from_resource_id=artifact_id,
                            relation_type=RelationType.ARTIFACT_OF.value,
                            to_resource_type=target_type,
                            to_resource_id=target,
                            relation_source=RelationSource.M4_PROJECT_LINK.value,
                            source_ref=(
                                f"zm_project_artifacts:{artifact_id}:{column}:{target}"
                            ),
                            profile_id=None,
                            project_id=_get(row, "project_id"),
                            knowledge_space_id=None,
                            lifecycle_status="candidate",
                            verification_status=_get(row, "verification_status"),
                            source_event_id=_get(row, "source_event_id"),
                            trace_id=None,
                        )
                    )
    return SourceScan(edges=tuple(edges), skipped=tuple(skipped))


def read_m4_verification_edges(conn: sqlite3.Connection) -> SourceScan:
    """Project ``zm_verifications`` subject linkage into ``verifies`` edges.

    The edge records that a verification record NAMES this subject. It does not
    make the subject verified: the subject's own stored verification status is
    untouched, and the edge's ``verification_status`` is copied from the
    verification row rather than asserted.
    """
    if not _table_exists(conn, "zm_verifications"):
        return SourceScan(edges=(), skipped=())
    edges: list[EdgeSourceRecord] = []
    skipped: list[SkippedSource] = []
    for row in _rows(
        conn,
        "SELECT verification_id, subject_type, subject_id, project_id, "
        "source_event_id, verification_status FROM zm_verifications "
        "ORDER BY verification_id ASC",
    ):
        verification_id = _get(row, "verification_id")
        subject_type = _get(row, "subject_type")
        subject_id = _get(row, "subject_id")
        source_ref = f"zm_verifications:{verification_id}"
        if not subject_id:
            skipped.append(
                SkippedSource(
                    relation_source=RelationSource.M4_VERIFICATION.value,
                    reason_code=REASON_MISSING_ENDPOINT,
                    source_ref=source_ref,
                )
            )
            continue
        mapped = map_verification_subject_type(subject_type)
        if mapped is None:
            skipped.append(
                SkippedSource(
                    relation_source=RelationSource.M4_VERIFICATION.value,
                    reason_code=REASON_UNMAPPED_SUBJECT_TYPE,
                    source_ref=source_ref,
                )
            )
            continue
        edges.append(
            EdgeSourceRecord(
                from_resource_type="verification",
                from_resource_id=verification_id,
                relation_type=RelationType.VERIFIES.value,
                to_resource_type=mapped,
                to_resource_id=subject_id,
                relation_source=RelationSource.M4_VERIFICATION.value,
                source_ref=source_ref,
                profile_id=None,
                project_id=_get(row, "project_id"),
                knowledge_space_id=None,
                lifecycle_status="candidate",
                verification_status=_get(row, "verification_status"),
                source_event_id=_get(row, "source_event_id"),
                trace_id=None,
            )
        )
    return SourceScan(edges=tuple(edges), skipped=tuple(skipped))


#: Ordered readers. The order is fixed so a rebuild always scans sources the
#: same way; derived identity does not depend on it, but reproducible skip
#: reporting does.
SOURCE_READERS: Final[tuple[Any, ...]] = (
    read_m2_relation_edges,
    read_m2_artifact_edges,
    read_m4_supersession_edges,
    read_m4_project_link_edges,
    read_m4_verification_edges,
)


def read_all_edge_sources(conn: sqlite3.Connection) -> SourceScan:
    """Run every approved source reader in fixed order."""
    edges: list[EdgeSourceRecord] = []
    skipped: list[SkippedSource] = []
    for reader in SOURCE_READERS:
        scan = reader(conn)
        edges.extend(scan.edges)
        skipped.extend(scan.skipped)
    return SourceScan(edges=tuple(edges), skipped=tuple(skipped))


def compute_source_descriptor(conn: sqlite3.Connection) -> dict[str, Any]:
    """Deterministic descriptor of the approved source state a build consumed.

    Feeds the M8.1 canonical fingerprint. Counts only, in fixed table order:
    it identifies WHICH source state was read, and carries no content.
    """
    descriptor: dict[str, Any] = {}
    for table in APPROVED_SOURCE_TABLES:
        if _table_exists(conn, table):
            descriptor[table] = int(
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )
        else:
            descriptor[table] = None
    return descriptor


def max_source_timestamp(conn: sqlite3.Connection) -> Optional[str]:
    """Largest ``zm_meta.created_at`` present, or ``None``.

    Used as an explicit build cutoff drawn from real source data. When no
    source event exists the answer is ``None`` — the caller supplies a cutoff
    rather than the projector inventing one from the wall clock.
    """
    if not _table_exists(conn, "zm_meta"):
        return None
    row = conn.execute("SELECT MAX(created_at) FROM zm_meta").fetchone()
    return row[0] if row and row[0] else None


__all__ = [
    "APPROVED_SOURCE_TABLES",
    "SOURCE_READERS",
    "SkippedSource",
    "SourceScan",
    "read_m2_relation_edges",
    "read_m2_artifact_edges",
    "read_m4_supersession_edges",
    "read_m4_project_link_edges",
    "read_m4_verification_edges",
    "read_all_edge_sources",
    "compute_source_descriptor",
    "max_source_timestamp",
]
