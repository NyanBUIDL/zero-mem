"""M4.1 migration: project-memory derived tables (schema version 7).

Deterministic project-memory layer foundation. These tables are DERIVED,
disposable, and rebuildable from canonical JSONL + the M2 artifact substrate
(zm_artifacts). They are NOT the canonical source of truth.

Implements the corrected M4 key semantics (resolved from the master spec and
verified M2 evidence):
- `lifecycle_status` is constrained to the CLOSED lifecycle enum ONLY
  (raw/observed/candidate/confirmed/active/superseded/conflicted/archived/deleted).
- Domain-specific status (proposed/accepted/satisfied/blocked/rejected/...) lives
  in a separate generic `state` column, never in `lifecycle_status`.
- `decision_key` / `state_key` are explicit stable logical keys ONLY. They are
  NULL when not supplied; `trace_id` is NEVER used as a fallback logical key.
- Active-uniqueness partial unique indexes fire only when the logical key is
  non-NULL (SQLite treats NULL keys as distinct, so NULL-key rows never collide).
- Supersession is explicit (supersedes/replaced_by self-FKs, nullable).

Downgrade (v7 -> v6) drops all six M4 tables + indexes, returning to v6. It does
not touch M0-M3 tables, JSONL, artifacts, or prior migrations.
"""

from __future__ import annotations

import sqlite3

# Closed lifecycle enum (master spec §7.1). Used for every lifecycle_status CHECK.
_LIFECYCLE_ENUM = (
    "'raw','observed','candidate','confirmed','active',"
    "'superseded','conflicted','archived','deleted'"
)

# ---- DDL ----------------------------------------------------------------------

CHARTERS_DDL = f"""
CREATE TABLE zm_project_charters (
  charter_id        TEXT PRIMARY KEY,
  project_id        TEXT NOT NULL,
  version           INTEGER NOT NULL DEFAULT 1,
  name              TEXT,
  goal              TEXT,
  scope             TEXT,
  non_goals         TEXT,
  constraints       TEXT,
  architecture_principles TEXT,
  success_criteria  TEXT,
  lifecycle_status  TEXT NOT NULL DEFAULT 'candidate'
                      CHECK (lifecycle_status IN ({_LIFECYCLE_ENUM})),
  state             TEXT,
  source_event_id   TEXT,
  trace_id          TEXT,
  session_id        TEXT,
  profile_id        TEXT,
  created_at        TEXT NOT NULL,
  updated_at        TEXT,
  supersedes        TEXT,
  verification_ref  TEXT,
  FOREIGN KEY (supersedes) REFERENCES zm_project_charters(charter_id)
);
"""

REQUIREMENTS_DDL = f"""
CREATE TABLE zm_requirements (
  requirement_id    TEXT PRIMARY KEY,
  project_id        TEXT NOT NULL,
  statement         TEXT,
  source_event_id   TEXT,
  created_at        TEXT NOT NULL,
  lifecycle_status  TEXT NOT NULL DEFAULT 'candidate'
                      CHECK (lifecycle_status IN ({_LIFECYCLE_ENUM})),
  state             TEXT,
  verification_status TEXT NOT NULL DEFAULT 'none',
  supersedes        TEXT,
  replaced_by       TEXT,
  linked_decision_ids   TEXT,
  linked_artifact_ids   TEXT,
  linked_verification_ids TEXT,
  trace_id          TEXT,
  session_id        TEXT,
  profile_id        TEXT,
  FOREIGN KEY (supersedes) REFERENCES zm_requirements(requirement_id),
  FOREIGN KEY (replaced_by) REFERENCES zm_requirements(requirement_id)
);
"""

DECISIONS_DDL = f"""
CREATE TABLE zm_decisions (
  decision_id       TEXT PRIMARY KEY,
  project_id        TEXT NOT NULL,
  scope             TEXT,
  decision_key      TEXT,
  statement         TEXT,
  rationale_ref     TEXT,
  alternatives      TEXT,
  source_event_id   TEXT,
  lifecycle_status  TEXT NOT NULL DEFAULT 'candidate'
                      CHECK (lifecycle_status IN ({_LIFECYCLE_ENUM})),
  state             TEXT,
  supersedes_id     TEXT,
  replaced_by       TEXT,
  effective_at      TEXT,
  linked_requirement_ids TEXT,
  linked_artifact_ids   TEXT,
  linked_verification_ids TEXT,
  trace_id          TEXT,
  session_id        TEXT,
  profile_id        TEXT,
  FOREIGN KEY (supersedes_id) REFERENCES zm_decisions(decision_id),
  FOREIGN KEY (replaced_by) REFERENCES zm_decisions(decision_id)
);
"""

PROJECT_STATE_DDL = f"""
CREATE TABLE zm_project_state (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id        TEXT NOT NULL,
  scope             TEXT,
  state_key         TEXT,
  state_value       TEXT,
  state_ref         TEXT,
  lifecycle_status  TEXT NOT NULL DEFAULT 'candidate'
                      CHECK (lifecycle_status IN ({_LIFECYCLE_ENUM})),
  verification_status TEXT NOT NULL DEFAULT 'none',
  effective_at      TEXT,
  supersedes        TEXT,
  source_event_id   TEXT,
  trace_id          TEXT,
  session_id        TEXT,
  profile_id        TEXT
);
"""

VERIFICATIONS_DDL = f"""
CREATE TABLE zm_verifications (
  verification_id   TEXT PRIMARY KEY,
  subject_type      TEXT,
  subject_id        TEXT,
  project_id        TEXT,
  method            TEXT,
  command_ref       TEXT,
  observed_result   TEXT,
  tested_commit     TEXT,
  source_event_id   TEXT,
  timestamp         TEXT,
  verification_status TEXT NOT NULL DEFAULT 'none',
  artifact_references TEXT
);
"""

PROJECT_ARTIFACTS_DDL = """
CREATE TABLE zm_project_artifacts (
  artifact_id       TEXT NOT NULL,
  project_id        TEXT NOT NULL,
  artifact_type     TEXT,
  version           TEXT,
  safe_reference    TEXT,
  source_event_id   TEXT,
  created_at        TEXT NOT NULL,
  verification_status TEXT NOT NULL DEFAULT 'none',
  linked_requirement_ids TEXT,
  linked_decision_ids   TEXT,
  linked_state_keys TEXT,
  PRIMARY KEY (artifact_id, project_id),
  FOREIGN KEY (artifact_id) REFERENCES zm_artifacts(artifact_id)
);
"""

# ---- Indexes ------------------------------------------------------------------

CHARTERS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_zm_charters_project ON zm_project_charters(project_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_zm_charters_active "
    "ON zm_project_charters(project_id) WHERE lifecycle_status='active'",
]

REQUIREMENTS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_zm_requirements_project ON zm_requirements(project_id)",
]

DECISIONS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_zm_decisions_project ON zm_decisions(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_zm_decisions_scope ON zm_decisions(scope)",
    # Active uniqueness ONLY when decision_key is non-NULL (NULL keys never collide).
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_zm_decisions_active "
    "ON zm_decisions(project_id, scope, decision_key) "
    "WHERE lifecycle_status='active' AND decision_key IS NOT NULL",
]

PROJECT_STATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_zm_project_state_project ON zm_project_state(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_zm_project_state_key ON zm_project_state(state_key)",
    # Active uniqueness ONLY when state_key is non-NULL (NULL keys never collide).
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_zm_project_state_active "
    "ON zm_project_state(project_id, scope, state_key) "
    "WHERE lifecycle_status='active' AND state_key IS NOT NULL",
]

VERIFICATIONS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_zm_verifications_subject ON zm_verifications(subject_id)",
    "CREATE INDEX IF NOT EXISTS idx_zm_verifications_project ON zm_verifications(project_id)",
]

PROJECT_ARTIFACTS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_zm_project_artifacts_project ON zm_project_artifacts(project_id)",
]

_DDL = [
    CHARTERS_DDL,
    REQUIREMENTS_DDL,
    DECISIONS_DDL,
    PROJECT_STATE_DDL,
    VERIFICATIONS_DDL,
    PROJECT_ARTIFACTS_DDL,
]

_INDEXES = (
    CHARTERS_INDEXES
    + REQUIREMENTS_INDEXES
    + DECISIONS_INDEXES
    + PROJECT_STATE_INDEXES
    + VERIFICATIONS_INDEXES
    + PROJECT_ARTIFACTS_INDEXES
)


def up(conn: sqlite3.Connection, note: str) -> None:
    """Apply migration 7: create the six M4 project-memory derived tables + indexes."""
    cur = conn.cursor()
    for ddl in _DDL:
        cur.execute(ddl)
    for stmt in _INDEXES:
        cur.execute(stmt)


def down(conn: sqlite3.Connection, note: str) -> None:
    """Reverse migration 7: drop all M4 tables + indexes, returning to v6.

    Does not touch M0-M3 tables, JSONL, artifacts, or prior migrations.
    """
    cur = conn.cursor()
    for name in (
        "uq_zm_project_state_active",
        "uq_zm_decisions_active",
        "uq_zm_charters_active",
        "idx_zm_project_artifacts_project",
        "idx_zm_verifications_project",
        "idx_zm_verifications_subject",
        "idx_zm_project_state_key",
        "idx_zm_project_state_project",
        "idx_zm_decisions_scope",
        "idx_zm_decisions_project",
        "idx_zm_requirements_project",
        "idx_zm_charters_project",
    ):
        cur.execute(f"DROP INDEX IF EXISTS {name}")
    for table in (
        "zm_project_artifacts",
        "zm_verifications",
        "zm_project_state",
        "zm_decisions",
        "zm_requirements",
        "zm_project_charters",
    ):
        cur.execute(f"DROP TABLE IF EXISTS {table}")


__all__ = ["up", "down"]
