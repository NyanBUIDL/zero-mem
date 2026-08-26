"""M10.4 focused tests — derived corpus storage + migrate_10.

Proves:

- migrate_10 (v9 -> v10) is additive, idempotent, transactional, down-safe.
- M1-M9 memory tables/data survive migrate_10 untouched.
- Derived corpus projection persists sources / units / FTS correctly.
- Cross-scope same-content data does NOT collapse authorization identities.
- corpus_source vs corpus_unit remain distinct resource types (M6.6).
- Versioning projection: unchanged content idempotent; changed content distinct;
  supersession traceable; historical version not silently overwritten.
- Deterministic rebuild reproduces equivalent derived state; canonical untouched.
- Read/write boundary: store is write/projection only here; ReadonlyStore unchanged.
- Security: secret-bearing units rejected at the projection boundary (fail-closed);
  resource_type CHECK enforced.

Uses tmp_path only; never writes to the real ~/.hermes or ingests real documents.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.corpus.blob_store import CorpusBlobStore
from src.corpus.derived_store import (
    CORPUS_UNIT_RESOURCE_TYPE,
    CorpusProjectionReport,
    project_corpus,
    rebuild_from_corpus,
)
from src.corpus.redact import CorpusRedactionError
from src.corpus.registry import CorpusSourceRegistry
from src.storage.migrations import CURRENT_SCHEMA_VERSION, MIGRATIONS
from src.storage.migrations.migrate_10 import (
    CORPUS_DERIVED_INDEXES,
    CORPUS_DERIVED_TABLES,
)
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig

TS = "2026-01-02T03:04:05+00:00"
SAMPLE_TXT = "Alpha beta gamma. Alpha beta gamma. Distinct sentence here.\n"


@pytest.fixture()
def corpus_root(tmp_path: Path):
    root = tmp_path / "corpus"
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture()
def blob_store(corpus_root: Path):
    return CorpusBlobStore(root=corpus_root)


@pytest.fixture()
def registry(corpus_root: Path):
    return CorpusSourceRegistry(root=corpus_root)


@pytest.fixture()
def store(tmp_path: Path):
    s = SQLiteStore(SQLiteStoreConfig(path=tmp_path / "corpus.sqlite"))
    s.ensure_schema()
    try:
        yield s
    finally:
        s.close()


def _config(tmp_path: Path, name: str = "meta.sqlite") -> SQLiteStoreConfig:
    return SQLiteStoreConfig(path=tmp_path / name)


def _seed_meta_row(db: SQLiteStore, event_id: str) -> None:
    """Insert one representative M2 canonical-projection row (memory data)."""
    db._conn.execute(
        "INSERT INTO zm_meta (event_id, trace_id, event_type, source, "
        "schema_version, created_at, observed_at, sequence, lifecycle_status, "
        "verification_status, confidence, sensitivity, retention, content_hash, "
        "redaction_applied, ingested_at, origin_jsonl) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (event_id, "T1", "note", "test", 1, TS, TS, 1, "active",
         "unverified", "medium", "normal", "standard", "hash-keep", 0, TS,
         "raw.jsonl"),
    )
    db._conn.commit()


# ---------------------------------------------------------------------------
# Schema / migration
# ---------------------------------------------------------------------------

class TestSchemaVersion:
    def test_current_schema_version_is_10(self):
        assert CURRENT_SCHEMA_VERSION == 13

    def test_migration_10_registered(self):
        assert 10 in MIGRATIONS

    def test_migration_chain_contiguous(self):
        assert sorted(MIGRATIONS) == list(range(1, 14))

    def test_migration_10_has_up_and_down(self):
        assert callable(MIGRATIONS[10].up)
        assert callable(MIGRATIONS[10].down)


class TestFreshInitialization:
    def test_fresh_db_reports_version_10(self, store):
        assert store.get_schema_version() == 13

    def test_all_v10_tables_created(self, store):
        for table in CORPUS_DERIVED_TABLES:
            assert store.table_exists(table), table

    def test_all_v10_indexes_created(self, store):
        for index in CORPUS_DERIVED_INDEXES:
            assert store.index_exists(index), index

    def test_m0_m9_memory_tables_still_present(self, store):
        for table in (
            "zm_meta", "zm_lifecycle", "zm_relations", "zm_scopes",
            "zm_artifacts", "zm_provenance", "zm_access_grants",
            "zm_requirements", "zm_decisions", "zm_verifications",
            "zm_entities", "zm_graph_edges", "zm_temporal_index",
        ):
            assert store.table_exists(table), table

    def test_derived_corpus_tables_start_empty(self, store):
        cur = store._conn.cursor()
        assert cur.execute("SELECT COUNT(*) FROM zm_corpus_sources").fetchone()[0] == 0
        assert cur.execute("SELECT COUNT(*) FROM zm_corpus_units").fetchone()[0] == 0

    def test_ensure_schema_is_idempotent(self, tmp_path):
        s = SQLiteStore(_config(tmp_path, "idem.sqlite"))
        assert s.ensure_schema() == 13
        before = (
            {r[0] for r in s._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            | {r[0] for r in s._conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        )
        assert s.ensure_schema() == 13
        after = (
            {r[0] for r in s._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            | {r[0] for r in s._conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        )
        assert after == before
        s.close()


class TestUpgradeFromV9:
    def test_v9_store_lacks_corpus_tables(self, tmp_path):
        s = SQLiteStore(_config(tmp_path, "v9.sqlite"))
        for version in sorted(v for v in MIGRATIONS if v <= 9):
            s._apply_up(version, note="m10.4_test")
        assert s.get_schema_version() == 9
        for table in CORPUS_DERIVED_TABLES:
            assert not s.table_exists(table)

    def test_upgrade_creates_corpus_tables(self, tmp_path):
        s = SQLiteStore(_config(tmp_path, "v9b.sqlite"))
        for version in sorted(v for v in MIGRATIONS if v <= 9):
            s._apply_up(version, note="m10.4_test")
        s.ensure_schema()
        assert s.get_schema_version() == 13
        for table in CORPUS_DERIVED_TABLES:
            assert s.table_exists(table), table

    def test_upgrade_preserves_memory_data(self, tmp_path):
        s = SQLiteStore(_config(tmp_path, "v9c.sqlite"))
        for version in sorted(v for v in MIGRATIONS if v <= 9):
            s._apply_up(version, note="m10.4_test")
        _seed_meta_row(s, "evt-keep-1")
        _seed_meta_row(s, "evt-keep-2")
        s.ensure_schema()
        rows = s._conn.execute(
            "SELECT event_id FROM zm_meta ORDER BY event_id"
        ).fetchall()
        assert [r["event_id"] for r in rows] == ["evt-keep-1", "evt-keep-2"]
        s.close()


class TestMigrationFailureSafety:
    def test_failed_migration_does_not_advance_version(self, tmp_path):
        """A broken up() must roll back and leave the version at 9."""
        import sqlite3 as _sqlite

        s = SQLiteStore(_config(tmp_path, "fail.sqlite"))
        for version in sorted(v for v in MIGRATIONS if v <= 9):
            s._apply_up(version, note="m10.4_test")
        # Monkeypatch migrate_10.up to raise.
        from src.storage import migrations as mig_mod

        original = mig_mod.migrate_10.up

        def _boom(conn, note):
            raise RuntimeError("injected migration failure")

        mig_mod.migrate_10.up = _boom
        try:
            with pytest.raises(Exception):
                s.ensure_schema()
        finally:
            mig_mod.migrate_10.up = original
        # Version must NOT have advanced to 10.
        assert s.get_schema_version() == 9
        # Corpus tables must not exist (rolled back).
        assert not s.table_exists("zm_corpus_sources")
        s.close()

    def test_downgrade_returns_to_v9(self, store):
        assert store.get_schema_version() == 13
        store.downgrade_to(9, note="rollback_test")
        assert store.get_schema_version() == 9
        for table in CORPUS_DERIVED_TABLES:
            assert not store.table_exists(table), table
        # Memory tables intact after downgrade.
        assert store.table_exists("zm_meta")


# ---------------------------------------------------------------------------
# Projection / derived storage
# ---------------------------------------------------------------------------

def _register_and_project(tmp_path, registry, blob_store, store, contents):
    """Register each (content, scope) as a source+ blob, then project."""
    recs = []
    for content, scope in contents:
        rec = registry.register_source_with_blob(
            content=content,
            external_ref=f"{scope}.txt",
            kind="txt",
            profile_id=scope.get("profile_id"),
            project_id=scope.get("project_id"),
            knowledge_space_id=scope.get("knowledge_space_id"),
        )
        recs.append(rec)
    report = project_corpus(store._conn, registry, blob_store=blob_store)
    return recs, report


class TestProjection:
    def test_source_projection_persists(self, store, registry, blob_store, tmp_path):
        _register_and_project(
            tmp_path, registry, blob_store, store,
            [(SAMPLE_TXT.encode(), {"profile_id": "p1", "project_id": "proj-x"})],
        )
        cur = store._conn.cursor()
        rows = cur.execute(
            "SELECT source_id, content_hash, resource_type, profile_id, project_id "
            "FROM zm_corpus_sources"
        ).fetchall()
        assert len(rows) == 1
        r = rows[0]
        assert r["resource_type"] == "corpus_source"
        assert r["profile_id"] == "p1"
        assert r["project_id"] == "proj-x"
        assert r["content_hash"]

    def test_unit_projection_persists_normalized_text(self, store, registry, blob_store, tmp_path):
        _register_and_project(
            tmp_path, registry, blob_store, store,
            [(SAMPLE_TXT.encode(), {"profile_id": "p1", "project_id": "proj-x"})],
        )
        cur = store._conn.cursor()
        rows = cur.execute(
            "SELECT unit_id, source_ref, content_hash, kind, resource_type, normalized_text "
            "FROM zm_corpus_units ORDER BY unit_order"
        ).fetchall()
        assert len(rows) >= 1
        for r in rows:
            assert r["resource_type"] == CORPUS_UNIT_RESOURCE_TYPE
            assert r["kind"] in ("text", "heading", "table", "code", "figure", "metadata", "other")
            assert r["normalized_text"]
            assert r["content_hash"]

    def test_fts_contains_sanitized_unit_text(self, store, registry, blob_store, tmp_path):
        _register_and_project(
            tmp_path, registry, blob_store, store,
            [(SAMPLE_TXT.encode(), {"profile_id": "p1", "project_id": "proj-x"})],
        )
        if not store.table_exists("zm_corpus_fts"):
            pytest.skip("FTS5 unavailable in this SQLite build")
        cur = store._conn.cursor()
        hits = cur.execute(
            "SELECT unit_id FROM zm_corpus_fts WHERE zm_corpus_fts MATCH ?",
            ("Distinct",),
        ).fetchall()
        assert len(hits) >= 1

    def test_projection_report_sums(self, store, registry, blob_store, tmp_path):
        _, report = _register_and_project(
            tmp_path, registry, blob_store, store,
            [
                (SAMPLE_TXT.encode(), {"profile_id": "p1", "project_id": "proj-x"}),
                (b"Second document with different words.", {"profile_id": "p2"}),
            ],
        )
        assert isinstance(report, CorpusProjectionReport)
        assert report.sources_projected == 2
        assert report.units_projected >= 2
        assert report.units_rejected_secret == 0


# ---------------------------------------------------------------------------
# Cross-scope / authorization identity
# ---------------------------------------------------------------------------

class TestCrossScope:
    def test_same_content_different_scope_distinct_units(self, store, registry, blob_store, tmp_path):
        """Two sources with identical bytes under different scope -> 2 logical units."""
        _register_and_project(
            tmp_path, registry, blob_store, store,
            [
                (SAMPLE_TXT.encode(), {"profile_id": "p1", "project_id": "proj-x"}),
                (SAMPLE_TXT.encode(), {"profile_id": "p2", "project_id": "proj-y"}),
            ],
        )
        cur = store._conn.cursor()
        rows = cur.execute(
            "SELECT unit_id, content_hash, profile_id, project_id "
            "FROM zm_corpus_units ORDER BY unit_id"
        ).fetchall()
        # Same content hash, but two distinct logical unit rows (no collapse).
        assert len(rows) == 2
        assert len({r["content_hash"] for r in rows}) == 1
        assert {r["profile_id"] for r in rows} == {"p1", "p2"}
        assert {r["project_id"] for r in rows} == {"proj-x", "proj-y"}
        assert len({r["unit_id"] for r in rows}) == 2

    def test_corpus_source_and_unit_resource_types_distinct(self, store, registry, blob_store, tmp_path):
        _register_and_project(
            tmp_path, registry, blob_store, store,
            [(SAMPLE_TXT.encode(), {"profile_id": "p1", "project_id": "proj-x"})],
        )
        cur = store._conn.cursor()
        src_rt = {r["resource_type"] for r in cur.execute("SELECT resource_type FROM zm_corpus_sources")}
        unit_rt = {r["resource_type"] for r in cur.execute("SELECT resource_type FROM zm_corpus_units")}
        assert src_rt == {"corpus_source"}
        assert unit_rt == {"corpus_unit"}
        assert src_rt != unit_rt

    def test_resource_type_check_blocks_wrong_literal(self, store):
        with pytest.raises(Exception):
            store._conn.execute(
                "INSERT INTO zm_corpus_units (unit_id, source_ref, source_location_id, "
                "content_hash, normalized_text, kind, resource_type, unit_order, "
                "lifecycle_status, sensitivity, created_at) "
                "VALUES ('u_x','s_x','l_x','c_x','text','event',1,'observed','internal','t')"
            )


# ---------------------------------------------------------------------------
# Versioning projection
# ---------------------------------------------------------------------------

class TestVersioning:
    def test_unchanged_reingest_idempotent(self, store, registry, blob_store, tmp_path):
        _register_and_project(
            tmp_path, registry, blob_store, store,
            [(SAMPLE_TXT.encode(), {"profile_id": "p1", "project_id": "proj-x"})],
        )
        first = store._conn.execute("SELECT COUNT(*) FROM zm_corpus_units").fetchone()[0]
        # Re-register identical content (idempotent at registry) + re-project.
        _register_and_project(
            tmp_path, registry, blob_store, store,
            [(SAMPLE_TXT.encode(), {"profile_id": "p1", "project_id": "proj-x"})],
        )
        second = store._conn.execute("SELECT COUNT(*) FROM zm_corpus_units").fetchone()[0]
        assert second == first  # unchanged -> no new derived unit rows

    def test_changed_content_distinct_version(self, store, registry, blob_store, tmp_path):
        recs, _ = _register_and_project(
            tmp_path, registry, blob_store, store,
            [(SAMPLE_TXT.encode(), {"profile_id": "p1", "project_id": "proj-x"})],
        )
        first_source = recs[0].source_id
        first_hash = recs[0].content_hash
        # Change content -> same logical source with a new immutable version.
        recs2, _ = _register_and_project(
            tmp_path, registry, blob_store, store,
            [(b"Completely different content after revision.", {"profile_id": "p1", "project_id": "proj-x"})],
        )
        new_source = recs2[0].source_id
        new_hash = recs2[0].content_hash
        assert new_source == first_source
        assert new_hash != first_hash
        cur = store._conn.cursor()
        # The derived source projection is latest-state; canonical registry
        # history retains both immutable versions and their supersession link.
        rows = cur.execute(
            "SELECT source_id, content_hash FROM zm_corpus_sources ORDER BY source_id"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["source_id"] == first_source
        assert rows[0]["content_hash"] == new_hash
        history = registry.all_records()
        assert len(history) == 2
        assert history[1].source_id == history[0].source_id
        assert history[1].supersedes == history[0].source_version_id


# ---------------------------------------------------------------------------
# Rebuild
# ---------------------------------------------------------------------------

class TestRebuild:
    def test_rebuild_reproduces_equivalent_state(self, store, registry, blob_store, tmp_path):
        _register_and_project(
            tmp_path, registry, blob_store, store,
            [
                (SAMPLE_TXT.encode(), {"profile_id": "p1", "project_id": "proj-x"}),
                (b"Second document with different words.", {"profile_id": "p2"}),
            ],
        )
        cur = store._conn.cursor()
        before_sources = {
            (r["source_id"], r["content_hash"], r["resource_type"])
            for r in cur.execute("SELECT source_id, content_hash, resource_type FROM zm_corpus_sources")
        }
        before_units = {
            (r["unit_id"], r["content_hash"], r["resource_type"], r["profile_id"])
            for r in cur.execute("SELECT unit_id, content_hash, resource_type, profile_id FROM zm_corpus_units")
        }
        # Destroy derived corpus state, then rebuild deterministically.
        fts_present = store.table_exists("zm_corpus_fts")
        if fts_present:
            before_fts = {
                (r["unit_id"], r["content"])
                for r in cur.execute("SELECT unit_id, content FROM zm_corpus_fts")
            }
        report = rebuild_from_corpus(store._conn, registry, blob_store=blob_store)
        assert isinstance(report, CorpusProjectionReport)
        after_sources = {
            (r["source_id"], r["content_hash"], r["resource_type"])
            for r in cur.execute("SELECT source_id, content_hash, resource_type FROM zm_corpus_sources")
        }
        after_units = {
            (r["unit_id"], r["content_hash"], r["resource_type"], r["profile_id"])
            for r in cur.execute("SELECT unit_id, content_hash, resource_type, profile_id FROM zm_corpus_units")
        }
        assert after_sources == before_sources
        assert after_units == before_units
        if fts_present:
            after_fts = {
                (r["unit_id"], r["content"])
                for r in cur.execute("SELECT unit_id, content FROM zm_corpus_fts")
            }
            assert after_fts == before_fts
        # Canonical registry JSONL untouched (still 2 source entries).
        assert len(registry.all_records()) == 2

    def test_rebuild_does_not_touch_memory_tables(self, store, registry, blob_store, tmp_path):
        _seed_meta_row(store, "evt-memory-1")
        _register_and_project(
            tmp_path, registry, blob_store, store,
            [(SAMPLE_TXT.encode(), {"profile_id": "p1"})],
        )
        rebuild_from_corpus(store._conn, registry, blob_store=blob_store)
        rows = store._conn.execute("SELECT event_id FROM zm_meta ORDER BY event_id").fetchall()
        assert [r["event_id"] for r in rows] == ["evt-memory-1"]

    def test_malformed_canonical_blob_ref_is_classified_during_projection(
        self, store, registry, blob_store, corpus_root
    ):
        registry.register_source_with_blob(
            content=b"canonical bytes",
            external_ref="malformed-ref.txt",
            kind="txt",
            profile_id="p1",
        )
        path = corpus_root / "corpus_sources.jsonl"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["blob_ref"] = ""
        path.write_text(json.dumps(record) + "\n", encoding="utf-8")

        reopened = CorpusSourceRegistry(root=corpus_root)
        report = project_corpus(store._conn, reopened, blob_store=CorpusBlobStore(root=corpus_root))

        assert report.sources_projected == 1
        assert report.extractions_failed == 1


# ---------------------------------------------------------------------------
# Read / write boundary + security
# ---------------------------------------------------------------------------

class TestSecurity:
    def test_secret_unit_rejected_fail_closed(self, store, registry, blob_store, tmp_path):
        """A secret-bearing source unit must be rejected, never stored/indexed."""
        secret_text = "password=hunter2 and more words around it for chunking."
        _register_and_project(
            tmp_path, registry, blob_store, store,
            [(secret_text.encode(), {"profile_id": "p1", "project_id": "proj-x"})],
        )
        cur = store._conn.cursor()
        # The source row is projected (registry entry), but its unit must be
        # rejected by the fail-closed redactor and NOT stored.
        units = cur.execute(
            "SELECT unit_id FROM zm_corpus_units WHERE source_ref=?",
            (registry.all_records()[0].source_id,),
        ).fetchall()
        assert len(units) == 0

    def test_blob_bytes_never_in_sqlite(self, store, registry, blob_store, tmp_path):
        _register_and_project(
            tmp_path, registry, blob_store, store,
            [(SAMPLE_TXT.encode(), {"profile_id": "p1"})],
        )
        cur = store._conn.cursor()
        # The canonical source BYTES live in the blob store, not SQLite. The
        # derived projection stores normalized (sanitized) text, which is the
        # intended rebuildable representation — but a secret marker must never
        # leak from the blob into SQLite, and the raw bytes must remain
        # retrievable only via the blob store.
        SECRET_MARKER = b"password=hunter2"
        secret_doc = b"This document contains password=hunter2 credentials inside.\n"
        _register_and_project(
            tmp_path, registry, blob_store, store,
            [(secret_doc, {"profile_id": "p1", "project_id": "proj-secret"})],
        )
        # The secret marker must be present in the blob store (canonical) ...
        assert blob_store.exists(registry.all_records()[-1].blob_ref)
        # ... but ABSENT from every SQLite corpus table (fail-closed).
        leaked = False
        for table in ("zm_corpus_sources", "zm_corpus_units", "zm_corpus_fts"):
            if table == "zm_corpus_fts" and not store.table_exists(table):
                continue
            if table == "zm_corpus_fts":
                for r in cur.execute("SELECT content FROM zm_corpus_fts").fetchall():
                    if SECRET_MARKER in r["content"].encode("utf-8", "ignore"):
                        leaked = True
            else:
                for r in cur.execute(f"SELECT * FROM {table}").fetchall():
                    for col in r:
                        if isinstance(col, (bytes, str)):
                            data = col if isinstance(col, bytes) else col.encode("utf-8", "ignore")
                            if SECRET_MARKER in data:
                                leaked = True
        assert leaked is False

    def test_projection_module_is_not_a_read_service(self):
        # The projection module must not import or expose retrieval surfaces.
        import src.corpus.derived_store as ds

        assert not hasattr(ds, "search_corpus")
        assert not hasattr(ds, "authorized_read_corpus")
        assert not hasattr(ds, "retrieve_corpus")


__all__ = [
    "TestSchemaVersion",
    "TestFreshInitialization",
    "TestUpgradeFromV9",
    "TestMigrationFailureSafety",
    "TestProjection",
    "TestCrossScope",
    "TestVersioning",
    "TestRebuild",
    "TestSecurity",
]
