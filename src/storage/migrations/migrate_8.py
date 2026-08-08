"""M5.4 migration: access-grant derived tables (schema version 8).

Deterministic authorization-layer foundation. These tables are DERIVED,
disposable, and rebuildable from canonical `access_grant` JSONL events. They are
NOT the canonical source of truth (the JSONL stream is).

Implements the corrected M5 plan (§11.2, §14):
- `zm_access_grants`: derived projection of canonical access_grant events.
- `zm_policy_audit`: derived projection of canonical policy_decision events
  (audit foundation; populated per the M5 audit plan §15).

Lifecycle semantics (authoritative closed enum only):
- `lifecycle_status` is constrained to the CLOSED lifecycle enum ONLY
  (raw/observed/candidate/confirmed/active/superseded/conflicted/archived/deleted).
- `state` is a generic domain column (holds "revoked"); it is NOT a lifecycle
  value. `revoked` must never appear in `lifecycle_status`.
- Supersession is explicit (supersedes self-FK, nullable).

Downgrade (v8 -> v7) drops both v8 tables + indexes, returning to v7. It does
not touch M0-M7 tables, JSONL, artifacts, or prior migrations.
"""

from __future__ import annotations

import sqlite3

# Closed lifecycle enum (master spec §7.1). Used for every lifecycle_status CHECK.
_LIFECYCLE_ENUM = (
    "'raw','observed','candidate','confirmed','active',"
    "'superseded','conflicted','archived','deleted'"
)

# ---- DDL ----------------------------------------------------------------------

GRANTS_DDL = f"""
CREATE TABLE zm_access_grants (
  grant_id         TEXT PRIMARY KEY,
  subject_profile  TEXT NOT NULL,
  operation        TEXT NOT NULL CHECK (operation IN ('READ','WRITE')),
  target_type      TEXT NOT NULL
                      CHECK (target_type IN ('profile','project','knowledge_space','global')),
  target_id        TEXT NOT NULL,
  resource_types   TEXT,                -- JSON list or NULL=all
  state            TEXT,                -- generic domain state, e.g. 'revoked'
  lifecycle_status TEXT NOT NULL DEFAULT 'candidate'
                      CHECK (lifecycle_status IN ({_LIFECYCLE_ENUM})),
  supersedes       TEXT,
  replaced_by      TEXT,
  verification_ref TEXT,
  source_event_id  TEXT,
  trace_id         TEXT,
  session_id       TEXT,
  profile_id       TEXT,
  project_id       TEXT,
  created_at       TEXT NOT NULL,
  FOREIGN KEY (supersedes) REFERENCES zm_access_grants(grant_id),
  FOREIGN KEY (replaced_by) REFERENCES zm_access_grants(grant_id)
);
"""

POLICY_AUDIT_DDL = """
CREATE TABLE zm_policy_audit (
  decision_id      TEXT PRIMARY KEY,
  operation        TEXT NOT NULL CHECK (operation IN ('READ','WRITE')),
  requester        TEXT NOT NULL,
  target_scope     TEXT NOT NULL,
  allow            INTEGER NOT NULL,
  reason_code      TEXT NOT NULL,
  grant_refs       TEXT,                -- JSON list or NULL
  source_event_id  TEXT,
  trace_id         TEXT,
  session_id       TEXT,
  profile_id       TEXT,
  created_at       TEXT NOT NULL
);
"""

# ---- Indexes ------------------------------------------------------------------

GRANTS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_grants_subject_op "
    "ON zm_access_grants(subject_profile, operation)",
    "CREATE INDEX IF NOT EXISTS idx_grants_target "
    "ON zm_access_grants(target_type, target_id)",
    "CREATE INDEX IF NOT EXISTS idx_grants_lifecycle "
    "ON zm_access_grants(lifecycle_status)",
]

POLICY_AUDIT_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_policy_audit_requester "
    "ON zm_policy_audit(requester)",
    "CREATE INDEX IF NOT EXISTS idx_policy_audit_created "
    "ON zm_policy_audit(created_at)",
]

_DDL = [GRANTS_DDL, POLICY_AUDIT_DDL]

_INDEXES = GRANTS_INDEXES + POLICY_AUDIT_INDEXES


def up(conn: sqlite3.Connection, note: str) -> None:
    """Apply migration 8: create the access-grant + policy-audit derived tables."""
    cur = conn.cursor()
    for ddl in _DDL:
        cur.execute(ddl)
    for stmt in _INDEXES:
        cur.execute(stmt)


def down(conn: sqlite3.Connection, note: str) -> None:
    """Reverse migration 8: drop both v8 tables + indexes, returning to v7.

    Does not touch M0-M7 tables, JSONL, artifacts, or prior migrations.
    """
    cur = conn.cursor()
    for name in (
        "idx_policy_audit_created",
        "idx_policy_audit_requester",
        "idx_grants_lifecycle",
        "idx_grants_target",
        "idx_grants_subject_op",
    ):
        cur.execute(f"DROP INDEX IF EXISTS {name}")
    for table in ("zm_policy_audit", "zm_access_grants"):
        cur.execute(f"DROP TABLE IF EXISTS {table}")


__all__ = ["up", "down"]
