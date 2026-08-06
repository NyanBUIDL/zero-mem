"""M2.2 migration: create zm_ingest_checkpoint and zm_ingest_log (schema version 2).

These tables support idempotent, resumable ingestion of canonical JSONL into the
derived SQLite layer. `zm_ingest_checkpoint` records the last committed line and a
consumed-prefix hash (sha256 over the exact bytes of lines 1..last_line_number) so
a resumed run can detect tampering with already-consumed bytes. `zm_ingest_log` is a
committed, sanitized record of each finalized ingestion outcome (NOT a dead-letter
store). Both are additive over v1; downgrade drops them, returning the DB to v1.
"""
from __future__ import annotations


ZM_INGEST_CHECKPOINT_DDL = """
CREATE TABLE zm_ingest_checkpoint (
  jsonl_path          TEXT PRIMARY KEY,
  last_line_number    INTEGER NOT NULL,
  last_event_id       TEXT,
  last_sequence       INTEGER,
  consumed_prefix_hash TEXT NOT NULL,
  updated_at          TEXT NOT NULL
);
"""

ZM_INGEST_LOG_DDL = """
CREATE TABLE zm_ingest_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  jsonl_path      TEXT NOT NULL,
  line_number     INTEGER NOT NULL,
  outcome         TEXT NOT NULL,
  event_id        TEXT,
  content_hash    TEXT,
  diagnostic_code TEXT,
  recorded_at     TEXT NOT NULL
);
"""


def up(conn, note: str) -> None:
    """Apply migration 2: add the ingest checkpoint and ingest-log tables."""
    cur = conn.cursor()
    cur.execute(ZM_INGEST_CHECKPOINT_DDL)
    cur.execute(ZM_INGEST_LOG_DDL)


def down(conn, note: str) -> None:
    """Reverse migration 2: drop the ingest tables, returning to v1."""
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS zm_ingest_log")
    cur.execute("DROP TABLE IF EXISTS zm_ingest_checkpoint")


__all__ = ["up", "down"]
