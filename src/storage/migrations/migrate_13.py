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

#: Bounded-memory backfill: zm_meta is streamed in fixed-size batches so a
#: large store does not load the full table into RAM during upgrade (review P2).
_BACKFILL_BATCH_SIZE = 1000


def _backfill_batches(conn: sqlite3.Connection, batch_size: int = _BACKFILL_BATCH_SIZE) -> None:
    """Stream legacy zm_meta.knowledge_space_id into the junction in batches.

    ADR-V160-01 sec2: only a NON-EMPTY string legacy is promoted; NULL and
    whitespace-only legacy stay unscoped (never backfilled). The blank check
    uses str.strip() (exact parity with ingest _knowledge_spaces) because
    SQLite TRIM() strips only U+0020 — tab, newline, CR and Unicode whitespace
    would otherwise be promoted.

    Type boundary (C2 review P1): SQLite TEXT affinity (migrate_11 TEXT
    column) collapses a numeric legacy into text '123', indistinguishable at
    migration time from a legitimate string id "123" — the original type is
    not recoverable here. Numeric-origin values are therefore promoted as
    text; the AUTHORITATIVE malformed-type gate is canonical replay
    (rebuild_from_jsonl, plan C3) which re-derives from the JSONL where the
    true type lives. Capture (C1) and ingest (C2) already reject/ignore
    non-string legacy going forward.

    Memory bound (review P2): a dedicated read cursor streams via fetchmany
    while a separate write cursor runs executemany — never fetchall of the
    full table, and the INSERTs cannot reset the pending SELECT results.
    """
    src = conn.cursor()
    dst = conn.cursor()
    src.execute(
        "SELECT event_id, knowledge_space_id FROM zm_meta "
        "WHERE knowledge_space_id IS NOT NULL")
    while True:
        chunk = src.fetchmany(batch_size)
        if not chunk:
            return
        rows = [
            (event_id, ks)
            for event_id, ks in chunk
            if isinstance(ks, str) and ks.strip()
        ]
        if rows:
            dst.executemany(
                f"INSERT OR IGNORE INTO {_TABLE} (event_id, knowledge_space_id) "
                "VALUES (?,?)",
                rows,
            )


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
    _backfill_batches(conn)


def down(conn: sqlite3.Connection, note: str) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {_TABLE}")
