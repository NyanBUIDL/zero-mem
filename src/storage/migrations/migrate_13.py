"""v1.6.0 C2 migration: zm_event_spaces junction table (schema v13).

ADR-V160-01 sec4/sec5 — additive, derived-state-only. The junction is the
derived source of truth for multi-KS per event. zm_meta.knowledge_space_id
stays as a denormalized PRIMARY-KS (first of the canonical list, NULL if
empty) and is NOT rebuilt from the junction (both are direct projections from
canonical at ingest; rebuild re-ingests canonical, so both re-derive
faithfully).
"""
from __future__ import annotations

import sqlite3

_TABLE = "zm_event_spaces"


def up(conn: sqlite3.Connection, note: str) -> None:
    cur = conn.cursor()
    cur.execute(
        f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
        " event_id TEXT NOT NULL,"
        " knowledge_space_id TEXT NOT NULL,"
        " PRIMARY KEY (event_id, knowledge_space_id))"
    )
    cur.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{_TABLE}_ks ON {_TABLE}(knowledge_space_id)")
    # Backfill from legacy singular zm_meta.knowledge_space_id (pre-v13 rows).
    cur.execute(
        f"INSERT OR IGNORE INTO {_TABLE} (event_id, knowledge_space_id) "
        "SELECT event_id, knowledge_space_id FROM zm_meta "
        "WHERE knowledge_space_id IS NOT NULL")


def down(conn: sqlite3.Connection, note: str) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {_TABLE}")
