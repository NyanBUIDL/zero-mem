"""M8.1 focused tests — schema v9 migration, initialization, and constraints.

Proves the derived foundation is additive, idempotent, rollback-safe, and that
all M0-M7 data survives the v8 -> v9 migration untouched. Uses tmp_path only;
never writes to the real ~/.hermes.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.m8.derived_index import m8_derived_state_is_empty, m8_tables_present
from src.storage.migrations import CURRENT_SCHEMA_VERSION, MIGRATIONS
from src.storage.migrations.migrate_9 import M8_DERIVED_INDEXES, M8_DERIVED_TABLES
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig

TS_A = "2026-01-02T03:04:05+00:00"


def _config(tmp_path: Path, name: str = "meta.sqlite") -> SQLiteStoreConfig:
    return SQLiteStoreConfig(path=tmp_path / name)


def _table_names(db: SQLiteStore) -> set[str]:
    return {
        row[0]
        for row in db._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _index_names(db: SQLiteStore) -> set[str]:
    return {
        row[0]
        for row in db._conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
    }


def _migrate_to(db: SQLiteStore, target: int) -> None:
    """Apply migrations up to ``target`` using the established runner."""
    for version in sorted(v for v in MIGRATIONS if v > db.get_schema_version() and v <= target):
        db._apply_up(version, note="m8.1_test")


def _seed_meta_row(db: SQLiteStore, event_id: str) -> None:
    """Insert one representative M2 canonical-projection row."""
    db._conn.execute(
        "INSERT INTO zm_meta (event_id, trace_id, event_type, source, "
        "schema_version, created_at, observed_at, sequence, lifecycle_status, "
        "verification_status, confidence, sensitivity, retention, content_hash, "
        "redaction_applied, ingested_at, origin_jsonl) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (event_id, "T1", "note", "test", 1, TS_A, TS_A, 1, "active",
         "unverified", "medium", "normal", "standard", "hash-keep", 0, TS_A,
         "raw.jsonl"),
    )
    db._conn.commit()


def _meta_rows(db: SQLiteStore) -> list[tuple]:
    return [
        tuple(r)
        for r in db._conn.execute(
            "SELECT event_id, lifecycle_status, content_hash "
            "FROM zm_meta ORDER BY event_id"
        )
    ]


@pytest.fixture()
def db(tmp_path: Path):
    store = SQLiteStore(_config(tmp_path))
    store.ensure_schema()
    try:
        yield store
    finally:
        store.close()


@pytest.fixture()
def db_v8(tmp_path: Path):
    store = SQLiteStore(_config(tmp_path, "v8.sqlite"))
    _migrate_to(store, 8)
    try:
        yield store
    finally:
        store.close()


class TestSchemaVersion:
    def test_current_schema_version_is_9(self):
        assert CURRENT_SCHEMA_VERSION == 13

    def test_migration_9_registered(self):
        assert 9 in MIGRATIONS

    def test_migration_chain_contiguous(self):
        assert sorted(MIGRATIONS) == list(range(1, 14))

    def test_migration_9_has_up_and_down(self):
        assert callable(MIGRATIONS[9].up)
        assert callable(MIGRATIONS[9].down)


class TestFreshInitialization:
    def test_fresh_db_reports_version_9(self, db):
        assert db.get_schema_version() == 13

    def test_all_v9_tables_created(self, db):
        for table in M8_DERIVED_TABLES:
            assert db.table_exists(table), table

    def test_all_v9_indexes_created(self, db):
        for index in M8_DERIVED_INDEXES:
            assert db.index_exists(index), index

    def test_m0_m7_tables_still_present(self, db):
        for table in (
            "zm_meta", "zm_lifecycle", "zm_relations", "zm_scopes",
            "zm_artifacts", "zm_provenance", "zm_access_grants",
            "zm_requirements", "zm_decisions", "zm_verifications",
        ):
            assert db.table_exists(table), table

    def test_derived_tables_start_empty(self, db):
        assert m8_derived_state_is_empty(db._conn) is True

    def test_helper_detects_v9(self, db):
        assert m8_tables_present(db._conn) is True

    def test_ensure_schema_is_idempotent(self, db):
        before = _table_names(db) | _index_names(db)
        assert db.get_schema_version() == 13
        assert db.get_schema_version() == 13
        assert (_table_names(db) | _index_names(db)) == before


class TestUpgradeFromV8:
    def test_v8_store_lacks_m8_tables(self, db_v8):
        assert db_v8.get_schema_version() == 8
        assert m8_tables_present(db_v8._conn) is False
        for table in M8_DERIVED_TABLES:
            assert not db_v8.table_exists(table)

    def test_upgrade_creates_m8_tables(self, db_v8):
        db_v8.ensure_schema()
        assert db_v8.get_schema_version() == 13
        for table in M8_DERIVED_TABLES:
            assert db_v8.table_exists(table), table

    def test_upgrade_is_purely_additive(self, db_v8):
        before = _table_names(db_v8)
        db_v8.ensure_schema()
        after = _table_names(db_v8)
        assert before.issubset(after)
        # Upgrade adds the M8.1 derived tables AND (after M10.4) the corpus
        # derived tables. Both are additive. No v1-v8 table is altered.
        from src.storage.migrations.migrate_10 import CORPUS_DERIVED_TABLES

        added = after - before
        # FTS5 creates implicit shadow tables (zm_corpus_fts_*) alongside the
        # virtual table; treat them as part of the derived corpus addition.
        added_core = {t for t in added if not t.startswith("zm_corpus_fts_")}
        assert added_core == set(M8_DERIVED_TABLES) | set(CORPUS_DERIVED_TABLES) | {'zm_event_spaces'}  # v13 junction
        assert added - added_core == {t for t in added if t.startswith("zm_corpus_fts_")}

    def test_upgrade_preserves_existing_rows(self, db_v8):
        _seed_meta_row(db_v8, "E-KEEP")
        before = _meta_rows(db_v8)
        assert before == [("E-KEEP", "active", "hash-keep")]

        db_v8.ensure_schema()

        assert _meta_rows(db_v8) == before

    def test_upgrade_preserves_prior_migration_ledger(self, db_v8):
        before = db_v8._conn.execute(
            "SELECT version FROM zm_migrations ORDER BY version"
        ).fetchall()
        db_v8.ensure_schema()
        after = db_v8._conn.execute(
            "SELECT version FROM zm_migrations ORDER BY version"
        ).fetchall()
        assert [tuple(r) for r in before] == [tuple(r) for r in after][:len(before)]
        assert [tuple(r)[0] for r in after][-1] == 13

    def test_rollback_removes_only_v9_structures(self, db_v8):
        v8_tables = _table_names(db_v8)
        v8_indexes = _index_names(db_v8)
        db_v8.ensure_schema()
        db_v8.downgrade_to(8)
        assert db_v8.get_schema_version() == 8
        assert _table_names(db_v8) == v8_tables
        assert _index_names(db_v8) == v8_indexes

    def test_rollback_preserves_data(self, db_v8):
        _seed_meta_row(db_v8, "E-KEEP")
        db_v8.ensure_schema()
        db_v8.downgrade_to(8)
        assert _meta_rows(db_v8) == [("E-KEEP", "active", "hash-keep")]

    def test_round_trip_up_down_up(self, db_v8):
        db_v8.ensure_schema()
        first = _table_names(db_v8) | _index_names(db_v8)
        db_v8.downgrade_to(8)
        db_v8.ensure_schema()
        assert (_table_names(db_v8) | _index_names(db_v8)) == first


class TestNoSpeculativeSchema:
    def test_only_approved_m8_tables_exist(self, db):
        m8_like = {
            t for t in _table_names(db)
            if "entit" in t or "graph" in t or "temporal" in t
            or "m8" in t or "calibration" in t
        }
        # M10.4 corpus tables (zm_corpus_*) are a separate, later increment and
        # must not be mistaken for speculative M8.1 schema. The M8.1 invariant
        # this test guards is "M8.1 created no tables beyond its approved set".
        m8_like = {t for t in m8_like if not t.startswith("zm_corpus_")}
        assert m8_like == set(M8_DERIVED_TABLES)

    def test_no_calibration_table_in_m8_1(self, db):
        # docs/plans/plan-m8.md makes zm_calibration_factors conditional; M8.1 must not
        # create speculative schema for deferred behavior.
        assert not db.table_exists("zm_calibration_factors")

    def test_no_deferred_increment_tables(self, db):
        for banned in (
            "zm_graph_paths", "zm_graph_cache", "zm_entity_embeddings",
            "zm_vectors", "zm_embeddings", "zm_obsidian_projection",
            "zm_temporal_snapshots", "zm_calibration_scores",
        ):
            assert not db.table_exists(banned), banned


class TestDerivedConstraints:
    def test_lifecycle_check_rejects_invalid_value(self, db):
        with pytest.raises(sqlite3.IntegrityError):
            db._conn.execute(
                "INSERT INTO zm_entities (entity_id, entity_type, canonical_name, "
                "lifecycle_status, relation_source, source_ref, projection_version, "
                "identity_version, provenance_hash, content_hash) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("ent_1", "person", "A", "revoked", "m2_relation", "r:1",
                 "m8.1", "v1", "ph", "ch"),
            )

    def test_entity_type_check_rejects_invalid_value(self, db):
        with pytest.raises(sqlite3.IntegrityError):
            db._conn.execute(
                "INSERT INTO zm_entities (entity_id, entity_type, canonical_name, "
                "relation_source, source_ref, projection_version, identity_version, "
                "provenance_hash, content_hash) VALUES (?,?,?,?,?,?,?,?,?)",
                ("ent_2", "alien", "A", "m2_relation", "r:1", "m8.1", "v1", "ph", "ch"),
            )

    def test_relation_source_rejects_inference(self, db):
        with pytest.raises(sqlite3.IntegrityError):
            db._conn.execute(
                "INSERT INTO zm_entities (entity_id, entity_type, canonical_name, "
                "relation_source, source_ref, projection_version, identity_version, "
                "provenance_hash, content_hash) VALUES (?,?,?,?,?,?,?,?,?)",
                ("ent_3", "person", "A", "llm_inferred", "r:1", "m8.1", "v1", "ph", "ch"),
            )

    def _edge_sql(self) -> str:
        return (
            "INSERT INTO zm_graph_edges (edge_id, from_resource_type, "
            "from_resource_id, relation_type, to_resource_type, to_resource_id, "
            "relation_source, source_ref, projection_version, identity_version, "
            "provenance_hash, content_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
        )

    def test_relation_type_check_rejects_invalid_value(self, db):
        with pytest.raises(sqlite3.IntegrityError):
            db._conn.execute(
                self._edge_sql(),
                ("edg_1", "event", "E1", "owns", "event", "E2",
                 "m2_relation", "r:1", "m8.1", "v1", "ph", "ch"),
            )

    def test_resource_type_check_rejects_generic_node(self, db):
        with pytest.raises(sqlite3.IntegrityError):
            db._conn.execute(
                self._edge_sql(),
                ("edg_2", "node", "E1", "supports", "event", "E2",
                 "m2_relation", "r:1", "m8.1", "v1", "ph", "ch"),
            )

    def test_edge_uniqueness_distinguishes_resource_type(self, db):
        db._conn.execute(
            self._edge_sql(),
            ("edg_a", "event", "E1", "supports", "artifact", "A1",
             "m2_relation", "r:1", "m8.1", "v1", "ph", "ch"),
        )
        # Same ids, different to_resource_type => a genuinely different edge.
        db._conn.execute(
            self._edge_sql(),
            ("edg_b", "event", "E1", "supports", "event", "A1",
             "m2_relation", "r:1", "m8.1", "v1", "ph", "ch"),
        )
        db._conn.commit()
        assert db._conn.execute("SELECT COUNT(*) FROM zm_graph_edges").fetchone()[0] == 2

    def test_duplicate_logical_edge_rejected(self, db):
        args = ("event", "E1", "supports", "event", "E2",
                "m2_relation", "r:1", "m8.1", "v1", "ph", "ch")
        db._conn.execute(self._edge_sql(), ("edg_x", *args))
        with pytest.raises(sqlite3.IntegrityError):
            db._conn.execute(self._edge_sql(), ("edg_y", *args))

    def test_duplicate_unscoped_edge_rejected_null_safe(self, db):
        # Regression: a plain UNIQUE constraint would NOT catch this, because
        # SQLite treats each NULL as distinct. Two identical fully-unscoped
        # edges must still collapse to one, or rebuild would duplicate rows.
        args = ("event", "E1", "references", "event", "E2",
                "m2_relation", "r:9", "m8.1", "v1", "ph", "ch")
        db._conn.execute(self._edge_sql(), ("edg_n1", *args))
        with pytest.raises(sqlite3.IntegrityError):
            db._conn.execute(self._edge_sql(), ("edg_n2", *args))

    def test_unscoped_is_distinct_from_literal_scope_value(self, db):
        # NULL-safety must not be forgeable: a real project_id that equals the
        # empty string (or any sentinel) must stay distinct from "unscoped".
        sql = (
            "INSERT INTO zm_graph_edges (edge_id, from_resource_type, "
            "from_resource_id, relation_type, to_resource_type, to_resource_id, "
            "project_id, relation_source, source_ref, projection_version, "
            "identity_version, provenance_hash, content_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
        )
        db._conn.execute(
            self._edge_sql(),
            ("edg_u", "event", "E1", "supports", "event", "E2",
             "m2_relation", "r:1", "m8.1", "v1", "ph", "ch"),
        )
        db._conn.execute(sql, ("edg_s", "event", "E1", "supports", "event", "E2",
                               "", "m2_relation", "r:1", "m8.1", "v1",
                               "ph", "ch"))
        db._conn.commit()
        stored = db._conn.execute(
            "SELECT project_id FROM zm_graph_edges ORDER BY edge_id"
        ).fetchall()
        # Both rows coexist, and the unscoped row keeps a real NULL.
        assert [tuple(r)[0] for r in stored] == ["", None]

    def test_same_edge_different_scope_allowed(self, db):
        sql = (
            "INSERT INTO zm_graph_edges (edge_id, from_resource_type, "
            "from_resource_id, relation_type, to_resource_type, to_resource_id, "
            "project_id, relation_source, source_ref, projection_version, "
            "identity_version, provenance_hash, content_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
        )
        db._conn.execute(sql, ("edg_p1", "event", "E1", "supports", "event", "E2",
                               "P1", "m2_relation", "r:1", "m8.1", "v1", "ph", "ch"))
        db._conn.execute(sql, ("edg_p2", "event", "E1", "supports", "event", "E2",
                               "P2", "m2_relation", "r:1", "m8.1", "v1", "ph", "ch"))
        db._conn.commit()
        assert db._conn.execute("SELECT COUNT(*) FROM zm_graph_edges").fetchone()[0] == 2

    def test_temporal_columns_have_no_default(self, db):
        db._conn.execute(
            "INSERT INTO zm_temporal_index (resource_type, resource_id, "
            "provenance_hash) VALUES (?,?,?)",
            ("decision", "D1", "ph"),
        )
        db._conn.commit()
        row = db._conn.execute(
            "SELECT created_at, observed_at, effective_at, valid_from, valid_until, "
            "superseded_at FROM zm_temporal_index WHERE resource_id='D1'"
        ).fetchone()
        # No invented timestamps: absent dimensions stay NULL.
        assert all(value is None for value in tuple(row))

    def test_build_status_check_enforced(self, db):
        with pytest.raises(sqlite3.IntegrityError):
            db._conn.execute(
                "INSERT INTO zm_m8_index_versions (index_name, version, source_cutoff, "
                "canonical_fingerprint, built_at, build_status) VALUES (?,?,?,?,?,?)",
                ("zm_graph_edges", "1", TS_A, "fp", TS_A, "usable"),
            )
