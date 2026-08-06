"""M2.1 migration: create zm_meta and zm_migrations (schema version 1).

This is the first, additive-only migration. It establishes the metadata table
(zm_meta) and the migration ledger (zm_migrations). No data is ingested here;
the SQLite store is a derived projection of the canonical JSONL stream and is
populated by later M2 increments.
"""
from __future__ import annotations


ZM_META_DDL = """
CREATE TABLE zm_meta (
  event_id            TEXT PRIMARY KEY,
  trace_id            TEXT NOT NULL,
  event_type          TEXT NOT NULL,
  source              TEXT NOT NULL,
  schema_version      INTEGER NOT NULL,
  created_at          TEXT NOT NULL,
  observed_at         TEXT NOT NULL,
  sequence            INTEGER NOT NULL,
  session_id          TEXT,
  profile_id          TEXT,
  project_id          TEXT,
  task_id             TEXT,
  turn_id             TEXT,
  parent_trace_id     TEXT,
  lifecycle_status    TEXT NOT NULL,
  verification_status TEXT NOT NULL,
  confidence          TEXT NOT NULL,
  sensitivity         TEXT NOT NULL,
  retention           TEXT NOT NULL,
  content_hash        TEXT NOT NULL,
  redaction_applied   INTEGER NOT NULL,
  ingested_at         TEXT NOT NULL,
  origin_jsonl        TEXT NOT NULL
);
"""

ZM_MIGRATIONS_DDL = """
CREATE TABLE zm_migrations (
  version   INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL,
  note       TEXT
);
"""


def up(conn, note: str) -> None:
    """Apply migration 1: create the ledger first, then the metadata table."""
    cur = conn.cursor()
    cur.execute(ZM_MIGRATIONS_DDL)
    cur.execute(ZM_META_DDL)


def down(conn, note: str) -> None:
    """Reverse migration 1: remove the metadata table and the ledger.

    The ledger row for version 1 is removed by the runner before this call, so
    dropping the table is safe and leaves the database at version 0.
    """
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS zm_meta")
    cur.execute("DROP TABLE IF EXISTS zm_migrations")


__all__ = ["up", "down"]
