"""v1.3.3 migration: add provenance columns to zm_verifications (schema v12).

DEF-007 — additive, derived-state-only change. Every other M4 project-memory
table (zm_project_charters, zm_project_requirements, zm_project_decisions,
zm_project_state) carries ``trace_id`` / ``session_id`` / ``profile_id``
provenance columns (migrate_7). ``zm_verifications`` alone was created without
them even though the canonical ``VerificationOp`` contract
(src/project_memory/contracts.py) accepts and validates those fields — the
projector silently dropped them on insert.

Consequences fixed by this migration:
  * EvidenceSet items built from verification rows surfaced
    ``profile_id=None``/``lifecycle=None``, which made M8.5 scope calibration
    classify an in-scope, fully authorized verification as
    ``excluded_unauthorized_scope`` (score unavailable).
  * M8.6 authority checks assert a closed lifecycle enum; a non-enum ``None``
    leaked through the M7 evidence mapping.

Rebuildable: values are recovered from the canonical VerificationOp payload on
full replay; the projector now persists them.
"""
from __future__ import annotations

import sqlite3

_TABLE = "zm_verifications"
_ADD_COLUMNS: tuple[tuple[str, str], ...] = (
    ("trace_id", "ALTER TABLE zm_verifications ADD COLUMN trace_id TEXT"),
    ("session_id", "ALTER TABLE zm_verifications ADD COLUMN session_id TEXT"),
    ("profile_id", "ALTER TABLE zm_verifications ADD COLUMN profile_id TEXT"),
)


def up(conn: sqlite3.Connection, note: str) -> None:
    """Apply migration 12: add the missing provenance columns.

    Purely additive: no existing column or row value is modified. Existing rows
    get NULL until the next canonical replay backfills them.
    """
    cur = conn.cursor()
    cols = {row[1] for row in cur.execute(f"PRAGMA table_info({_TABLE})").fetchall()}
    for name, sql in _ADD_COLUMNS:
        if name not in cols:
            cur.execute(sql)


def down(conn: sqlite3.Connection, note: str) -> None:
    """Reverse migration 12: drop the provenance columns.

    The dropped values are recoverable from canonical JSONL replay.
    """
    cur = conn.cursor()
    cols = {row[1] for row in cur.execute(f"PRAGMA table_info({_TABLE})").fetchall()}
    for name, sql in reversed(_ADD_COLUMNS):
        if name not in cols:
            continue
        try:
            cur.execute(f"ALTER TABLE {_TABLE} DROP COLUMN {name}")
        except sqlite3.OperationalError as exc:
            raise sqlite3.OperationalError(
                f"migration 12 down requires SQLite >= 3.35 DROP COLUMN: {exc}"
            ) from exc
