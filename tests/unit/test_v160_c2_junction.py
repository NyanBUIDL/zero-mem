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

from src.storage.ingest import ingest_file
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


def _insert_legacy_meta(store, event_id, ks):
    """Insert a pre-v13-style zm_meta row with a legacy knowledge_space_id."""
    store._conn.execute(
        "INSERT INTO zm_meta (event_id, trace_id, event_type, source, schema_version, "
        "created_at, observed_at, sequence, lifecycle_status, verification_status, "
        "confidence, sensitivity, retention, content_hash, redaction_applied, "
        "ingested_at, origin_jsonl, knowledge_space_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (event_id, f"t-{event_id}", "system_event", "probe", 1,
         "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", 0, "observed", "none",
         "medium", "internal", "persistent", f"h-{event_id}", 0,
         "2026-01-01T00:00:00Z", f"s-{event_id}", ks),
    )


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

    def test_fresh_ingest_junction_parity(self, tmp_path):
        """Two independent FRESH ingests of the same canonical must yield the
        same junction (derived determinism). NOTE: this is ingest parity, NOT
        rebuild_from_jsonl replay — real rebuild-from-canonical is covered in
        plan C3 (behavioral: junction after rebuild == junction after ingest).
        """
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
        assert j1 == j2, "fresh ingest from canonical must reproduce the junction"

    def test_migration_13_upgrade_from_v12_backfills_legacy_only(self, tmp_path):
        """Real upgrade path through the migration RUNNER (not direct migrate_13.up).

        v13 store -> downgrade_to(12) -> insert pre-v13 zm_meta rows
        (valid / whitespace variants / numeric / NULL legacy) -> reopen ->
        ensure_schema(). Asserts: version advances to 13; valid legacy backfills;
        EVERY whitespace-only legacy (space, tab, newline, CR, NBSP) and NULL
        stay UNSCoped (ADR-V160-01 sec2 — malformed/blank legacy is ignored);
        numeric-origin legacy is promoted as text '123' because SQLite TEXT
        affinity (migrate_11 TEXT column) already collapsed it — indistinguishable
        from a legitimate string id; documented ADR boundary, canonical replay
        (rebuild_from_jsonl, C3) is authoritative for malformed-type rows;
        ledger records exactly one v13 row.
        """
        db_path = tmp_path / "upgrade.sqlite"
        store = SQLiteStore(SQLiteStoreConfig(path=db_path))
        store.ensure_schema()
        assert store.get_schema_version() == 13
        store.downgrade_to(12, note="test")
        assert store.get_schema_version() == 12
        assert not store.table_exists("zm_event_spaces"), "downgrade must drop junction"
        _insert_legacy_meta(store, "leg-valid", "legacy-ks")
        _insert_legacy_meta(store, "leg-space", "   ")
        _insert_legacy_meta(store, "leg-tab", "\t")
        _insert_legacy_meta(store, "leg-nl", "\n")
        _insert_legacy_meta(store, "leg-cr", "\r")
        _insert_legacy_meta(store, "leg-nbsp", "\u00a0")
        _insert_legacy_meta(store, "leg-num", 123)  # stored as text '123' (TEXT affinity)
        _insert_legacy_meta(store, "leg-null", None)
        store._conn.commit()
        _checkpoint_and_close(store)
        store2 = SQLiteStore(SQLiteStoreConfig(path=db_path))
        try:
            assert store2.ensure_schema() == 13
            junction = _read(str(db_path),
                             "SELECT event_id, knowledge_space_id FROM zm_event_spaces ORDER BY event_id")
            assert junction == [
                {"event_id": "leg-num", "knowledge_space_id": "123"},
                {"event_id": "leg-valid", "knowledge_space_id": "legacy-ks"},
            ], (
                "whitespace-only and NULL legacy must NOT be backfilled (ADR sec2); "
                "numeric-origin is promoted as text (ADR boundary — see migrate_13 "
                "docstring; canonical replay authoritative)"
            )
            ledger = _read(str(db_path),
                           "SELECT COUNT(*) AS n FROM zm_migrations WHERE version=13")
            assert ledger[0]["n"] == 1, "ledger must record exactly one v13 row after upgrade"
        finally:
            _checkpoint_and_close(store2)

    def test_downgrade_13_removes_junction_and_index(self, tmp_path):
        db_path = tmp_path / "down.sqlite"
        store = SQLiteStore(SQLiteStoreConfig(path=db_path))
        store.ensure_schema()
        assert store.get_schema_version() == 13
        assert store.table_exists("zm_event_spaces")
        idx = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_zm_event_spaces_ks'").fetchone()
        assert idx is not None, "v13 must create the ks index"
        store.downgrade_to(12, note="test")
        assert store.get_schema_version() == 12
        assert not store.table_exists("zm_event_spaces")
        idx2 = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_zm_event_spaces_ks'").fetchone()
        assert idx2 is None, "downgrade must drop the ks index with the table"
        store.close()

    def test_migration_13_backfill_streams_batched_no_full_table_fetchall(self, tmp_path):
        """Large-store guard (review P2): backfill must stream zm_meta in fixed
        batches — never load the full table into memory. Two checks:
        (1) static guard: the migration module must not call fetchall() on the
        backfill read path (repo convention: source inspection, cf. m8 tests);
        (2) behavioral: > batch-size valid legacy rows all backfill across
        batches — an early-exit/single-batch bug would drop later batches.
        """
        import inspect

        from src.storage.migrations import migrate_13

        src = inspect.getsource(migrate_13)
        assert ".fetchall(" not in src, (
            "backfill must stream by batch, never call fetchall() on the full "
            "zm_meta table (review P2 — large stores would OOM)"
        )
        batch = migrate_13._BACKFILL_BATCH_SIZE
        db_path = tmp_path / "big.sqlite"
        store = SQLiteStore(SQLiteStoreConfig(path=db_path))
        store.ensure_schema()
        store.downgrade_to(12, note="test")
        for i in range(batch * 3 + 7):
            _insert_legacy_meta(store, f"leg-{i:04d}", f"ks-{i % 7}")
        store._conn.commit()
        _checkpoint_and_close(store)
        store2 = SQLiteStore(SQLiteStoreConfig(path=db_path))
        try:
            assert store2.ensure_schema() == 13
            n = _read(str(db_path), "SELECT COUNT(*) AS n FROM zm_event_spaces")
            assert n[0]["n"] == batch * 3 + 7, (
                "every valid legacy row must backfill across multiple batches")
        finally:
            _checkpoint_and_close(store2)
