"""M2.5 migration: relational indexes and FTS5 full-text index (schema version 5).

- Relational indexes over zm_meta / zm_relations / zm_lifecycle / zm_scopes (no data; maintained
  automatically by SQLite; rebuildable).
- ``zm_fts`` FTS5 virtual table indexing APPROVED SANITIZED content only (the envelope's
  ``sanitized_content``; M1 redaction is fail-closed, so no raw secret reaches FTS).
- FTS5 capability detection: if the SQLite build lacks FTS5, ``zm_fts`` is skipped and the
  migration still succeeds (safe fallback); helpers consult ``FTS5_AVAILABLE``.
"""
from __future__ import annotations

import sqlite3

# Detected at import time; reflects whether this SQLite build can create FTS5 tables.
FTS5_AVAILABLE: bool = True


RELATIONAL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_zm_meta_trace      ON zm_meta(trace_id)",
    "CREATE INDEX IF NOT EXISTS idx_zm_meta_lifecycle  ON zm_meta(lifecycle_status)",
    "CREATE INDEX IF NOT EXISTS idx_zm_meta_verif      ON zm_meta(verification_status)",
    "CREATE INDEX IF NOT EXISTS idx_zm_meta_project    ON zm_meta(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_zm_meta_profile    ON zm_meta(profile_id)",
    "CREATE INDEX IF NOT EXISTS idx_zm_meta_created    ON zm_meta(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_zm_relations_from  ON zm_relations(from_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_zm_relations_to    ON zm_relations(to_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_zm_lifecycle_key   ON zm_lifecycle(active_key)",
    "CREATE INDEX IF NOT EXISTS idx_zm_lifecycle_state ON zm_lifecycle(current_state)",
    "CREATE INDEX IF NOT EXISTS idx_zm_scopes_type     ON zm_scopes(scope_type, scope_id)",
]

FTS5_DDL = (
    "CREATE VIRTUAL TABLE zm_fts USING fts5(event_id UNINDEXED, content)"
)


def _detect_fts5(conn) -> bool:
    cur = conn.cursor()
    cur.execute("PRAGMA compile_options")
    opts = {row[0] for row in cur.fetchall()}
    if any("FTS5" in o.upper() for o in opts):
        return True
    # Fallback probe (compile_options can be empty in some builds).
    try:
        conn.execute("CREATE VIRTUAL TABLE _fts5_probe USING fts5(x)")
        conn.execute("DROP TABLE _fts5_probe")
        return True
    except sqlite3.OperationalError:
        return False


def up(conn, note: str) -> None:
    """Apply migration 5: relational indexes + FTS5 (if available)."""
    global FTS5_AVAILABLE
    cur = conn.cursor()
    for stmt in RELATIONAL_INDEXES:
        cur.execute(stmt)
    FTS5_AVAILABLE = _detect_fts5(conn)
    if FTS5_AVAILABLE:
        try:
            cur.execute(FTS5_DDL)
        except sqlite3.OperationalError:
            FTS5_AVAILABLE = False


def down(conn, note: str) -> None:
    """Reverse migration 5: drop indexes + zm_fts (returns to v4)."""
    cur = conn.cursor()
    for name in (
        "idx_zm_meta_trace", "idx_zm_meta_lifecycle", "idx_zm_meta_verif",
        "idx_zm_meta_project", "idx_zm_meta_profile", "idx_zm_meta_created",
        "idx_zm_relations_from", "idx_zm_relations_to",
        "idx_zm_lifecycle_key", "idx_zm_lifecycle_state", "idx_zm_scopes_type",
    ):
        cur.execute(f"DROP INDEX IF EXISTS {name}")
    cur.execute("DROP TABLE IF EXISTS zm_fts")


__all__ = ["up", "down", "FTS5_AVAILABLE"]
