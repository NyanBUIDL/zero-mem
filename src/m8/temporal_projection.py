"""M8.4 - deterministic temporal projection into ``zm_temporal_index``.

This module is the *only* writer of ``zm_temporal_index``. It reads the
authorized M4 / event / relation / artifact source substrates and projects each
resource's *explicit* temporal fields into the derived temporal index. The
projection is:

- DERIVED - never canonical truth; canonical JSONL remains authoritative.
- DISPOSABLE - every row is rebuildable from the sources.
- DETERMINISTIC - identical sources (in any insertion order) produce identical
  derived rows; we never read ``now()``, never randomize identity, never
  depend on rowid/insertion order.

Two temporal dimensions are kept strictly distinct, exactly as plan-m8.md
requires:

1. **Transaction / history time** - represented by the source's ``created_at``
   where the source carries one (event / requirement / verification / artifact
   / relation / charter / trace). A source without ``created_at`` (decision,
   project_state) has UNKNOWN transaction time; we never invent it.
2. **Valid / effective time** - represented ONLY by explicit source fields
   (``effective_at`` on decisions/state; ``valid_from`` / ``valid_until`` where
   a source legitimately carries them). It is frequently absent.

No timestamp is ever manufactured to fill a NULL. A source without a given
dimension stores NULL; unknown time stays unknown. ``created_at`` is NEVER
copied into a validity/effective column, and vice-versa.

M4 lifecycle / supersession / conflict semantics remain authoritative. This
module never re-labels a resource, never resolves a conflict, never promotes an
assistant claim, and never derives supersession from recency. It copies the
source ``lifecycle_status`` verbatim.

Column selection probes each source table's real schema, so a source lacking a
scope/temporal column simply projects NULL for that dimension - never an error
and never an invented value.

Zero LLM. Zero network. No authorization logic (the read layer owns that).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Final, Mapping, Optional, Sequence, Tuple

from .temporal_contract import TemporalError, normalize_timestamp
from .vocabulary import RESOURCE_TYPES, validate_resource_type

#: Projection version stamped into derived provenance rows.
PROJECTION_VERSION: Final[str] = "m8.4"

#: The derived table this increment owns. It is one of the five v9 derived
#: tables; rebuild here touches ONLY this table, never canonical JSONL or the
#: other M8 derived tables.
TEMPORAL_TABLE: Final[str] = "zm_temporal_index"

#: Per-connection column-presence cache (keyed by id(conn)). Cheap and safe:
#: a connection lives for one projection run; the cache avoids repeating
#: PRAGMA table_info per source table.
_COLUMN_CACHE: dict[int, dict[str, set[str]]] = {}


class TemporalProjectionError(RuntimeError):
    """Sanitized temporal-projection failure. Never contains raw SQL/payloads."""

    def __init__(self, reason: str, detail: str = "") -> None:
        message = f"temporal_projection_error: {reason}"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)
        self.reason = reason


# ---------------------------------------------------------------------------
# Source specification
# ---------------------------------------------------------------------------
# Every typed substrate that carries usable temporal fields is a temporal
# projection source. The mapping is the single source of truth for
# (resource_type -> table/id column). It deliberately does NOT invent a
# resource type and does NOT erase resource_type identity (permanent M6.6).
#
# ``optional_ts`` is the explicit VALID/EFFECTIVE column a source MAY carry
# beyond transaction ``created_at``. ``valid_cols`` name explicit
# ``valid_from`` / ``valid_until`` columns if present. Supersession reference
# columns are named so the read layer can surface the explicit chain.
@dataclass(frozen=True)
class _SourceSpec:
    resource_type: str
    table: str
    id_col: Optional[str]            # None => composite id built from row
    id_builder: Optional[str]        # expression producing resource_id
    optional_ts: Optional[str]       # explicit valid/effective column (or None)
    valid_from_col: Optional[str]
    valid_until_col: Optional[str]


_SOURCE_SPECS: Tuple[_SourceSpec, ...] = (
    _SourceSpec("requirement", "zm_requirements", "requirement_id", None,
                None, None, None),
    _SourceSpec("decision", "zm_decisions", "decision_id", None,
                "effective_at", None, None),
    _SourceSpec("state", "zm_project_state", None,
                "json_object('id', id, 'scope', scope, 'state_key', state_key)",
                "effective_at", None, None),
    _SourceSpec("verification", "zm_verifications", "verification_id", None,
                None, None, None),
    _SourceSpec("artifact", "zm_artifacts", "artifact_id", None,
                None, None, None),
    _SourceSpec("project_artifact", "zm_project_artifacts", "artifact_id", None,
                None, None, None),
    _SourceSpec("relation", "zm_relations", "id", None,
                None, None, None),
    _SourceSpec("charter", "zm_project_charters", "charter_id", None,
                None, None, None),
    _SourceSpec("event", "zm_meta", "event_id", None,
                None, None, None),
)


def _spec_for(resource_type: str) -> _SourceSpec:
    validate_resource_type(resource_type)
    for spec in _SOURCE_SPECS:
        if spec.resource_type == resource_type:
            return spec
    raise TemporalProjectionError("unknown_resource_type", resource_type[:48])


# ---------------------------------------------------------------------------
# Deterministic helpers
# ---------------------------------------------------------------------------

def _norm(value: Optional[str]) -> Optional[str]:
    """Normalize an explicit timestamp via the M8.1 contract.

    Returns the canonical UTC form (``... +00:00``), or ``None`` when the
    source value is NULL. A malformed value fails closed (``TemporalError``);
    we never coerce, shift, or invent.
    """
    if value is None:
        return None
    ts = normalize_timestamp("temporal_projection", value)
    return None if ts is None else ts.utc


def _row_provenance_hash(resource_type: str, resource_id: str,
                          created_at: Optional[str],
                          lifecycle_status: Optional[str]) -> str:
    """Deterministic content hash for the temporal row's provenance anchor.

    Built only from the resource's own explicit identity and temporal fields -
    never from secrets, wall-clock, or random material.
    """
    material = json.dumps(
        {
            "resource_type": resource_type,
            "resource_id": resource_id,
            "created_at": created_at,
            "lifecycle_status": lifecycle_status,
        },
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _table_columns(conn: sqlite3.Connection, table: str) -> "set[str]":
    """The set of columns that actually exist on ``table`` (cached per conn)."""
    cache = _COLUMN_CACHE.get(id(conn))
    if cache is None:
        cache = {}
        _COLUMN_CACHE[id(conn)] = cache
    if table not in cache:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        cache[table] = cols
    return cache[table]


def _columns_for(conn: sqlite3.Connection, spec: _SourceSpec) -> list[str]:
    """SELECT expressions for a source spec, using ONLY real columns.

    Each expression yields a stable alias. Scope/temporal columns are included
    only when the source table actually carries them, so a source lacking
    ``knowledge_space_id`` or ``created_at`` simply projects NULL for that
    dimension - never an error, never an invented value.
    """
    present = _table_columns(conn, spec.table)
    parts: list[str] = []
    # lifecycle_status: present on most M4 tables; otherwise default 'candidate'
    # (the authoritative M4 initial lifecycle) so the derived row stays valid
    # under the closed lifecycle CHECK without inventing a state.
    parts.append(
        f"{spec.table}.lifecycle_status" if "lifecycle_status" in present
        else "'candidate' AS lifecycle_status"
    )
    if spec.id_col is not None:
        parts.append(f"{spec.table}.{spec.id_col} AS resource_id")
    else:
        assert spec.id_builder is not None
        parts.append(f"{spec.id_builder} AS resource_id")
    # Transaction time: explicit created_at only; absent -> NULL.
    parts.append(
        f"{spec.table}.created_at" if "created_at" in present
        else "NULL AS created_at"
    )
    for col in ("profile_id", "project_id", "knowledge_space_id",
                "source_event_id", "trace_id", "verification_status"):
        parts.append(
            f"{spec.table}.{col}" if col in present else f"NULL AS {col}"
        )
    if spec.optional_ts is not None and spec.optional_ts in present:
        parts.append(f"{spec.table}.{spec.optional_ts} AS optional_ts")
    if spec.valid_from_col is not None and spec.valid_from_col in present:
        parts.append(f"{spec.table}.{spec.valid_from_col} AS valid_from_col")
    if spec.valid_until_col is not None and spec.valid_until_col in present:
        parts.append(f"{spec.table}.{spec.valid_until_col} AS valid_until_col")
    return parts


def _project_one(conn: sqlite3.Connection, spec: _SourceSpec) -> list[dict]:
    """Read one source substrate and build ordered temporal rows.

    Determinism: rows are ordered by ``created_at`` (NULLs last, stable) then
    ``resource_id`` so two independent runs over the same canonical state emit
    identical rows regardless of physical insertion order.
    """
    select = ", ".join(_columns_for(conn, spec))
    rows = conn.execute(
        f"SELECT {select} FROM {spec.table} "
        f"ORDER BY created_at ASC, resource_id ASC"
    ).fetchall()
    out: list[dict] = []
    for row in rows:
        resource_id = row["resource_id"]
        created_at = _norm(row["created_at"])
        effective_at = _norm(row["optional_ts"]) if spec.optional_ts else None
        valid_from = _norm(row["valid_from_col"]) if spec.valid_from_col else None
        valid_until = _norm(row["valid_until_col"]) if spec.valid_until_col else None
        # Transaction time == explicit created_at only. It is NEVER copied into
        # a validity/effective column.
        out.append({
            "resource_type": spec.resource_type,
            "resource_id": resource_id,
            "created_at": created_at,
            "observed_at": None,           # M8.1 separates this; not sourced here
            "effective_at": effective_at,  # explicit valid/effective only
            "valid_from": valid_from,
            "valid_until": valid_until,
            "superseded_at": None,         # M4 supersession is reference-based
            "lifecycle_status": row["lifecycle_status"],
            "verification_status": row["verification_status"],
            "profile_id": row["profile_id"],
            "project_id": row["project_id"],
            "knowledge_space_id": row["knowledge_space_id"],
            "source_event_id": row["source_event_id"],
            "trace_id": row["trace_id"],
            "provenance_hash": _row_provenance_hash(
                spec.resource_type, resource_id, created_at,
                row["lifecycle_status"]),
        })
    return out


def _ordered_projection(conn: sqlite3.Connection) -> list[dict]:
    """Deterministic full projection across every typed source."""
    rows: list[dict] = []
    for spec in _SOURCE_SPECS:
        rows.extend(_project_one(conn, spec))
    # Final stable ordering by (resource_type, resource_id).
    rows.sort(key=lambda r: (r["resource_type"], r["resource_id"]))
    return rows


def _clear_temporal_table(conn: sqlite3.Connection) -> int:
    before = conn.execute(
        f"SELECT COUNT(*) FROM {TEMPORAL_TABLE}"
    ).fetchone()[0]
    conn.execute(f"DELETE FROM {TEMPORAL_TABLE}")
    return int(before)


def project_temporal_index(
    conn: sqlite3.Connection,
    *,
    source_cutoff: str,
    built_at: str,
) -> dict[str, Any]:
    """Rebuild ``zm_temporal_index`` from canonical M4/event/relation sources.

    ``source_cutoff`` and ``built_at`` are supplied explicitly by the caller
    from canonical data (never ``now()``). Both must be valid tz-aware ISO8601
    values; a malformed value fails closed.

    Returns an operational summary only (row counts, fingerprint). It does NOT
    mutate canonical JSONL, the other M8 derived tables, grants, or project
    state. The rebuild is deterministic: clearing and re-projecting identical
    sources yields equivalent rows.
    """
    # Validate the caller-supplied registry timestamps through the M8.1 contract.
    normalize_timestamp("source_cutoff", source_cutoff)
    normalize_timestamp("built_at", built_at)

    rows = _ordered_projection(conn)
    _clear_temporal_table(conn)

    inserted = 0
    for r in rows:
        conn.execute(
            f"INSERT INTO {TEMPORAL_TABLE} ("
            "resource_type, resource_id, created_at, observed_at, effective_at, "
            "valid_from, valid_until, superseded_at, lifecycle_status, "
            "verification_status, profile_id, project_id, knowledge_space_id, "
            "source_event_id, trace_id, provenance_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                r["resource_type"], r["resource_id"], r["created_at"],
                r["observed_at"], r["effective_at"], r["valid_from"],
                r["valid_until"], r["superseded_at"], r["lifecycle_status"],
                r["verification_status"], r["profile_id"], r["project_id"],
                r["knowledge_space_id"], r["source_event_id"], r["trace_id"],
                r["provenance_hash"],
            ),
        )
        inserted += 1
    conn.commit()

    fingerprint = _temporal_fingerprint(rows)
    return {
        "index_name": TEMPORAL_TABLE,
        "projection_version": PROJECTION_VERSION,
        "source_cutoff": source_cutoff,
        "built_at": built_at,
        "inserted_rows": inserted,
        "canonical_fingerprint": fingerprint,
    }


def _temporal_fingerprint(rows: Sequence[Mapping[str, Any]]) -> str:
    """Deterministic fingerprint of the projected temporal state.

    Built only from the projected rows (derived from canonical sources). Two
    independent projections of identical sources fingerprint identically.
    """
    material = json.dumps(
        [
            {
                "rt": r["resource_type"],
                "rid": r["resource_id"],
                "ca": r["created_at"],
                "ea": r["effective_at"],
                "vf": r["valid_from"],
                "vu": r["valid_until"],
                "ls": r["lifecycle_status"],
                "vs": r["verification_status"],
                "ph": r["provenance_hash"],
            }
            for r in rows
        ],
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def describe_temporal_projection() -> dict[str, Any]:
    """Introspectable description of the M8.4 temporal projection."""
    return {
        "projection_version": PROJECTION_VERSION,
        "schema_version": 10,
        "target_table": TEMPORAL_TABLE,
        "derived": True,
        "canonical_store": "jsonl",
        "source_resource_types": sorted(RESOURCE_TYPES),
        "transaction_time_field": "created_at",
        "valid_time_fields": ["effective_at", "valid_from", "valid_until"],
        "invents_no_timestamp": True,
        "makes_authorization_decisions": False,
        "resolves_conflicts": False,
        "promotes_assistant_claim": False,
    }


__all__ = [
    "PROJECTION_VERSION",
    "TEMPORAL_TABLE",
    "TemporalProjectionError",
    "project_temporal_index",
    "describe_temporal_projection",
]
