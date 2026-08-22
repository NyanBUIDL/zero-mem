"""v1.3.0 migration: add zm_meta.knowledge_space_id (schema version 11).

V130-02 — additive, derived-state-only change. The canonical JSONL envelope
already carries ``knowledge_space_id``; this column denormalizes it onto the
event row so structured queries and FTS search can enforce the knowledge-space
scope exactly like the corpus/graph/temporal layers do. NULL = unscoped =
visible under global-default-read (DECISIONS D-2026-08-22-03, user-approved).

Rebuildable: the full-replay path (``rebuild_from_jsonl``) recreates the column
from the canonical envelope — proven by tests/unit/test_v130_02_ks_filter.py.
"""
from __future__ import annotations

import sqlite3

ADD_COLUMN_SQL = "ALTER TABLE zm_meta ADD COLUMN knowledge_space_id TEXT"
ADD_INDEX_SQL = "CREATE INDEX IF NOT EXISTS idx_zm_meta_ks ON zm_meta(knowledge_space_id)"
DROP_INDEX_SQL = "DROP INDEX IF EXISTS idx_zm_meta_ks"
# SQLite supports DROP COLUMN since 3.35; older builds fall back to the documented
# copy-drop-rename dance. We require >=3.35 semantics and fail closed otherwise.
DROP_COLUMN_SQL = "ALTER TABLE zm_meta DROP COLUMN knowledge_space_id"


def up(conn: sqlite3.Connection, note: str) -> None:
    """Apply migration 11: add the ks column + index to zm_meta.

    Purely additive: no existing column or row value is modified. Existing rows
    get NULL (= unscoped), which preserves global-default-read visibility.
    """
    cur = conn.cursor()
    cols = {row[1] for row in cur.execute("PRAGMA table_info(zm_meta)").fetchall()}
    if "knowledge_space_id" in cols:
        return  # idempotent
    cur.execute(ADD_COLUMN_SQL)
    cur.execute(ADD_INDEX_SQL)


def down(conn: sqlite3.Connection, note: str) -> None:
    """Reverse migration 11: drop the index then the column.

    The dropped values are recoverable from canonical JSONL replay.
    """
    cur = conn.cursor()
    cur.execute(DROP_INDEX_SQL)
    cols = {row[1] for row in cur.execute("PRAGMA table_info(zm_meta)").fetchall()}
    if "knowledge_space_id" not in cols:
        return  # idempotent
    try:
        cur.execute(DROP_COLUMN_SQL)
    except sqlite3.OperationalError as exc:
        raise sqlite3.OperationalError(
            "migration-11 down requires SQLite >= 3.35 (ALTER TABLE DROP COLUMN)"
        ) from exc
