"""M10.4 migration: derived corpus storage substrate (schema version 10).

Every table created here is DERIVED, disposable, and fully rebuildable from the
canonical corpus registry (``corpus_sources.jsonl``) plus the content-addressed
blob store via the frozen M10.2 extractor / M10.3 normalizer. None of them is
canonical truth. Dropping all of them and re-running the corpus projection must
reproduce an equivalent derived state (docs/plans/plan-m10.md §5.2, §11).

Scope discipline (additive, mirrors migrate_9 foundation discipline):

- Created here: the minimal derived corpus structures the frozen M10.1-M10.3
  contracts describe.
- NOT populated here: ``zm_corpus_relations`` / ``zm_corpus_entities`` are created
  as schema-only (reusing the closed M8 vocabularies + the ``corpus_source`` /
  ``corpus_unit`` resource types) so M10.6 can write corpus graph edges later.
  M10.4 owns the derived *storage* substrate; graph *population* is M10.6.
- Canonical JSONL, blobs, and the v1-v9 tables are never touched by either
  direction.
- ``down()`` (v10 -> v9) drops ONLY the v10 derived structures, which is safe
  precisely because they are rebuildable.
- ``lifecycle_status`` / ``sensitivity`` use the same CLOSED enums as the
  corpus source contract (M10.1). Domain state never enters a lifecycle column.
- Timestamp columns are NULLable on purpose; a source without valid time stores
  NULL. No default, no ``CURRENT_TIMESTAMP``, no invented time.
- Uniqueness is on full logical/provenance identity, never on ``AUTOINCREMENT``
  or insertion order.

Security boundary:

- ``zm_corpus_units.normalized_text`` and ``zm_corpus_fts.content`` hold only
  sanitized/secret-free derived text. The projection layer (``src/corpus/
  derived_store.py``) applies the fail-closed M10.2 redactor before any unit or
  FTS row is written, so a secret-shaped unit is rejected (never stored/indexed).
- ``resource_type`` is a hard CHECK (``corpus_source`` / ``corpus_unit``) so the
  two authorization resource types stay distinct and the permanent M6.6
  isolation invariant is preserved at the storage layer.
"""

from __future__ import annotations

import sqlite3

# Closed lifecycle enum (M10.1 src/corpus/identity.py::SourceLifecycle).
_LIFECYCLE_ENUM = (
    "'raw','observed','candidate','confirmed','active',"
    "'superseded','conflicted','archived','deleted'"
)

# Closed sensitivity ceiling (M10.1 src/corpus/contracts.py::SourceSensitivity).
_SENSITIVITY_ENUM = "'public','internal','private','secret'"

# Coarse structural unit kinds (M10.2 src/corpus/extract.py::UnitKind).
_UNIT_KIND_ENUM = "'text','heading','table','code','figure','metadata','other'"

# Closed resource-type vocabulary for corpus tables. Mirrors
# src/m8/vocabulary.py::RESOURCE_TYPES (which already includes corpus_source /
# corpus_unit) so a derived corpus row can never erase resource_type identity
# (permanent M6.6 invariant).
_RESOURCE_TYPE_ENUM = (
    "'event','trace','relation','charter','requirement','decision','state',"
    "'verification','artifact','project_artifact','corpus_source','corpus_unit'"
)

# Closed M8 relation vocabulary (docs/plans/plan-m8.md §7). Mirrors
# src/m8/vocabulary.py::RelationType.
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

# Closed relation-source vocabulary. Mirrors src/m8/vocabulary.py::RelationSource
# plus the M10 corpus-extraction member (docs/plans/plan-m10.md §4: "RelationSource gains a
# corpus_extraction member"). There is deliberately no 'inferred' / 'llm' member.
_RELATION_SOURCE_ENUM = (
    "'m2_relation','m2_scope','m2_artifact','m4_project_link',"
    "'m4_supersession','m4_verification','corpus_extraction'"
)

#: Detected at import time; reflects whether this SQLite build can create FTS5.
FTS5_AVAILABLE: bool = True

# ---- DDL ----------------------------------------------------------------------

CORPUS_SOURCES_DDL = f"""
CREATE TABLE IF NOT EXISTS zm_corpus_sources (
  source_id          TEXT PRIMARY KEY,
  content_hash       TEXT NOT NULL,
  external_ref       TEXT NOT NULL,
  kind               TEXT NOT NULL,
  resource_type      TEXT NOT NULL CHECK (resource_type = 'corpus_source'),
  profile_id         TEXT,
  project_id         TEXT,
  knowledge_space_id TEXT,
  sensitivity        TEXT NOT NULL CHECK (sensitivity IN ({_SENSITIVITY_ENUM})),
  lifecycle_status   TEXT NOT NULL CHECK (lifecycle_status IN ({_LIFECYCLE_ENUM})),
  blob_ref           TEXT,
  created_at         TEXT,
  provenance         TEXT,
  custom_meta        TEXT
);
"""

CORPUS_UNITS_DDL = f"""
CREATE TABLE IF NOT EXISTS zm_corpus_units (
  unit_id           TEXT PRIMARY KEY,
  source_ref        TEXT NOT NULL,
  source_location_id TEXT NOT NULL,
  content_hash      TEXT NOT NULL,
  normalized_text   TEXT NOT NULL,
  kind              TEXT NOT NULL CHECK (kind IN ({_UNIT_KIND_ENUM})),
  resource_type     TEXT NOT NULL CHECK (resource_type = 'corpus_unit'),
  unit_order        INTEGER NOT NULL,
  page              INTEGER,
  parent_ref        TEXT,
  profile_id        TEXT,
  project_id        TEXT,
  knowledge_space_id TEXT,
  duplicate_of      TEXT,
  lifecycle_status  TEXT NOT NULL CHECK (lifecycle_status IN ({_LIFECYCLE_ENUM})),
  sensitivity       TEXT NOT NULL CHECK (sensitivity IN ({_SENSITIVITY_ENUM})),
  created_at        TEXT,
  provenance_hash   TEXT,
  FOREIGN KEY (source_ref) REFERENCES zm_corpus_sources(source_id)
);
"""

CORPUS_FTS_DDL = "CREATE VIRTUAL TABLE IF NOT EXISTS zm_corpus_fts USING fts5(unit_id UNINDEXED, content)"

# Schema-only corpus graph structures (populated by M10.6). Reuse the closed M8
# vocabularies so corpus edges carry the same provenance/resource-type discipline.
CORPUS_RELATIONS_DDL = f"""
CREATE TABLE IF NOT EXISTS zm_corpus_relations (
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

CORPUS_ENTITIES_DDL = f"""
CREATE TABLE IF NOT EXISTS zm_corpus_entities (
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

# ---- Indexes ------------------------------------------------------------------

CORPUS_SOURCES_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_zm_corpus_sources_scope "
    "ON zm_corpus_sources(profile_id, project_id, knowledge_space_id)",
    "CREATE INDEX IF NOT EXISTS idx_zm_corpus_sources_content_hash "
    "ON zm_corpus_sources(content_hash)",
    "CREATE INDEX IF NOT EXISTS idx_zm_corpus_sources_kind "
    "ON zm_corpus_sources(kind)",
    "CREATE INDEX IF NOT EXISTS idx_zm_corpus_sources_lifecycle "
    "ON zm_corpus_sources(lifecycle_status)",
]

CORPUS_UNITS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_zm_corpus_units_source "
    "ON zm_corpus_units(source_ref)",
    "CREATE INDEX IF NOT EXISTS idx_zm_corpus_units_content_hash "
    "ON zm_corpus_units(content_hash)",
    "CREATE INDEX IF NOT EXISTS idx_zm_corpus_units_kind "
    "ON zm_corpus_units(kind)",
    "CREATE INDEX IF NOT EXISTS idx_zm_corpus_units_lifecycle "
    "ON zm_corpus_units(lifecycle_status)",
    "CREATE INDEX IF NOT EXISTS idx_zm_corpus_units_scope "
    "ON zm_corpus_units(profile_id, project_id, knowledge_space_id)",
    "CREATE INDEX IF NOT EXISTS idx_zm_corpus_units_duplicate_of "
    "ON zm_corpus_units(duplicate_of)",
]

CORPUS_RELATIONS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_zm_corpus_relations_from "
    "ON zm_corpus_relations(from_resource_type, from_resource_id, relation_type)",
    "CREATE INDEX IF NOT EXISTS idx_zm_corpus_relations_to "
    "ON zm_corpus_relations(to_resource_type, to_resource_id, relation_type)",
    "CREATE INDEX IF NOT EXISTS idx_zm_corpus_relations_scope "
    "ON zm_corpus_relations(profile_id, project_id, knowledge_space_id)",
]

CORPUS_ENTITIES_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_zm_corpus_entities_scope "
    "ON zm_corpus_entities(profile_id, project_id, knowledge_space_id)",
    "CREATE INDEX IF NOT EXISTS idx_zm_corpus_entities_type_name "
    "ON zm_corpus_entities(entity_type, canonical_name)",
]

_DDL = [
    CORPUS_SOURCES_DDL,
    CORPUS_UNITS_DDL,
    CORPUS_FTS_DDL,
    CORPUS_RELATIONS_DDL,
    CORPUS_ENTITIES_DDL,
]

_INDEXES = (
    CORPUS_SOURCES_INDEXES
    + CORPUS_UNITS_INDEXES
    + CORPUS_RELATIONS_INDEXES
    + CORPUS_ENTITIES_INDEXES
)

#: Tables introduced by v10. All DERIVED and rebuildable.
CORPUS_DERIVED_TABLES = (
    "zm_corpus_sources",
    "zm_corpus_units",
    "zm_corpus_fts",
    "zm_corpus_relations",
    "zm_corpus_entities",
)

#: Indexes introduced by v10 (drop order is the reverse of creation order).
CORPUS_DERIVED_INDEXES = (
    "idx_zm_corpus_entities_type_name",
    "idx_zm_corpus_entities_scope",
    "idx_zm_corpus_relations_scope",
    "idx_zm_corpus_relations_to",
    "idx_zm_corpus_relations_from",
    "idx_zm_corpus_units_duplicate_of",
    "idx_zm_corpus_units_scope",
    "idx_zm_corpus_units_lifecycle",
    "idx_zm_corpus_units_kind",
    "idx_zm_corpus_units_content_hash",
    "idx_zm_corpus_units_source",
    "idx_zm_corpus_sources_lifecycle",
    "idx_zm_corpus_sources_kind",
    "idx_zm_corpus_sources_content_hash",
    "idx_zm_corpus_sources_scope",
)


def _detect_fts5(conn) -> bool:
    cur = conn.cursor()
    cur.execute("PRAGMA compile_options")
    opts = {row[0] for row in cur.fetchall()}
    if any("FTS5" in o.upper() for o in opts):
        return True
    try:
        conn.execute("CREATE VIRTUAL TABLE _fts5_probe USING fts5(x)")
        conn.execute("DROP TABLE _fts5_probe")
        return True
    except sqlite3.OperationalError:
        return False


def up(conn: sqlite3.Connection, note: str) -> None:
    """Apply migration 10: create the five derived corpus tables + indexes.

    Purely additive: no existing v1-v9 table, column, index, or row is modified,
    and canonical JSONL/blobs are untouched.
    """
    global FTS5_AVAILABLE
    cur = conn.cursor()
    for ddl in (
        CORPUS_SOURCES_DDL,
        CORPUS_UNITS_DDL,
    ):
        cur.execute(ddl)
    FTS5_AVAILABLE = _detect_fts5(conn)
    if FTS5_AVAILABLE:
        try:
            cur.execute(CORPUS_FTS_DDL)
        except sqlite3.OperationalError:
            FTS5_AVAILABLE = False
    for ddl in (CORPUS_RELATIONS_DDL, CORPUS_ENTITIES_DDL):
        cur.execute(ddl)
    for stmt in (
        CORPUS_SOURCES_INDEXES
        + CORPUS_UNITS_INDEXES
        + CORPUS_RELATIONS_INDEXES
        + CORPUS_ENTITIES_INDEXES
    ):
        cur.execute(stmt)


def down(conn: sqlite3.Connection, note: str) -> None:
    """Reverse migration 10: drop the v10 derived structures, returning to v9.

    Safe because every dropped structure is derived and rebuildable. Does not
    touch M0-M8 tables, canonical JSONL, blobs, or prior migrations.
    """
    cur = conn.cursor()
    for name in CORPUS_DERIVED_INDEXES:
        cur.execute(f"DROP INDEX IF EXISTS {name}")
    # Child-before-parent so the unit FK never blocks the drop.
    for table in (
        "zm_corpus_entities",
        "zm_corpus_relations",
        "zm_corpus_fts",
        "zm_corpus_units",
        "zm_corpus_sources",
    ):
        cur.execute(f"DROP TABLE IF EXISTS {table}")


__all__ = [
    "up",
    "down",
    "FTS5_AVAILABLE",
    "CORPUS_DERIVED_TABLES",
    "CORPUS_DERIVED_INDEXES",
]
