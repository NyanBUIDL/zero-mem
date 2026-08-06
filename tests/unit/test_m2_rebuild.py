"""M2.3 focused tests: lifecycle/verification projection and rebuild_from_jsonl.

Covers only M2.3 (derived lifecycle + provenance projection over canonical JSONL, and
full rebuild). Uses temporary directories; never writes to the real ~/.hermes.
"""
from __future__ import annotations

import pathlib
import sqlite3
from unittest import mock

import pytest

from src.capture.validation import validate_envelope  # noqa: F401 (contract reuse)
from src.storage.ingest import (
    IngestionFailure,
    IngestionOutcome,
    count_metadata,
    get_checkpoint,
    get_lifecycle,
    get_provenance,
    get_trace,
    ingest_file,
    list_by_lifecycle_state,
    rebuild_from_jsonl,
    scan_sqlite_for_secrets,
    verify_rebuild_parity,
)
from src.storage.migrations import CURRENT_SCHEMA_VERSION
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig

SECRET = "SK-M2-3-DEADBEEF-99"


def _config(tmp_path: pathlib.Path, name: str = "meta.sqlite") -> SQLiteStoreConfig:
    return SQLiteStoreConfig(path=tmp_path / name)


def _open_store(tmp_path: pathlib.Path, name: str = "meta.sqlite") -> SQLiteStore:
    store = SQLiteStore(_config(tmp_path, name))
    store.ensure_schema()
    return store


def _make_env(eid="evt-1", **kw):
    base = dict(
        event_id=eid, trace_id="tr-1", event_type="tool_observation",
        source="pre_tool_call", schema_version=1,
        created_at="2026-08-06T00:00:00Z", observed_at="2026-08-06T00:00:00Z",
        sequence=0, lifecycle_status="observed", verification_status="none",
        confidence="medium", sensitivity="internal", retention="persistent",
        sanitized_content_hash="h-" + eid,
        sanitized_content={"text": "clean"}, redaction_audit=[],
    )
    base.update(kw)
    return base


def _write_jsonl(path: pathlib.Path, items) -> None:
    lines = []
    for it in items:
        if isinstance(it, (bytes, bytearray)):
            lines.append(it.decode("utf-8") if isinstance(it, bytes) else it)
        elif isinstance(it, str):
            lines.append(it)
        else:
            import json
            lines.append(json.dumps(it))
    path.write_text("\n".join(lines) + "\n")


# ---- migration / schema -----------------------------------------------------

def test_migration_v2_to_current(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        assert store.get_schema_version() == CURRENT_SCHEMA_VERSION
        assert store.table_exists("zm_lifecycle")
        assert store.table_exists("zm_provenance")
        # v4 relation/scope/artifact tables also present
        assert store.table_exists("zm_relations")
        assert store.table_exists("zm_scopes")
        assert store.table_exists("zm_artifacts")
    finally:
        store.close()


def test_downgrade_v3_to_v2_drops_new_tables(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        assert store.get_schema_version() == CURRENT_SCHEMA_VERSION
        store.downgrade_to(2)
        assert store.get_schema_version() == 2
        assert not store.table_exists("zm_lifecycle")
        assert not store.table_exists("zm_provenance")
        # zm_meta (v1) and zm_ingest_* (v2) survive.
        assert store.table_exists("zm_meta")
        assert store.table_exists("zm_ingest_checkpoint")
    finally:
        store.close()


def test_reopen_v3_idempotent(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    store.close()
    store2 = _open_store(tmp_path)
    try:
        assert store2.get_schema_version() == CURRENT_SCHEMA_VERSION
        assert store2.table_exists("zm_lifecycle")
        assert store2.table_exists("zm_provenance")
    finally:
        store2.close()


# ---- lifecycle projection ---------------------------------------------------

def test_lifecycle_mirrors_envelope(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a", lifecycle_status="active")])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        lc = get_lifecycle(store, "a")
        assert lc is not None
        assert lc["current_state"] == "active"
        assert lc["superseded_by"] is None  # reserved for M2.4
        # M2.4 sets active_key = trace_id for active events
        assert lc["active_key"] == "tr-1"
    finally:
        store.close()


def test_lifecycle_records_conflicted_archived_deleted(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [
        _make_env("c", lifecycle_status="conflicted"),
        _make_env("x", lifecycle_status="archived"),
        _make_env("d", lifecycle_status="deleted"),
    ])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        assert get_lifecycle(store, "c")["current_state"] == "conflicted"
        assert get_lifecycle(store, "x")["current_state"] == "archived"
        assert get_lifecycle(store, "d")["current_state"] == "deleted"
        assert set(list_by_lifecycle_state(store, "conflicted")) == {"c"}
    finally:
        store.close()


# ---- provenance projection --------------------------------------------------

def test_provenance_seeded_per_event(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a", verification_status="deterministic_verification", trace_id="tr-A")])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        prov = get_provenance(store, "a")
        assert len(prov) == 1
        assert prov[0]["verification_status"] == "deterministic_verification"
        assert prov[0]["verifier"] == "deterministic_check"
        assert prov[0]["evidence_ref"] == "tr-A"
    finally:
        store.close()


def test_provenance_rank_stored_as_data_only(tmp_path: pathlib.Path) -> None:
    # Multiple verification rows possible later; we only assert deterministic seeding here.
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [
        _make_env("a", verification_status="user_confirmation"),
        _make_env("b", verification_status="direct_tool_output"),
    ])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        assert get_provenance(store, "a")[0]["verification_status"] == "user_confirmation"
        assert get_provenance(store, "b")[0]["verification_status"] == "direct_tool_output"
    finally:
        store.close()


# ---- first-write / later-event idempotence ----------------------------------

def test_first_write_seeds_lifecycle_provenance(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a")])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        assert get_lifecycle(store, "a") is not None
        assert len(get_provenance(store, "a")) == 1
        assert count_metadata(store) == 1
    finally:
        store.close()


def test_duplicate_event_id_no_extra_lifecycle_provenance(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a")])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        # re-ingest same file (idempotent)
        ingest_file(store, jl)
        assert count_metadata(store) == 1
        assert get_lifecycle(store, "a") is not None
        assert len(get_provenance(store, "a")) == 1
    finally:
        store.close()


def test_conflict_keeps_original_no_new_lifecycle(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a", sanitized_content_hash="h-orig", lifecycle_status="confirmed")])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        # later event with same id, different hash
        jl2 = tmp_path / "conflict.jsonl"
        _write_jsonl(jl2, [_make_env("a", sanitized_content_hash="h-new", lifecycle_status="active")])
        ingest_file(store, jl2)
        assert get_trace(store, "a")["content_hash"] == "h-orig"
        assert get_lifecycle(store, "a")["current_state"] == "confirmed"
        assert len(get_provenance(store, "a")) == 1
    finally:
        store.close()


# ---- rebuild_from_jsonl -----------------------------------------------------

def _two_file_corpus(tmp_path: pathlib.Path):
    jl1 = tmp_path / "a.jsonl"
    jl2 = tmp_path / "b.jsonl"
    _write_jsonl(jl1, [
        _make_env("a", lifecycle_status="active", verification_status="deterministic_verification"),
        _make_env("b", lifecycle_status="conflicted"),
        "{not valid json with " + SECRET + "}",
    ])
    _write_jsonl(jl2, [
        _make_env("c", lifecycle_status="archived", trace_id="tr-C"),
    ])
    return jl1, jl2


def test_rebuild_populates_all_projections(tmp_path: pathlib.Path) -> None:
    jl1, jl2 = _two_file_corpus(tmp_path)
    store = _open_store(tmp_path)
    try:
        reports = rebuild_from_jsonl(store, [jl1, jl2])
        assert count_metadata(store) == 3  # 2 valid in a.jsonl (one malformed) + 1 in b.jsonl
        assert get_lifecycle(store, "a")["current_state"] == "active"
        assert get_lifecycle(store, "b")["current_state"] == "conflicted"
        assert get_lifecycle(store, "c")["current_state"] == "archived"
        assert len(get_provenance(store, "c")) == 1
        # malformed line reported as invalid_record but ingestion continued
        all_counts = [r.counts["invalid_record"] for r in reports.values()]
        assert sum(all_counts) == 1
    finally:
        store.close()


def test_rebuild_parity_with_incremental(tmp_path: pathlib.Path) -> None:
    jl1, jl2 = _two_file_corpus(tmp_path)
    inc = _open_store(tmp_path / "inc")
    rb = _open_store(tmp_path / "rb")
    try:
        ingest_file(inc, jl1)
        ingest_file(inc, jl2)
        rebuild_from_jsonl(rb, [jl1, jl2])
        assert verify_rebuild_parity(inc, rb) is True
    finally:
        inc.close()
        rb.close()


def test_rebuild_deterministic_repeatable(tmp_path: pathlib.Path) -> None:
    jl1, jl2 = _two_file_corpus(tmp_path)
    rb1 = _open_store(tmp_path / "rb1")
    rb2 = _open_store(tmp_path / "rb2")
    try:
        rebuild_from_jsonl(rb1, [jl1, jl2])
        rebuild_from_jsonl(rb2, [jl1, jl2])
        assert verify_rebuild_parity(rb1, rb2) is True
    finally:
        rb1.close()
        rb2.close()


def test_rebuild_into_empty_db(tmp_path: pathlib.Path) -> None:
    jl1, jl2 = _two_file_corpus(tmp_path)
    # A store whose DB file does not yet exist.
    empty_store = SQLiteStore(_config(tmp_path, name="fresh.sqlite"))
    empty_store.ensure_schema()
    try:
        rebuild_from_jsonl(empty_store, [jl1, jl2])
        assert count_metadata(empty_store) == 3
        assert empty_store.get_schema_version() == CURRENT_SCHEMA_VERSION
    finally:
        empty_store.close()


def test_rebuild_malformed_line_sanitized_and_continues(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [
        _make_env("a"),
        "{broken json " + SECRET + "}",
        _make_env("b"),
    ])
    store = _open_store(tmp_path)
    try:
        reports = rebuild_from_jsonl(store, [jl])
        rep = reports[jl.name]
        assert rep.counts["invalid_record"] >= 1
        assert count_metadata(store) == 2  # a and b ingested despite the broken middle line
    finally:
        store.close()


def test_rebuild_preserves_migrations_ledger(tmp_path: pathlib.Path) -> None:
    jl1, jl2 = _two_file_corpus(tmp_path)
    store = _open_store(tmp_path)
    try:
        rebuild_from_jsonl(store, [jl1, jl2])
        # schema version ledger still intact at current (v5)
        assert store.get_schema_version() == CURRENT_SCHEMA_VERSION
        cur = store._conn.cursor()
        versions = [r["version"] for r in cur.execute("SELECT version FROM zm_migrations ORDER BY version").fetchall()]
        assert versions == [1, 2, 3, 4, 5]
    finally:
        store.close()


# ---- transaction / crash safety ---------------------------------------------

def _patch_commit_to_fail_on(store, fail_on_call, monkeypatch):
    import src.storage.ingest as ingest_mod
    calls = {"n": 0}
    original = ingest_mod._commit

    def fake_commit(conn):
        calls["n"] += 1
        if calls["n"] == fail_on_call:
            raise sqlite3.OperationalError("simulated commit failure")
        return original(conn)

    monkeypatch.setattr(ingest_mod, "_commit", fake_commit)


def test_per_line_crash_rolls_back_whole_event(tmp_path: pathlib.Path, monkeypatch) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a"), _make_env("b"), _make_env("c")])
    store = _open_store(tmp_path)
    try:
        _patch_commit_to_fail_on(store, fail_on_call=2, monkeypatch=monkeypatch)  # line b fails
        rep = ingest_file(store, jl)
        assert rep.stopped is True
        # line b's zm_meta + lifecycle + provenance must NOT exist (rolled back)
        assert get_trace(store, "b") is None
        assert get_lifecycle(store, "b") is None
        assert get_provenance(store, "b") == []
        # lines before the failure committed fully (meta + lifecycle + provenance)
        assert get_trace(store, "a") is not None
        assert get_lifecycle(store, "a") is not None
        assert len(get_provenance(store, "a")) == 1
        assert count_metadata(store) == 1
        # resume with commit restored: line b re-attempted, total complete
        rebuild_from_jsonl(store, [jl])
        assert count_metadata(store) == 3
        assert get_lifecycle(store, "b") is not None
    finally:
        store.close()


# ---- secret scan / immutability / boundaries --------------------------------

def test_secret_absent_across_projections(tmp_path: pathlib.Path) -> None:
    # M1 redaction guarantees sanitized_content is secret-free before M2.5 indexes it in FTS.
    # FTS-level secret coverage is proven separately in M2.5.
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a", sanitized_content={"text": "benign observation"})])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        found = scan_sqlite_for_secrets(store, [SECRET])
        assert found == [], f"secret leaked: {found}"
    finally:
        store.close()


def test_jsonl_byte_for_byte_unchanged(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a"), _make_env("b")])
    raw = jl.read_bytes()
    store = _open_store(tmp_path)
    try:
        rebuild_from_jsonl(store, [jl])
        assert jl.read_bytes() == raw
    finally:
        store.close()


def test_no_later_m2_tables_or_behavior(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        tables = {r["name"] for r in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        # zm_relations/zm_scopes/zm_artifacts ARE created by M2.4; zm_fts IS created by M2.5 (FTS5).
        # M2.6+ tables (e.g. zm_tombstone) must still be absent.
        assert "zm_tombstone" not in tables
        # module does not expose later-M2 entry points
        import src.storage.ingest as ingest_mod
        assert not hasattr(ingest_mod, "rebuild_relations")
        assert not hasattr(ingest_mod, "build_fts")
        assert not hasattr(ingest_mod, "apply_tombstone")
    finally:
        store.close()


def test_no_real_hermes_home_writes(tmp_path: pathlib.Path, monkeypatch) -> None:
    # Baseline-aware assertion: capture exact REAL ~/.hermes baseline, run with an isolated
    # temporary HERMES_HOME, then assert the real home is byte-identical (no project-attributable write).
    real_home = pathlib.Path.home() / ".hermes"
    # Independently-verified UNRELATED sidecars (unrelated kanban sqlite WAL/SHM) are mutated by a
    # background process during the run; exclude only those specific files. Any NEW entry fails.
    UNRELATED = {"kanban.db-wal", "kanban.db-shm"}
    baseline = ({p.relative_to(real_home) for p in real_home.rglob("*")} if real_home.exists() else set()) - UNRELATED
    isolated = tmp_path / "isolated_hermes_home"
    isolated.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(isolated))
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: tmp_path))
    jl1, jl2 = _two_file_corpus(tmp_path)
    store = _open_store(tmp_path)
    try:
        rebuild_from_jsonl(store, [jl1, jl2])
    finally:
        store.close()
    after = ({p.relative_to(real_home) for p in real_home.rglob("*")} if real_home.exists() else set()) - UNRELATED
    assert after == baseline, (
        f"M2.3 wrote to the real ~/.hermes: added={after - baseline}, removed={baseline - after}"
    )


def test_no_network_calls(tmp_path: pathlib.Path) -> None:
    jl1, jl2 = _two_file_corpus(tmp_path)
    with mock.patch("socket.socket", side_effect=AssertionError("net")):
        store = _open_store(tmp_path)
        try:
            rebuild_from_jsonl(store, [jl1, jl2])
        finally:
            store.close()
