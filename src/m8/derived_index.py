"""M8.1 — deterministic derived-index foundation.

Provides the minimum rebuild machinery later M8 increments build on:

    canonical/project sources
      -> deterministic derived M8 structures
    delete derived M8 structures -> rebuild -> equivalent derived state

M8.1 owns the LIFECYCLE of that boundary (clear, initialize, publish a version,
fingerprint, verify emptiness). It deliberately owns no PROJECTION: reading M2
relations and M4 links into ``zm_graph_edges`` is M8.2, and this module has no
knowledge of those source tables.

Invariants enforced here:

- Only the five v9 derived tables are ever touched. Canonical JSONL, artifacts,
  and every M0-M7 derived table are out of scope; ``clear_m8_derived_state``
  cannot reach them.
- Rebuild is deterministic: no wall-clock default, no random identity, no
  insertion-order dependence. ``built_at`` and ``source_cutoff`` are supplied
  explicitly by the caller from canonical data, never read from ``now()``.
- A partial index version is never published. The registry moves
  ``building -> published`` only on explicit success, and ``building ->
  failed`` otherwise, so an interrupted rebuild leaves no row claiming to be
  usable (plan-m8.md §6 "no partial version is published").
- No authorization logic. No M5 policy import, no grant access, no LLM, no
  network.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Final, Mapping, Optional, Sequence

from src.storage.migrations.migrate_9 import M8_DERIVED_INDEXES, M8_DERIVED_TABLES

from .identity import source_fingerprint
from .temporal_contract import normalize_timestamp

#: Projector contract version stamped into derived provenance rows.
PROJECTION_VERSION: Final[str] = "m8.1"

#: Registry index names M8.1 recognizes. A later increment adds its own only
#: with approval; an unknown name fails closed rather than silently registering.
KNOWN_INDEX_NAMES: Final[tuple[str, ...]] = (
    "zm_entities",
    "zm_entity_mentions",
    "zm_graph_edges",
    "zm_temporal_index",
)

#: Registry build states.
BUILD_STATUS_BUILDING: Final[str] = "building"
BUILD_STATUS_PUBLISHED: Final[str] = "published"
BUILD_STATUS_FAILED: Final[str] = "failed"

#: Derived tables cleared by a rebuild. Excludes the version registry itself,
#: which records build history and is updated explicitly rather than wiped.
_REBUILDABLE_TABLES: Final[tuple[str, ...]] = (
    "zm_entity_mentions",  # child first (FK to zm_entities)
    "zm_graph_edges",
    "zm_temporal_index",
    "zm_entities",
)


class DerivedIndexError(RuntimeError):
    """Sanitized derived-index failure. Never contains raw SQL or payloads."""

    def __init__(self, reason: str, detail: str = "") -> None:
        message = f"derived_index_error: {reason}"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)
        self.reason = reason


def _require_v9(conn: sqlite3.Connection) -> None:
    """Fail closed unless every v9 derived table is present."""
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    present = {row[0] for row in rows}
    missing = [name for name in M8_DERIVED_TABLES if name not in present]
    if missing:
        raise DerivedIndexError("schema_v9_missing", ",".join(sorted(missing)))


def m8_tables_present(conn: sqlite3.Connection) -> bool:
    """True when all five v9 derived tables exist."""
    try:
        _require_v9(conn)
    except DerivedIndexError:
        return False
    return True


def clear_m8_derived_state(conn: sqlite3.Connection) -> dict[str, int]:
    """Delete all rows from the rebuildable M8 derived tables.

    Returns per-table deleted-row counts. Touches no canonical JSONL, no
    artifact file, and no M0-M7 derived table — the table list is a fixed
    module constant, not caller input.
    """
    _require_v9(conn)
    cur = conn.cursor()
    deleted: dict[str, int] = {}
    for table in _REBUILDABLE_TABLES:
        before = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        cur.execute(f"DELETE FROM {table}")
        deleted[table] = int(before)
    return deleted


def m8_derived_state_is_empty(conn: sqlite3.Connection) -> bool:
    """True when every rebuildable M8 derived table holds zero rows."""
    _require_v9(conn)
    cur = conn.cursor()
    for table in _REBUILDABLE_TABLES:
        if int(cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) > 0:
            return False
    return True


def compute_canonical_fingerprint(source_descriptor: Mapping[str, Any]) -> str:
    """Deterministic fingerprint of the canonical state a build consumed.

    The caller supplies an explicit descriptor drawn from canonical data (for
    example event ids and content hashes at the cutoff). Identical canonical
    state always fingerprints identically; nothing time-based or random enters
    the digest.
    """
    if not isinstance(source_descriptor, Mapping):
        raise DerivedIndexError("invalid_source_descriptor")
    return source_fingerprint(dict(source_descriptor))


@dataclass(frozen=True)
class IndexVersionRecord:
    """One row of the derived-index version registry.

    Operational metadata only: it records how a derived index was built. It
    carries no content, no authority, and no truth.
    """

    index_name: str
    version: str
    source_cutoff: str
    canonical_fingerprint: str
    built_at: str
    build_status: str

    def to_dict(self) -> dict[str, str]:
        return {
            "index_name": self.index_name,
            "version": self.version,
            "source_cutoff": self.source_cutoff,
            "canonical_fingerprint": self.canonical_fingerprint,
            "built_at": self.built_at,
            "build_status": self.build_status,
        }


def _validate_index_name(index_name: str) -> str:
    if index_name not in KNOWN_INDEX_NAMES:
        raise DerivedIndexError("unknown_index_name", str(index_name)[:48])
    return index_name


def _validate_registry_timestamps(source_cutoff: str, built_at: str) -> None:
    """Both registry timestamps must be explicit, valid, tz-aware values.

    They are supplied by the caller from real data. A malformed or naive value
    is rejected rather than repaired, matching the temporal contract.
    """
    normalize_timestamp("source_cutoff", source_cutoff)
    normalize_timestamp("built_at", built_at)


def begin_index_build(
    conn: sqlite3.Connection,
    *,
    index_name: str,
    version: str,
    source_cutoff: str,
    canonical_fingerprint: str,
    built_at: str,
) -> IndexVersionRecord:
    """Mark an index build as in-progress (``building``).

    A ``building`` row is explicitly NOT usable. Publishing is a separate call,
    so an interrupted rebuild can never leave a row that claims to be complete.
    """
    _require_v9(conn)
    _validate_index_name(index_name)
    if not isinstance(version, str) or not version.strip():
        raise DerivedIndexError("invalid_version")
    if not isinstance(canonical_fingerprint, str) or not canonical_fingerprint.strip():
        raise DerivedIndexError("invalid_canonical_fingerprint")
    _validate_registry_timestamps(source_cutoff, built_at)
    record = IndexVersionRecord(
        index_name=index_name,
        version=version,
        source_cutoff=source_cutoff,
        canonical_fingerprint=canonical_fingerprint,
        built_at=built_at,
        build_status=BUILD_STATUS_BUILDING,
    )
    conn.execute(
        "INSERT INTO zm_m8_index_versions"
        "(index_name, version, source_cutoff, canonical_fingerprint, built_at, build_status) "
        "VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(index_name) DO UPDATE SET "
        "version=excluded.version, source_cutoff=excluded.source_cutoff, "
        "canonical_fingerprint=excluded.canonical_fingerprint, "
        "built_at=excluded.built_at, build_status=excluded.build_status",
        (
            record.index_name,
            record.version,
            record.source_cutoff,
            record.canonical_fingerprint,
            record.built_at,
            record.build_status,
        ),
    )
    return record


def _set_build_status(conn: sqlite3.Connection, index_name: str, status: str) -> None:
    _require_v9(conn)
    _validate_index_name(index_name)
    cur = conn.cursor()
    row = cur.execute(
        "SELECT build_status FROM zm_m8_index_versions WHERE index_name=?",
        (index_name,),
    ).fetchone()
    if row is None:
        raise DerivedIndexError("no_build_in_progress", index_name)
    cur.execute(
        "UPDATE zm_m8_index_versions SET build_status=? WHERE index_name=?",
        (status, index_name),
    )


def publish_index_build(conn: sqlite3.Connection, index_name: str) -> None:
    """Promote a completed build to ``published`` (the usable state)."""
    _set_build_status(conn, index_name, BUILD_STATUS_PUBLISHED)


def fail_index_build(conn: sqlite3.Connection, index_name: str) -> None:
    """Mark a build ``failed`` so no partial index is ever treated as usable."""
    _set_build_status(conn, index_name, BUILD_STATUS_FAILED)


def get_index_version(
    conn: sqlite3.Connection, index_name: str
) -> Optional[IndexVersionRecord]:
    """Return the registry row for ``index_name``, or ``None``."""
    _require_v9(conn)
    _validate_index_name(index_name)
    row = conn.execute(
        "SELECT index_name, version, source_cutoff, canonical_fingerprint, "
        "built_at, build_status FROM zm_m8_index_versions WHERE index_name=?",
        (index_name,),
    ).fetchone()
    if row is None:
        return None
    return IndexVersionRecord(
        index_name=row[0],
        version=row[1],
        source_cutoff=row[2],
        canonical_fingerprint=row[3],
        built_at=row[4],
        build_status=row[5],
    )


def list_published_indexes(conn: sqlite3.Connection) -> list[IndexVersionRecord]:
    """Return published registry rows in deterministic ``index_name`` order."""
    _require_v9(conn)
    rows = conn.execute(
        "SELECT index_name, version, source_cutoff, canonical_fingerprint, "
        "built_at, build_status FROM zm_m8_index_versions "
        "WHERE build_status=? ORDER BY index_name ASC",
        (BUILD_STATUS_PUBLISHED,),
    ).fetchall()
    return [
        IndexVersionRecord(
            index_name=row[0],
            version=row[1],
            source_cutoff=row[2],
            canonical_fingerprint=row[3],
            built_at=row[4],
            build_status=row[5],
        )
        for row in rows
    ]


def derived_state_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    """Deterministic snapshot of derived M8 state, for rebuild-equivalence checks.

    Rows are ordered by their stable logical identity (never by ``rowid``), so
    two independent rebuilds of the same canonical state produce equal
    snapshots.
    """
    _require_v9(conn)
    cur = conn.cursor()
    snapshot: dict[str, Any] = {}
    snapshot["zm_entities"] = [
        tuple(row)
        for row in cur.execute(
            "SELECT entity_id, entity_type, canonical_name, profile_id, project_id, "
            "knowledge_space_id, lifecycle_status, content_hash "
            "FROM zm_entities ORDER BY entity_id ASC"
        ).fetchall()
    ]
    snapshot["zm_entity_mentions"] = [
        tuple(row)
        for row in cur.execute(
            "SELECT mention_id, entity_id, source_event_id, span_start, span_end, "
            "mention_text_hash, content_hash "
            "FROM zm_entity_mentions ORDER BY mention_id ASC"
        ).fetchall()
    ]
    snapshot["zm_graph_edges"] = [
        tuple(row)
        for row in cur.execute(
            "SELECT edge_id, from_resource_type, from_resource_id, relation_type, "
            "to_resource_type, to_resource_id, profile_id, project_id, "
            "knowledge_space_id, lifecycle_status, content_hash "
            "FROM zm_graph_edges ORDER BY edge_id ASC"
        ).fetchall()
    ]
    snapshot["zm_temporal_index"] = [
        tuple(row)
        for row in cur.execute(
            "SELECT resource_type, resource_id, created_at, observed_at, effective_at, "
            "valid_from, valid_until, superseded_at, lifecycle_status, provenance_hash "
            "FROM zm_temporal_index ORDER BY resource_type ASC, resource_id ASC"
        ).fetchall()
    ]
    return snapshot


def describe_derived_foundation() -> dict[str, Any]:
    """Introspectable description of the M8.1 derived foundation."""
    return {
        "projection_version": PROJECTION_VERSION,
        "schema_version": 10,
        "derived_tables": list(M8_DERIVED_TABLES),
        "derived_indexes": list(M8_DERIVED_INDEXES),
        "rebuildable_tables": list(_REBUILDABLE_TABLES),
        "canonical_store": "jsonl",
        "sqlite_is_derived": True,
        # M8.2 implements deterministic graph projection over these tables;
        # M8.4 implements bounded authorization-first temporal as-of/history
        # reads; M8.5 implements the approved deterministic calibration engine
        # (request-time only — no calibration table is added to v9).
        "projection_implemented": True,
        "traversal_implemented": False,
        "temporal_query_implemented": True,
        "calibration_scoring_implemented": True,
    }


def m8_derived_table_names() -> Sequence[str]:
    """The v9 derived table names (stable order)."""
    return M8_DERIVED_TABLES


__all__ = [
    "PROJECTION_VERSION",
    "KNOWN_INDEX_NAMES",
    "BUILD_STATUS_BUILDING",
    "BUILD_STATUS_PUBLISHED",
    "BUILD_STATUS_FAILED",
    "DerivedIndexError",
    "IndexVersionRecord",
    "m8_tables_present",
    "clear_m8_derived_state",
    "m8_derived_state_is_empty",
    "compute_canonical_fingerprint",
    "begin_index_build",
    "publish_index_build",
    "fail_index_build",
    "get_index_version",
    "list_published_indexes",
    "derived_state_snapshot",
    "describe_derived_foundation",
    "m8_derived_table_names",
]
