"""V1.6.0 C2 RED-first — ingest denormalize: zm_event_spaces junction + PRIMARY-KS.

ADR-V160-01 §4/§5 + plan C2:
- migration v13 creates zm_event_spaces(event_id, knowledge_space_id, PK) +
  index on ks; backfills from zm_meta.knowledge_space_id (legacy singular).
- ingest: canonical knowledge_space_ids (precedence) / legacy singular ->
  one junction row per KS; zm_meta.knowledge_space_id = PRIMARY-KS (first of
  the canonical list, NULL if empty); zm_scopes gets one knowledge_space row
  per KS.

RED on current tree (no migration 13, ingest writes no junction).
"""
from __future__ import annotations

import sqlite3

import pytest

from src.storage.ingest import ingest_file
from src.storage.migrations import MIGRATIONS
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from tests.unit.test_m3_query import (
    _checkpoint_and_close,
    _make_env,
    _open_store,
    _write_jsonl,
)


def _ingest(tmp_path, items, name="m.sqlite"):
    jl = tmp_path / f"{name}.jsonl"
    _write_jsonl(jl, items)
    store = _open_store(tmp_path, name)
    ingest_file(store, jl)
    _checkpoint_and_close(store)
    return str(tmp_path / name)


def _read(db_path, sql):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql)]
    finally:
        conn.close()


class TestC2JunctionIngest:
    def test_multi_ks_junction_and_primary(self, tmp_path):
        db = _ingest(tmp_path, [
            _make_env("ev1", profile_id="p1", project_id="P",
                      knowledge_space_ids=["B", "A"]),
        ])
        rows = _read(db, "SELECT event_id, knowledge_space_id FROM zm_event_spaces ORDER BY knowledge_space_id")
        assert {(r["event_id"], r["knowledge_space_id"]) for r in rows} == {
            ("ev1", "A"), ("ev1", "B")}
        meta = _read(db, "SELECT knowledge_space_id FROM zm_meta WHERE event_id='ev1'")
        assert meta[0]["knowledge_space_id"] == "B", "PRIMARY-KS = first of canonical list"

    def test_legacy_singular_junction(self, tmp_path):
        db = _ingest(tmp_path, [
            _make_env("ev1", profile_id="p1", project_id="P",
                      knowledge_space_id="legacy-ks"),
        ])
        rows = _read(db, "SELECT knowledge_space_id FROM zm_event_spaces")
        assert [r["knowledge_space_id"] for r in rows] == ["legacy-ks"]
        meta = _read(db, "SELECT knowledge_space_id FROM zm_meta WHERE event_id='ev1'")
        assert meta[0]["knowledge_space_id"] == "legacy-ks"

    def test_no_ks_no_junction(self, tmp_path):
        db = _ingest(tmp_path, [
            _make_env("ev1", profile_id="p1", project_id="P"),
        ])
        rows = _read(db, "SELECT knowledge_space_id FROM zm_event_spaces")
        assert rows == []
        meta = _read(db, "SELECT knowledge_space_id FROM zm_meta WHERE event_id='ev1'")
        assert meta[0]["knowledge_space_id"] is None

    def test_empty_list_plus_legacy_uses_legacy(self, tmp_path):
        db = _ingest(tmp_path, [
            _make_env("ev1", profile_id="p1", project_id="P",
                      knowledge_space_ids=[], knowledge_space_id="legacy-ks"),
        ])
        rows = _read(db, "SELECT knowledge_space_id FROM zm_event_spaces")
        assert [r["knowledge_space_id"] for r in rows] == ["legacy-ks"]

    def test_scopes_one_per_ks(self, tmp_path):
        db = _ingest(tmp_path, [
            _make_env("ev1", profile_id="p1", project_id="P",
                      knowledge_space_ids=["A", "B"]),
        ])
        rows = _read(
            db,
            "SELECT scope_id FROM zm_scopes WHERE scope_type='knowledge_space' ORDER BY scope_id")
        assert [r["scope_id"] for r in rows] == ["A", "B"]

    def test_rebuild_junction_faithful(self, tmp_path):
        items = [
            _make_env("ev1", profile_id="p1", project_id="P",
                      knowledge_space_ids=["B", "A"]),
            _make_env("ev2", profile_id="p1", project_id="P",
                      knowledge_space_id="legacy-ks"),
            _make_env("ev3", profile_id="p1", project_id="P"),
        ]
        db1 = _ingest(tmp_path, items, "m1.sqlite")
        db2 = _ingest(tmp_path, items, "m2.sqlite")
        j1 = _read(db1, "SELECT event_id, knowledge_space_id FROM zm_event_spaces ORDER BY event_id, knowledge_space_id")
        j2 = _read(db2, "SELECT event_id, knowledge_space_id FROM zm_event_spaces ORDER BY event_id, knowledge_space_id")
        assert j1 == j2, "rebuild from canonical must reproduce the junction"

    def test_migration_13_backfills_legacy(self, tmp_path):
        """Simulate a v12 store with legacy ks rows; migration 13 backfills."""
        from src.storage.migrations import migrate_13
        store = SQLiteStore(SQLiteStoreConfig(path=tmp_path / "v12.sqlite"))
        store.ensure_schema()
        # manually insert a legacy-ks row into zm_meta as if pre-v13
        store._conn.execute(
            "INSERT INTO zm_meta (event_id, trace_id, event_type, source, schema_version, "
            "created_at, observed_at, sequence, lifecycle_status, verification_status, "
            "confidence, sensitivity, retention, content_hash, redaction_applied, "
            "ingested_at, origin_jsonl, knowledge_space_id) "
            "VALUES ('legacy-1','t1','system_event','probe',1,'2026-01-01T00:00:00Z',"
            "'2026-01-01T00:00:00Z',0,'observed','none','medium','internal','persistent',"
            "'h1',0,'2026-01-01T00:00:00Z','s1','legacy-ks')")
        store._conn.commit()
        migrate_13.up(store._conn, "test")
        store._conn.commit()
        rows = _read(str(tmp_path / "v12.sqlite"),
                     "SELECT event_id, knowledge_space_id FROM zm_event_spaces")
        assert (rows and rows[0]["event_id"] == "legacy-1"
                and rows[0]["knowledge_space_id"] == "legacy-ks"), (
            "migration 13 must backfill junction from legacy zm_meta ks")
