"""M2.6 migration: retention tombstones, deletion audit, and their indexes (schema version 6).

Decision B (logical deletion only):
- Canonical JSONL is NEVER modified, deleted, truncated, rewritten, or compacted.
- Deletion is represented by an explicit append-only tombstone event (a JSONL line) whose
  derived state is projected here.
- ``zm_tombstones``: one row per deletion event (PK = deletion_event_id), recording the target,
  reason/scope (only if explicitly supplied), verifier/evidence, and apply status
  ('applied' | 'pending_unknown_target').
- ``zm_deletion_audit``: an append-only, sanitized audit log of every deletion action. No raw
  payload, secret, or exception text is stored.
- No FK constraint on target_event_id: a tombstone may reference a target that has not yet
  arrived (pending_unknown_target), so a hard FK would block order-independent rebuild.

Downgrade (v6 -> v5) drops both tables + indexes, returning to v5 (tombstone history is lost,
but zm_lifecycle.current_state='deleted' markers from prior events remain; re-ensure_schema to
v6 + re-ingest / rebuild_from_jsonl regenerates tombstones/audit from canonical JSONL).
"""

from __future__ import annotations

import sqlite3

TOMBSTONE_DDL = (
    "CREATE TABLE zm_tombstones ("
    "  tombstone_id      TEXT PRIMARY KEY,"        # == deletion_event_id (idempotent PK)
    "  target_event_id   TEXT NOT NULL,"
    "  target_trace_id   TEXT,"
    "  reason_code       TEXT,"
    "  approved_scope    TEXT,"                     # JSON-encoded approved scope object or NULL
    "  verifier          TEXT NOT NULL,"
    "  evidence_ref      TEXT,"
    "  deletion_event_id TEXT NOT NULL,"           # == tombstone_id
    "  current_state     TEXT NOT NULL DEFAULT 'deleted',"
    "  status            TEXT NOT NULL,"           # 'applied' | 'pending_unknown_target'
    "  created_at        TEXT NOT NULL"
    ")"
)

AUDIT_DDL = (
    "CREATE TABLE zm_deletion_audit ("
    "  audit_id          INTEGER PRIMARY KEY AUTOINCREMENT,"
    "  tombstone_id      TEXT NOT NULL,"
    "  target_event_id   TEXT NOT NULL,"
    "  target_trace_id   TEXT,"
    "  action            TEXT NOT NULL,"           # 'logical_delete'
    "  prior_lifecycle_state TEXT,"                # captured before transition (provenance)
    "  reason_code       TEXT,"
    "  approved_scope    TEXT,"
    "  deletion_event_id TEXT NOT NULL,"
    "  verifier          TEXT NOT NULL,"
    "  evidence_ref      TEXT,"
    "  diagnostic_code   TEXT,"                    # sanitized, fixed vocabulary
    "  recorded_at       TEXT NOT NULL"
    ")"
)

TOMBSTONE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_zm_tombstones_target ON zm_tombstones(target_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_zm_tombstones_status ON zm_tombstones(status)",
]

AUDIT_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_zm_deletion_audit_target ON zm_deletion_audit(target_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_zm_deletion_audit_tomb ON zm_deletion_audit(tombstone_id)",
]


def up(conn, note: str) -> None:
    """Apply migration 6: tombstone + deletion-audit tables and their indexes."""
    cur = conn.cursor()
    cur.execute(TOMBSTONE_DDL)
    cur.execute(AUDIT_DDL)
    for stmt in TOMBSTONE_INDEXES + AUDIT_INDEXES:
        cur.execute(stmt)


def down(conn, note: str) -> None:
    """Reverse migration 6: drop tombstone/audit tables + indexes (returns to v5)."""
    cur = conn.cursor()
    for name in (
        "idx_zm_deletion_audit_tomb",
        "idx_zm_deletion_audit_target",
        "idx_zm_tombstones_status",
        "idx_zm_tombstones_target",
    ):
        cur.execute(f"DROP INDEX IF EXISTS {name}")
    cur.execute("DROP TABLE IF EXISTS zm_deletion_audit")
    cur.execute("DROP TABLE IF EXISTS zm_tombstones")


__all__ = ["up", "down"]
