"""M2.4 migration: create zm_relations, zm_scopes, zm_artifacts (schema version 4).

These tables are the derived relation, scope-mapping, and artifact-metadata-registry
projections over canonical JSONL. Edges and scopes are derived only from envelope-present
signals (no inference). `zm_artifacts` records authorized artifact *metadata* references;
artifact content storage is deferred. All three are additive over v3; downgrade drops them,
returning the DB to v3.
"""
from __future__ import annotations


ZM_RELATIONS_DDL = """
CREATE TABLE zm_relations (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  from_event_id TEXT NOT NULL,
  to_event_id   TEXT NOT NULL,
  relation      TEXT NOT NULL,
  verifier      TEXT NOT NULL,
  evidence_ref  TEXT,
  created_at    TEXT NOT NULL,
  UNIQUE (from_event_id, to_event_id, relation)
);
"""

ZM_SCOPES_DDL = """
CREATE TABLE zm_scopes (
  scope_type   TEXT NOT NULL,
  scope_id     TEXT NOT NULL,
  display_name TEXT,
  parent_scope TEXT,
  created_at   TEXT NOT NULL,
  PRIMARY KEY (scope_type, scope_id)
);
"""

ZM_ARTIFACTS_DDL = """
CREATE TABLE zm_artifacts (
  artifact_id    TEXT PRIMARY KEY,
  content_hash   TEXT NOT NULL,
  kind           TEXT,
  retention      TEXT NOT NULL,
  origin_event_id TEXT,
  stored_path    TEXT,
  created_at     TEXT NOT NULL
);
"""


def up(conn, note: str) -> None:
    """Apply migration 4: add relation, scope, and artifact-registry projections."""
    cur = conn.cursor()
    cur.execute(ZM_RELATIONS_DDL)
    cur.execute(ZM_SCOPES_DDL)
    cur.execute(ZM_ARTIFACTS_DDL)


def down(conn, note: str) -> None:
    """Reverse migration 4: drop the three tables, returning to v3."""
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS zm_artifacts")
    cur.execute("DROP TABLE IF EXISTS zm_scopes")
    cur.execute("DROP TABLE IF EXISTS zm_relations")


__all__ = ["up", "down"]
