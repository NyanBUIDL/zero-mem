"""M8.1 focused tests — derived-index rebuild foundation.

Proves: derived M8 structures can be cleared and rebuilt to an equivalent
state, no partial index version is ever published, and canonical JSONL is never
touched by any derived operation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.m8.derived_index import (
    BUILD_STATUS_BUILDING,
    BUILD_STATUS_FAILED,
    BUILD_STATUS_PUBLISHED,
    PROJECTION_VERSION,
    DerivedIndexError,
    begin_index_build,
    clear_m8_derived_state,
    compute_canonical_fingerprint,
    derived_state_snapshot,
    describe_derived_foundation,
    fail_index_build,
    get_index_version,
    list_published_indexes,
    m8_derived_state_is_empty,
    m8_tables_present,
)
from src.storage.migrations import MIGRATIONS
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig

TS_A = "2026-01-02T03:04:05+00:00"
TS_B = "2026-01-03T03:04:05+00:00"

EDGE_SQL = (
    "INSERT INTO zm_graph_edges (edge_id, from_resource_type, from_resource_id, "
    "relation_type, to_resource_type, to_resource_id, project_id, "
    "relation_source, source_ref, projection_version, identity_version, "
    "provenance_hash, content_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
)

ENTITY_SQL = (
    "INSERT INTO zm_entities (entity_id, entity_type, canonical_name, project_id, "
    "relation_source, source_ref, projection_version, identity_version, "
    "provenance_hash, content_hash) VALUES (?,?,?,?,?,?,?,?,?,?)"
)


@pytest.fixture()
def db(tmp_path: Path):
    store = SQLiteStore(SQLiteStoreConfig(path=tmp_path / "meta.sqlite"))
    store.ensure_schema()
    try:
        yield store
    finally:
        store.close()


def _project(db: SQLiteStore) -> None:
    """Deterministic stand-in projection: fixed inputs, fixed derived rows.

    M8.1 owns no real projection (that is M8.2). This exercises the rebuild
    LIFECYCLE the foundation is responsible for.
    """
    db._conn.execute(ENTITY_SQL, ("ent_1", "person", "Ada", "P1", "m2_relation",
                                  "r:1", PROJECTION_VERSION, "v1", "ph1", "ch1"))
    db._conn.execute(EDGE_SQL, ("edg_1", "event", "E1", "supports", "event", "E2",
                                "P1", "m2_relation", "r:1", PROJECTION_VERSION,
                                "v1", "ph2", "ch2"))
    db._conn.execute(EDGE_SQL, ("edg_2", "event", "E1", "references", "artifact",
                                "A1", "P1", "m2_artifact", "r:2",
                                PROJECTION_VERSION, "v1", "ph3", "ch3"))
    db._conn.execute(
        "INSERT INTO zm_temporal_index (resource_type, resource_id, created_at, "
        "effective_at, provenance_hash) VALUES (?,?,?,?,?)",
        ("decision", "D1", TS_A, TS_B, "ph4"),
    )
    db._conn.commit()


class TestClearAndRebuild:
    def test_starts_empty(self, db):
        assert m8_derived_state_is_empty(db._conn) is True

    def test_projection_populates_state(self, db):
        _project(db)
        assert m8_derived_state_is_empty(db._conn) is False

    def test_clear_empties_all_derived_tables(self, db):
        _project(db)
        deleted = clear_m8_derived_state(db._conn)
        assert deleted["zm_graph_edges"] == 2
        assert deleted["zm_entities"] == 1
        assert deleted["zm_temporal_index"] == 1
        assert m8_derived_state_is_empty(db._conn) is True

    def test_rebuild_produces_equivalent_state(self, db):
        _project(db)
        before = derived_state_snapshot(db._conn)

        clear_m8_derived_state(db._conn)
        assert derived_state_snapshot(db._conn) == {
            "zm_entities": [], "zm_entity_mentions": [],
            "zm_graph_edges": [], "zm_temporal_index": [],
        }

        _project(db)
        assert derived_state_snapshot(db._conn) == before

    def test_rebuild_is_order_independent(self, db):
        # Insert the same logical rows in a different order; the deterministic
        # snapshot must be identical (no insertion-order dependence).
        _project(db)
        first = derived_state_snapshot(db._conn)
        clear_m8_derived_state(db._conn)

        db._conn.execute(
            "INSERT INTO zm_temporal_index (resource_type, resource_id, created_at, "
            "effective_at, provenance_hash) VALUES (?,?,?,?,?)",
            ("decision", "D1", TS_A, TS_B, "ph4"),
        )
        db._conn.execute(EDGE_SQL, ("edg_2", "event", "E1", "references", "artifact",
                                    "A1", "P1", "m2_artifact", "r:2",
                                    PROJECTION_VERSION, "v1", "ph3", "ch3"))
        db._conn.execute(EDGE_SQL, ("edg_1", "event", "E1", "supports", "event", "E2",
                                    "P1", "m2_relation", "r:1", PROJECTION_VERSION,
                                    "v1", "ph2", "ch2"))
        db._conn.execute(ENTITY_SQL, ("ent_1", "person", "Ada", "P1", "m2_relation",
                                      "r:1", PROJECTION_VERSION, "v1", "ph1", "ch1"))
        db._conn.commit()

        assert derived_state_snapshot(db._conn) == first

    def test_clear_does_not_touch_canonical_projection_tables(self, db):
        db._conn.execute(
            "INSERT INTO zm_meta (event_id, trace_id, event_type, source, "
            "schema_version, created_at, observed_at, sequence, lifecycle_status, "
            "verification_status, confidence, sensitivity, retention, content_hash, "
            "redaction_applied, ingested_at, origin_jsonl) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("E1", "T1", "note", "test", 1, TS_A, TS_A, 1, "active", "unverified",
             "medium", "normal", "standard", "h", 0, TS_A, "raw.jsonl"),
        )
        db._conn.commit()
        _project(db)
        clear_m8_derived_state(db._conn)
        remaining = db._conn.execute("SELECT COUNT(*) FROM zm_meta").fetchone()[0]
        assert remaining == 1

    def test_clear_requires_v9(self, tmp_path):
        store = SQLiteStore(SQLiteStoreConfig(path=tmp_path / "v8.sqlite"))
        for v in sorted(x for x in MIGRATIONS if x <= 8):
            store._apply_up(v, note="t")
        try:
            assert m8_tables_present(store._conn) is False
            with pytest.raises(DerivedIndexError):
                clear_m8_derived_state(store._conn)
        finally:
            store.close()


class TestCanonicalFingerprint:
    def test_deterministic(self):
        d = {"cutoff_sequence": 42, "events": ["a", "b"]}
        assert compute_canonical_fingerprint(d) == compute_canonical_fingerprint(dict(d))

    def test_key_order_independent(self):
        assert compute_canonical_fingerprint({"a": 1, "b": 2}) == (
            compute_canonical_fingerprint({"b": 2, "a": 1})
        )

    def test_changes_with_canonical_state(self):
        assert compute_canonical_fingerprint({"seq": 1}) != (
            compute_canonical_fingerprint({"seq": 2})
        )

    def test_rejects_non_mapping(self):
        with pytest.raises(DerivedIndexError):
            compute_canonical_fingerprint(["not", "a", "mapping"])  # type: ignore[arg-type]


class TestIndexVersionRegistry:
    def _begin(self, db, name="zm_graph_edges"):
        return begin_index_build(
            db._conn, index_name=name, version="1", source_cutoff=TS_A,
            canonical_fingerprint="fp1", built_at=TS_B,
        )

    def test_begin_marks_building(self, db):
        self._begin(db)
        rec = get_index_version(db._conn, "zm_graph_edges")
        assert rec is not None and rec.build_status == BUILD_STATUS_BUILDING

    def test_building_is_not_published(self, db):
        self._begin(db)
        assert list_published_indexes(db._conn) == []

    def test_publish_promotes(self, db):
        self._begin(db)
        from src.m8.derived_index import publish_index_build
        publish_index_build(db._conn, "zm_graph_edges")
        rec = get_index_version(db._conn, "zm_graph_edges")
        assert rec is not None and rec.build_status == BUILD_STATUS_PUBLISHED
        assert [r.index_name for r in list_published_indexes(db._conn)] == ["zm_graph_edges"]

    def test_failed_build_never_published(self, db):
        self._begin(db)
        fail_index_build(db._conn, "zm_graph_edges")
        rec = get_index_version(db._conn, "zm_graph_edges")
        assert rec is not None and rec.build_status == BUILD_STATUS_FAILED
        assert list_published_indexes(db._conn) == []

    def test_rebuild_overwrites_previous_version_row(self, db):
        from src.m8.derived_index import publish_index_build
        self._begin(db)
        publish_index_build(db._conn, "zm_graph_edges")
        begin_index_build(
            db._conn, index_name="zm_graph_edges", version="2", source_cutoff=TS_B,
            canonical_fingerprint="fp2", built_at=TS_B,
        )
        rec = get_index_version(db._conn, "zm_graph_edges")
        assert rec is not None
        assert rec.version == "2"
        # Re-opening a build must drop it back out of the published set.
        assert rec.build_status == BUILD_STATUS_BUILDING
        assert list_published_indexes(db._conn) == []

    def test_unknown_index_name_rejected(self, db):
        with pytest.raises(DerivedIndexError):
            begin_index_build(
                db._conn, index_name="zm_totally_new", version="1",
                source_cutoff=TS_A, canonical_fingerprint="fp", built_at=TS_B,
            )

    def test_malformed_timestamps_rejected(self, db):
        from src.m8.temporal_contract import TemporalError
        with pytest.raises(TemporalError):
            begin_index_build(
                db._conn, index_name="zm_graph_edges", version="1",
                source_cutoff="2026-01-02T03:04:05",  # timezone-naive
                canonical_fingerprint="fp", built_at=TS_B,
            )

    def test_publish_without_build_rejected(self, db):
        from src.m8.derived_index import publish_index_build
        with pytest.raises(DerivedIndexError):
            publish_index_build(db._conn, "zm_entities")

    def test_published_list_is_deterministically_ordered(self, db):
        from src.m8.derived_index import publish_index_build
        for name in ("zm_temporal_index", "zm_entities", "zm_graph_edges"):
            begin_index_build(
                db._conn, index_name=name, version="1", source_cutoff=TS_A,
                canonical_fingerprint="fp", built_at=TS_B,
            )
            publish_index_build(db._conn, name)
        assert [r.index_name for r in list_published_indexes(db._conn)] == [
            "zm_entities", "zm_graph_edges", "zm_temporal_index",
        ]


class TestFoundationDescription:
    def test_declares_derived_not_canonical(self):
        d = describe_derived_foundation()
        assert d["canonical_store"] == "jsonl"
        assert d["sqlite_is_derived"] is True
        assert d["schema_version"] == 10

    def test_declares_deferred_behavior_absent(self):
        d = describe_derived_foundation()
        # Projection is implemented as of M8.2; temporal as-of/history reads as
        # of M8.4. Traversal and calibration scoring remain deferred.
        assert d["projection_implemented"] is True
        assert d["temporal_query_implemented"] is True
        assert d["traversal_implemented"] is False
        assert d["calibration_scoring_implemented"] is True
