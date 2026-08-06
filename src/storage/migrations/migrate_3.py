"""M2.3 migration: create zm_lifecycle and zm_provenance (schema version 3).

These tables are the derived lifecycle-state and verification/provenance projections
over canonical JSONL. `zm_lifecycle` mirrors the observed `lifecycle_status` and reserves
`superseded_by` / `active_key` columns for M2.4 enforcement. `zm_provenance` seeds one
verification record per event from the envelope, with the verifier-rank stored as data only.

Both tables are additive over v2; downgrade drops them, returning the DB to v2.
"""
from __future__ import annotations


ZM_LIFECYCLE_DDL = """
CREATE TABLE zm_lifecycle (
  event_id      TEXT PRIMARY KEY,
  current_state TEXT NOT NULL,
  superseded_by TEXT,
  active_key    TEXT,
  updated_at    TEXT NOT NULL
);
"""

ZM_PROVENANCE_DDL = """
CREATE TABLE zm_provenance (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id            TEXT NOT NULL,
  verification_status TEXT NOT NULL,
  verifier            TEXT NOT NULL,
  evidence_ref        TEXT,
  recorded_at         TEXT NOT NULL
);
"""


def up(conn, note: str) -> None:
    """Apply migration 3: add the lifecycle and provenance projections."""
    cur = conn.cursor()
    cur.execute(ZM_LIFECYCLE_DDL)
    cur.execute(ZM_PROVENANCE_DDL)


def down(conn, note: str) -> None:
    """Reverse migration 3: drop the lifecycle and provenance tables, returning to v2."""
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS zm_provenance")
    cur.execute("DROP TABLE IF EXISTS zm_lifecycle")


__all__ = ["up", "down"]
