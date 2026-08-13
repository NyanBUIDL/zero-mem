"""M8.1 migration: derived graph/temporal/index-registry foundation (schema v9).

Every table created here is DERIVED, disposable, and fully rebuildable from
canonical JSONL plus approved M4/project operation records. None of them is
canonical truth. Dropping all of them and re-running the projection must
reproduce an equivalent derived state (docs/plans/plan-m8.md §5, §14).

Scope discipline (M8.1 is a FOUNDATION increment):

- Created here: the minimal structures the frozen M8.1 contracts describe.
- NOT created here: any table that exists only to serve behavior deferred to a
  later increment. In particular ``zm_calibration_factors`` is deliberately
  ABSENT — docs/plans/plan-m8.md §6 item 6 makes it conditional ("only if request-time
  decomposition cannot remain entirely in memory") and M8-OQ-6 recommends
  request-time-only calibration. Adding it now would be speculative schema.

Safety properties:

- Additive only. No v8 or earlier table, index, column, or row is altered,
  renamed, or dropped by ``up()``.
- Canonical JSONL and artifact files are never touched by either direction.
- ``down()`` (v9 -> v8) drops ONLY the v9 derived structures, which is safe
  precisely because they are rebuildable.
- ``lifecycle_status`` uses the same CLOSED lifecycle enum as v7/v8. Domain
  state never enters a lifecycle column.
- Timestamp columns are NULLable on purpose: a source that has no valid time
  stores NULL. No default, no ``CURRENT_TIMESTAMP``, no invented time.
- Uniqueness is on full logical/provenance identity, never on ``AUTOINCREMENT``
  or insertion order.
"""

from __future__ import annotations

import sqlite3

# Closed lifecycle enum (master spec §7.1), identical to migrate_7 / migrate_8.
_LIFECYCLE_ENUM = (
    "'raw','observed','candidate','confirmed','active',"
    "'superseded','conflicted','archived','deleted'"
)

# Closed M8 relation vocabulary (docs/plans/plan-m8.md §7). Mirrors
# src/m8/vocabulary.py::RelationType; a focused test asserts they stay in sync.
_RELATION_ENUM = (
    "'supports','contradicts','verifies','supersedes','derived_from',"
    "'references','related_to','belongs_to_project','belongs_to_profile',"
    "'belongs_to_knowledge_space','artifact_of','source_of','decision_for',"
    "'requirement_for'"
)

# Closed M8 entity-type vocabulary. Mirrors src/m8/vocabulary.py::EntityType.
_ENTITY_TYPE_ENUM = (
    "'person','organization','project','component','artifact','concept',"
    "'source','tool'"
)

# Closed resource-type vocabulary. Mirrors the authoritative M5 literals in
# src/access/contracts.py. Preserving it as a CHECK is what stops a derived
# graph row from erasing resource_type identity (permanent M6.6 invariant).
_RESOURCE_TYPE_ENUM = (
    "'event','trace','relation','charter','requirement','decision','state',"
    "'verification','artifact','project_artifact'"
)

# Closed relation-source vocabulary. Mirrors src/m8/vocabulary.py::RelationSource.
# There is deliberately no 'inferred' / 'llm' member.
_RELATION_SOURCE_ENUM = (
    "'m2_relation','m2_scope','m2_artifact','m4_project_link',"
    "'m4_supersession','m4_verification'"
)

# ---- DDL ----------------------------------------------------------------------

ENTITIES_DDL = f"""
CREATE TABLE IF NOT EXISTS zm_entities (
  entity_id          TEXT PRIMARY KEY,
  entity_type        TEXT NOT NULL CHECK (entity_type IN ({_ENTITY_TYPE_ENUM})),
  canonical_name     TEXT NOT NULL,
  profile_id         TEXT,
  project_id         TEXT,
  knowledge_space_id TEXT,
  lifecycle_status   TEXT NOT NULL DEFAULT 'candidate'
                        CHECK (lifecycle_status IN ({_LIFECYCLE_ENUM})),
  source_event_id    TEXT,
  trace_id           TEXT,
  relation_source    TEXT NOT NULL
                        CHECK (relation_source IN ({_RELATION_SOURCE_ENUM})),
  source_ref         TEXT NOT NULL,
  projection_version TEXT NOT NULL,
  identity_version   TEXT NOT NULL,
  provenance_hash    TEXT NOT NULL,
  content_hash       TEXT NOT NULL,
  created_at         TEXT,
  updated_at         TEXT
);
"""

ENTITY_MENTIONS_DDL = """
CREATE TABLE IF NOT EXISTS zm_entity_mentions (
  mention_id         TEXT PRIMARY KEY,
  entity_id          TEXT NOT NULL,
  source_event_id    TEXT NOT NULL,
  trace_id           TEXT,
  span_start         INTEGER,
  span_end           INTEGER,
  -- Hash only. Raw mention text is never duplicated into the derived index,
  -- so a redacted/secret-bearing span cannot be reconstructed from here.
  mention_text_hash  TEXT NOT NULL,
  profile_id         TEXT,
  project_id         TEXT,
  knowledge_space_id TEXT,
  provenance_hash    TEXT NOT NULL,
  content_hash       TEXT NOT NULL,
  created_at         TEXT,
  FOREIGN KEY (entity_id) REFERENCES zm_entities(entity_id)
);
"""

GRAPH_EDGES_DDL = f"""
CREATE TABLE IF NOT EXISTS zm_graph_edges (
  edge_id            TEXT PRIMARY KEY,
  from_resource_type TEXT NOT NULL
                        CHECK (from_resource_type IN ({_RESOURCE_TYPE_ENUM})),
  from_resource_id   TEXT NOT NULL,
  relation_type      TEXT NOT NULL CHECK (relation_type IN ({_RELATION_ENUM})),
  to_resource_type   TEXT NOT NULL
                        CHECK (to_resource_type IN ({_RESOURCE_TYPE_ENUM})),
  to_resource_id     TEXT NOT NULL,
  profile_id         TEXT,
  project_id         TEXT,
  knowledge_space_id TEXT,
  lifecycle_status   TEXT NOT NULL DEFAULT 'candidate'
                        CHECK (lifecycle_status IN ({_LIFECYCLE_ENUM})),
  verification_status TEXT,
  valid_from         TEXT,
  valid_until        TEXT,
  source_event_id    TEXT,
  trace_id           TEXT,
  relation_source    TEXT NOT NULL
                        CHECK (relation_source IN ({_RELATION_SOURCE_ENUM})),
  source_ref         TEXT NOT NULL,
  projection_version TEXT NOT NULL,
  identity_version   TEXT NOT NULL,
  provenance_hash    TEXT NOT NULL,
  content_hash       TEXT NOT NULL,
  created_at         TEXT
);
"""

TEMPORAL_INDEX_DDL = f"""
CREATE TABLE IF NOT EXISTS zm_temporal_index (
  resource_type      TEXT NOT NULL
                        CHECK (resource_type IN ({_RESOURCE_TYPE_ENUM})),
  resource_id        TEXT NOT NULL,
  -- Every timestamp column is NULLable and has NO default. A source without
  -- that dimension stores NULL; no time is ever invented.
  created_at         TEXT,
  observed_at        TEXT,
  effective_at       TEXT,
  valid_from         TEXT,
  valid_until        TEXT,
  superseded_at      TEXT,
  lifecycle_status   TEXT NOT NULL DEFAULT 'candidate'
                        CHECK (lifecycle_status IN ({_LIFECYCLE_ENUM})),
  verification_status TEXT,
  profile_id         TEXT,
  project_id         TEXT,
  knowledge_space_id TEXT,
  source_event_id    TEXT,
  trace_id           TEXT,
  provenance_hash    TEXT NOT NULL,
  PRIMARY KEY (resource_type, resource_id)
);
"""

INDEX_VERSIONS_DDL = """
CREATE TABLE IF NOT EXISTS zm_m8_index_versions (
  index_name            TEXT PRIMARY KEY,
  version               TEXT NOT NULL,
  source_cutoff         TEXT NOT NULL,
  canonical_fingerprint TEXT NOT NULL,
  built_at              TEXT NOT NULL,
  build_status          TEXT NOT NULL
                          CHECK (build_status IN ('building','published','failed'))
);
"""

# ---- Indexes ------------------------------------------------------------------

ENTITIES_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_zm_entities_scope "
    "ON zm_entities(profile_id, project_id, knowledge_space_id)",
    "CREATE INDEX IF NOT EXISTS idx_zm_entities_type_name "
    "ON zm_entities(entity_type, canonical_name)",
]

ENTITY_MENTIONS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_zm_entity_mentions_entity "
    "ON zm_entity_mentions(entity_id)",
    "CREATE INDEX IF NOT EXISTS idx_zm_entity_mentions_source "
    "ON zm_entity_mentions(source_event_id)",
]

GRAPH_EDGES_INDEXES = [
    # Logical identity: typed endpoints + relation + provenance source + scope.
    # Never rowid/insertion order. Both resource_types participate so an
    # artifact edge can never collide with an event edge of the same raw id.
    #
    # A plain UNIQUE table constraint would NOT work here: SQLite treats every
    # NULL as distinct, so two identical unscoped edges (profile/project/space
    # all NULL) would both be admitted and the derived index would duplicate on
    # rebuild.
    #
    # A COALESCE-to-sentinel fix would be forgeable: a real scope id equal to
    # the sentinel string would collide with "unscoped". Instead each scope
    # dimension contributes an explicit IS NULL flag alongside its value, so
    # NULL occupies a separate coordinate that no literal string can reach.
    # Stored columns keep a real NULL; the encoding exists only in the index.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_zm_graph_edges_logical "
    "ON zm_graph_edges("
    "from_resource_type, from_resource_id, relation_type, "
    "to_resource_type, to_resource_id, source_ref, "
    "(profile_id IS NULL), COALESCE(profile_id, ''), "
    "(project_id IS NULL), COALESCE(project_id, ''), "
    "(knowledge_space_id IS NULL), COALESCE(knowledge_space_id, ''))",
    # Outgoing lookup keyed by TYPED endpoint (never by bare resource_id).
    "CREATE INDEX IF NOT EXISTS idx_zm_graph_edges_from "
    "ON zm_graph_edges(from_resource_type, from_resource_id, relation_type)",
    # Incoming lookup, likewise typed.
    "CREATE INDEX IF NOT EXISTS idx_zm_graph_edges_to "
    "ON zm_graph_edges(to_resource_type, to_resource_id, relation_type)",
    "CREATE INDEX IF NOT EXISTS idx_zm_graph_edges_scope "
    "ON zm_graph_edges(profile_id, project_id, knowledge_space_id)",
    "CREATE INDEX IF NOT EXISTS idx_zm_graph_edges_lifecycle "
    "ON zm_graph_edges(lifecycle_status)",
]

TEMPORAL_INDEX_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_zm_temporal_scope "
    "ON zm_temporal_index(profile_id, project_id, knowledge_space_id)",
    "CREATE INDEX IF NOT EXISTS idx_zm_temporal_effective "
    "ON zm_temporal_index(effective_at)",
    "CREATE INDEX IF NOT EXISTS idx_zm_temporal_validity "
    "ON zm_temporal_index(valid_from, valid_until)",
]

_DDL = [
    ENTITIES_DDL,
    ENTITY_MENTIONS_DDL,
    GRAPH_EDGES_DDL,
    TEMPORAL_INDEX_DDL,
    INDEX_VERSIONS_DDL,
]

_INDEXES = (
    ENTITIES_INDEXES
    + ENTITY_MENTIONS_INDEXES
    + GRAPH_EDGES_INDEXES
    + TEMPORAL_INDEX_INDEXES
)

#: Tables introduced by v9. All DERIVED and rebuildable.
M8_DERIVED_TABLES = (
    "zm_entities",
    "zm_entity_mentions",
    "zm_graph_edges",
    "zm_temporal_index",
    "zm_m8_index_versions",
)

#: Indexes introduced by v9 (drop order is the reverse of creation order).
M8_DERIVED_INDEXES = (
    "idx_zm_temporal_validity",
    "idx_zm_temporal_effective",
    "idx_zm_temporal_scope",
    "idx_zm_graph_edges_lifecycle",
    "idx_zm_graph_edges_scope",
    "idx_zm_graph_edges_to",
    "idx_zm_graph_edges_from",
    "uq_zm_graph_edges_logical",
    "idx_zm_entity_mentions_source",
    "idx_zm_entity_mentions_entity",
    "idx_zm_entities_type_name",
    "idx_zm_entities_scope",
)


def up(conn: sqlite3.Connection, note: str) -> None:
    """Apply migration 9: create the five M8 derived tables + indexes.

    Purely additive: no existing table, column, index, or row is modified, and
    canonical JSONL/artifacts are untouched.
    """
    cur = conn.cursor()
    for ddl in _DDL:
        cur.execute(ddl)
    for stmt in _INDEXES:
        cur.execute(stmt)


def down(conn: sqlite3.Connection, note: str) -> None:
    """Reverse migration 9: drop the v9 derived structures, returning to v8.

    Safe because every dropped structure is derived and rebuildable. Does not
    touch M0-M7 tables, canonical JSONL, artifacts, or prior migrations.
    """
    cur = conn.cursor()
    for name in M8_DERIVED_INDEXES:
        cur.execute(f"DROP INDEX IF EXISTS {name}")
    # Child-before-parent so the entity FK never blocks the drop.
    for table in (
        "zm_m8_index_versions",
        "zm_temporal_index",
        "zm_graph_edges",
        "zm_entity_mentions",
        "zm_entities",
    ):
        cur.execute(f"DROP TABLE IF EXISTS {table}")


__all__ = ["up", "down", "M8_DERIVED_TABLES", "M8_DERIVED_INDEXES"]
