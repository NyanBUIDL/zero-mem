"""M2.6 focused tests: retention tombstones, logical deletion, secret scanning, rollback.

Covers only M2.6 (migration v6, tombstone projection, idempotence, pending_unknown_target,
lifecycle transitions, active-helper/FTS exclusion, admin helpers, secret scanning, rebuild
parity, downgrade). Uses temporary directories; never writes to the real ~/.hermes.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from src.capture.validation import validate_envelope
from src.storage.migrations import CURRENT_SCHEMA_VERSION
from src.storage.migrations import migrate_6 as _migrate_6
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.storage.ingest import (
    ingest_file,
    rebuild_from_jsonl,
    scan_sqlite_for_secrets,
    search_fts,
    find_by_trace_id,
    list_events_in_scope,
    list_deleted,
    get_tombstone,
    get_deletion_audit,
    get_lifecycle,
    verify_rebuild_parity,
)

TS = "2026-08-06T00:00:00Z"
SECRET = "SK-M2-6-PROBE-XYZ"


def _open_store(tmp_path: pathlib.Path) -> SQLiteStore:
    store = SQLiteStore(SQLiteStoreConfig(path=tmp_path / "m.sqlite"))
    store.ensure_schema()
    return store


def _write_jsonl(path: pathlib.Path, envs: list) -> None:
    path.write_text("\n".join(json.dumps(e) for e in envs) + "\n")


def _make_env(event_id, **over):
    base = dict(
        event_id=event_id,
        trace_id=f"tr-{event_id}",
        event_type="tool_observation",
        source="pre_tool_call",
        schema_version=1,
        created_at=TS,
        observed_at=TS,
        sequence=0,
        lifecycle_status="observed",
        verification_status="none",
        confidence="medium",
        sensitivity="internal",
        retention="persistent",
        sanitized_content_hash=f"h-{event_id}",
        sanitized_content={"text": f"content for {event_id}"},
        redaction_audit=[],
    )
    base.update(over)
    return base


def _make_tombstone(tomb_id, target, **over):
    env = _make_env(tomb_id, event_type="system_event", lifecycle_status="deleted",
                    trace_id=f"tr-{tomb_id}", sanitized_content={"text": f"delete {target}"})
    env["deletion"] = {"target_event_id": target}
    if "deletion" in over:
        env["deletion"].update(over.pop("deletion"))
    env.update(over)
    return env


# ---- migration v6 ------------------------------------------------------------

def test_migration_v5_to_v6(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        assert store.get_schema_version() == CURRENT_SCHEMA_VERSION
        assert CURRENT_SCHEMA_VERSION == 9
        for t in ("zm_tombstones", "zm_deletion_audit"):
            assert store.table_exists(t)
        assert store.index_exists("idx_zm_tombstones_target")
        assert store.index_exists("idx_zm_tombstones_status")
        assert store.index_exists("idx_zm_deletion_audit_target")
        assert store.index_exists("idx_zm_deletion_audit_tomb")
    finally:
        store.close()


def test_downgrade_v6_to_v5_drops_tombstone_tables(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        assert store.get_schema_version() == 9
        store.downgrade_to(5)
        assert store.get_schema_version() == 5
        for t in ("zm_tombstones", "zm_deletion_audit"):
            assert not store.table_exists(t)
    finally:
        store.close()


def test_reopen_schema_v6_idempotent(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        assert store.get_schema_version() == 9
    finally:
        store.close()
    store2 = _open_store(tmp_path)
    try:
        assert store2.get_schema_version() == 9
        assert store2.table_exists("zm_tombstones")
    finally:
        store2.close()


def test_migration_rollback_on_failure_no_partial_advance(tmp_path: pathlib.Path) -> None:
    import sqlite3
    store = _open_store(tmp_path)
    try:
        assert store.get_schema_version() == 9
        real = store._conn

        class _BadConn:
            def cursor(self):
                raise sqlite3.OperationalError("injected failure")

        store._conn = _BadConn()
        with pytest.raises(sqlite3.OperationalError):
            _migrate_6.up(store._conn, "fail")
        store._conn = real
        assert store.get_schema_version() == 9
    finally:
        store.close()


# ---- idempotence -------------------------------------------------------------

def test_duplicate_deletion_event_idempotent(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        jl = tmp_path / "e.jsonl"
        _write_jsonl(jl, [_make_env("a", lifecycle_status="active")])
        ingest_file(store, jl)
        jl2 = tmp_path / "d.jsonl"
        _write_jsonl(jl2, [_make_tombstone("del-1", "a")])
        ingest_file(store, jl2)
        ingest_file(store, jl2)
        cur = store._conn.cursor()
        n = cur.execute("SELECT COUNT(*) AS n FROM zm_tombstones WHERE tombstone_id='del-1'").fetchone()["n"]
        assert n == 1, n
        assert get_lifecycle(store, "a")["current_state"] == "deleted"
    finally:
        store.close()


def test_repeated_tombstone_idempotent(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        jl = tmp_path / "e.jsonl"
        _write_jsonl(jl, [_make_env("a", lifecycle_status="active")])
        ingest_file(store, jl)
        tomb = _make_tombstone("del-1", "a")
        jl2 = tmp_path / "d.jsonl"
        _write_jsonl(jl2, [tomb])
        ingest_file(store, jl2)
        jl3 = tmp_path / "d2.jsonl"
        _write_jsonl(jl3, [tomb])
        rep = ingest_file(store, jl3)
        assert rep.counts.get("duplicate_event_id", 0) >= 1
        cur = store._conn.cursor()
        n = cur.execute("SELECT COUNT(*) AS n FROM zm_tombstones WHERE tombstone_id='del-1'").fetchone()["n"]
        assert n == 1, n
    finally:
        store.close()


# ---- unknown-target / pending ------------------------------------------------

def test_unknown_target_tombstone_pending(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        jl = tmp_path / "d.jsonl"
        _write_jsonl(jl, [_make_tombstone("del-1", "missing")])
        rep = ingest_file(store, jl)
        assert rep.counts.get("new_event") == 1
        assert get_tombstone(store, "del-1")["status"] == "pending_unknown_target"
        assert get_lifecycle(store, "missing") is None
    finally:
        store.close()


def test_pending_unknown_target_retained(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        jl = tmp_path / "d.jsonl"
        _write_jsonl(jl, [_make_tombstone("del-1", "a")])
        ingest_file(store, jl)
        assert get_tombstone(store, "del-1")["status"] == "pending_unknown_target"
        jl2 = tmp_path / "e.jsonl"
        _write_jsonl(jl2, [_make_env("a", lifecycle_status="active")])
        ingest_file(store, jl2)
        assert get_tombstone(store, "del-1")["status"] == "applied"
        assert get_lifecycle(store, "a")["current_state"] == "deleted"
    finally:
        store.close()


def test_target_arriving_after_tombstone(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        _write_jsonl(tmp_path / "d.jsonl", [_make_tombstone("del-1", "a")])
        _write_jsonl(tmp_path / "e.jsonl", [_make_env("a", lifecycle_status="active")])
        ingest_file(store, tmp_path / "d.jsonl")
        ingest_file(store, tmp_path / "e.jsonl")
        assert get_lifecycle(store, "a")["current_state"] == "deleted"
        assert get_tombstone(store, "del-1")["status"] == "applied"
    finally:
        store.close()

def test_validate_envelope_accepts_deletion_block() -> None:
    env = _make_tombstone("del-x", "evt-y")
    validate_envelope(env)


def test_validate_envelope_rejects_deletion_without_target() -> None:
    env = _make_tombstone("del-x", "evt-y")
    env["deletion"] = {}
    with pytest.raises(ValueError):
        validate_envelope(env)


def test_validate_envelope_rejects_deletion_block_on_non_deleted() -> None:
    env = _make_env("a", deletion={"target_event_id": "z"})
    with pytest.raises(ValueError):
        validate_envelope(env)


# ---- known-target tombstone + lifecycle transitions --------------------------

def test_known_target_tombstone_applied(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        jl = tmp_path / "e.jsonl"
        _write_jsonl(jl, [_make_env("a", lifecycle_status="active")])
        ingest_file(store, jl)
        jl2 = tmp_path / "d.jsonl"
        _write_jsonl(jl2, [_make_tombstone("del-1", "a", deletion={"reason_code": "user_request"})])
        ingest_file(store, jl2)
        assert get_lifecycle(store, "a")["current_state"] == "deleted"
        assert get_tombstone(store, "del-1")["status"] == "applied"
        assert get_tombstone(store, "del-1")["target_event_id"] == "a"
    finally:
        store.close()


def test_active_to_deleted(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        jl = tmp_path / "e.jsonl"
        _write_jsonl(jl, [_make_env("a", lifecycle_status="active")])
        ingest_file(store, jl)
        jl2 = tmp_path / "d.jsonl"
        _write_jsonl(jl2, [_make_tombstone("del-1", "a")])
        ingest_file(store, jl2)
        assert get_deletion_audit(store, target_event_id="a")[0]["prior_lifecycle_state"] == "active"
    finally:
        store.close()


def test_archived_to_deleted(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        jl = tmp_path / "e.jsonl"
        _write_jsonl(jl, [_make_env("a", lifecycle_status="archived")])
        ingest_file(store, jl)
        jl2 = tmp_path / "d.jsonl"
        _write_jsonl(jl2, [_make_tombstone("del-1", "a")])
        ingest_file(store, jl2)
        assert get_lifecycle(store, "a")["current_state"] == "deleted"
        assert get_deletion_audit(store, target_event_id="a")[0]["prior_lifecycle_state"] == "archived"
    finally:
        store.close()


def test_superseded_to_deleted(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        jl = tmp_path / "e.jsonl"
        _write_jsonl(jl, [_make_env("a", lifecycle_status="superseded")])
        ingest_file(store, jl)
        jl2 = tmp_path / "d.jsonl"
        _write_jsonl(jl2, [_make_tombstone("del-1", "a")])
        ingest_file(store, jl2)
        assert get_lifecycle(store, "a")["current_state"] == "deleted"
        assert get_deletion_audit(store, target_event_id="a")[0]["prior_lifecycle_state"] == "superseded"
    finally:
        store.close()


# ---- exclusion from active helpers + FTS -------------------------------------

def test_deleted_excluded_from_active_inspection(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        _write_jsonl(tmp_path / "e.jsonl",
                     [_make_env("a", lifecycle_status="active", project_id="proj-1"),
                      _make_env("b", lifecycle_status="observed", project_id="proj-1")])
        ingest_file(store, tmp_path / "e.jsonl")
        _write_jsonl(tmp_path / "d.jsonl", [_make_tombstone("del-1", "a")])
        ingest_file(store, tmp_path / "d.jsonl")
        assert "a" not in [r["event_id"] for r in find_by_trace_id(store, "tr-a")]
        assert "a" not in list_events_in_scope(store, "project", "proj-1")
        assert "b" in list_events_in_scope(store, "project", "proj-1")
    finally:
        store.close()


def test_deleted_excluded_from_fts(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        _write_jsonl(tmp_path / "e.jsonl",
                     [_make_env("a", lifecycle_status="active", sanitized_content={"text": "deploy service prod"}),
                      _make_env("b", lifecycle_status="observed", sanitized_content={"text": "rollback migration"})])
        ingest_file(store, tmp_path / "e.jsonl")
        _write_jsonl(tmp_path / "d.jsonl", [_make_tombstone("del-1", "a")])
        ingest_file(store, tmp_path / "d.jsonl")
        hit_a = {h["event_id"] for h in search_fts(store, "deploy")}
        hit_b = {h["event_id"] for h in search_fts(store, "rollback")}
        assert "a" not in hit_a
        assert "b" in hit_b
    finally:
        store.close()


def test_admin_helpers_expose_deleted(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        _write_jsonl(tmp_path / "e.jsonl", [_make_env("a", lifecycle_status="active", project_id="proj-1")])
        ingest_file(store, tmp_path / "e.jsonl")
        _write_jsonl(tmp_path / "d.jsonl", [_make_tombstone("del-1", "a", deletion={"reason_code": "user_request"})])
        ingest_file(store, tmp_path / "d.jsonl")
        assert "a" in list_deleted(store)
        assert "a" in list_deleted(store, scope_type="project", scope_id="proj-1")
        assert get_tombstone(store, "del-1") is not None
        assert len(get_deletion_audit(store, target_event_id="a")) == 1
    finally:
        store.close()


def test_historical_metadata_retained_after_delete(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        _write_jsonl(tmp_path / "e.jsonl", [_make_env("a", lifecycle_status="active")])
        ingest_file(store, tmp_path / "e.jsonl")
        from src.storage.ingest import get_trace, get_provenance
        _write_jsonl(tmp_path / "d.jsonl", [_make_tombstone("del-1", "a")])
        ingest_file(store, tmp_path / "d.jsonl")
        assert get_trace(store, "a") is not None
        assert get_provenance(store, "a")
        assert get_lifecycle(store, "a")["current_state"] == "deleted"
    finally:
        store.close()


# ---- retention values projected without invented expiry ----------------------

def test_retention_values_projected_no_expiry(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        _write_jsonl(tmp_path / "e.jsonl", [
            _make_env("a", retention="temporary"),
            _make_env("b", retention="session"),
            _make_env("c", retention="persistent"),
        ])
        ingest_file(store, tmp_path / "e.jsonl")
        from src.storage.ingest import get_trace
        assert get_trace(store, "a")["retention"] == "temporary"
        assert get_trace(store, "b")["retention"] == "session"
        assert get_trace(store, "c")["retention"] == "persistent"
        assert not hasattr(store, "apply_retention_schedule")
    finally:
        store.close()


def test_no_scheduler_exists(tmp_path: pathlib.Path) -> None:
    import src.storage.ingest as ingest_mod
    assert not hasattr(ingest_mod, "apply_retention_schedule")
    assert not hasattr(ingest_mod, "run_retention_expiry")


# ---- rebuild parity -----------------------------------------------------------

def _corpus(tmp_path):
    jl1 = tmp_path / "a.jsonl"
    jl2 = tmp_path / "d.jsonl"
    _write_jsonl(jl1, [
        _make_env("a", lifecycle_status="active", project_id="proj-1", sanitized_content={"text": "deploy service prod"}),
        _make_env("b", lifecycle_status="observed", sanitized_content={"text": "rollback migration"}),
    ])
    _write_jsonl(jl2, [_make_tombstone("del-1", "a", deletion={"reason_code": "user_request"})])
    return jl1, jl2


def test_incremental_vs_rebuild_parity(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        jl1, jl2 = _corpus(tmp_path)
        ingest_file(store, jl1)
        ingest_file(store, jl2)
        rb = _open_store(tmp_path / "rb")
        try:
            rebuild_from_jsonl(rb, [jl1, jl2])
            assert verify_rebuild_parity(store, rb) is True
        finally:
            rb.close()
    finally:
        store.close()


def test_out_of_order_tombstone_rebuild(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        jl1 = tmp_path / "d.jsonl"
        jl2 = tmp_path / "e.jsonl"
        _write_jsonl(jl1, [_make_tombstone("del-1", "a")])
        _write_jsonl(jl2, [_make_env("a", lifecycle_status="active", sanitized_content={"text": "deploy prod"})])
        ingest_file(store, jl1)
        ingest_file(store, jl2)
        assert get_tombstone(store, "del-1")["status"] == "applied"
        assert get_lifecycle(store, "a")["current_state"] == "deleted"
        rb = _open_store(tmp_path / "rb")
        try:
            rebuild_from_jsonl(rb, [jl1, jl2])
            assert get_tombstone(rb, "del-1")["status"] == "applied"
            assert get_lifecycle(rb, "a")["current_state"] == "deleted"
            assert verify_rebuild_parity(store, rb) is True
        finally:
            rb.close()
    finally:
        store.close()


def test_repeated_rebuild_determinism(tmp_path: pathlib.Path) -> None:
    jl1, jl2 = _corpus(tmp_path)
    s1 = _open_store(tmp_path / "s1")
    s2 = _open_store(tmp_path / "s2")
    try:
        rebuild_from_jsonl(s1, [jl1, jl2])
        rebuild_from_jsonl(s2, [jl1, jl2])
        assert verify_rebuild_parity(s1, s2) is True
    finally:
        s1.close()
        s2.close()


# ---- secret scanning ---------------------------------------------------------

def test_secret_scan_covers_tombstones(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        store._conn.execute(
            "INSERT INTO zm_tombstones(tombstone_id,target_event_id,target_trace_id,reason_code,"
            "approved_scope,verifier,evidence_ref,deletion_event_id,current_state,status,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            ("probe", "x", "tr-x", SECRET, None, "deterministic_check", "tr-x", "probe", "deleted", "applied", TS))
        store._conn.commit()
        assert SECRET in scan_sqlite_for_secrets(store, [SECRET])
    finally:
        store.close()


def test_secret_scan_covers_deletion_audit(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        store._conn.execute(
            "INSERT INTO zm_deletion_audit(tombstone_id,target_event_id,target_trace_id,action,"
            "prior_lifecycle_state,reason_code,approved_scope,deletion_event_id,verifier,evidence_ref,"
            "diagnostic_code,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            ("probe", "x", "tr-x", "logical_delete", "active", SECRET, None, "probe",
             "deterministic_check", "tr-x", "", TS))
        store._conn.commit()
        assert SECRET in scan_sqlite_for_secrets(store, [SECRET])
    finally:
        store.close()


def test_secret_absent_normal_ingestion(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        _write_jsonl(tmp_path / "e.jsonl", [_make_env("a", lifecycle_status="active", sanitized_content={"text": "benign observation"})])
        ingest_file(store, tmp_path / "e.jsonl")
        _write_jsonl(tmp_path / "d.jsonl", [_make_tombstone("del-1", "a", deletion={"reason_code": "user_request"})])
        ingest_file(store, tmp_path / "d.jsonl")
        assert scan_sqlite_for_secrets(store, [SECRET]) == []
    finally:
        store.close()


def test_deletion_diagnostics_sanitized(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        _write_jsonl(tmp_path / "e.jsonl", [_make_env("a", lifecycle_status="active")])
        ingest_file(store, tmp_path / "e.jsonl")
        bad = _make_tombstone("del-1", "a", deletion={"reason_code": SECRET})
        jl = tmp_path / "d.jsonl"
        _write_jsonl(jl, [bad])
        rep = ingest_file(store, jl)
        assert SECRET not in str(rep)
        assert SECRET not in str(rep.failures)
        assert SECRET in scan_sqlite_for_secrets(store, [SECRET])
    finally:
        store.close()


def test_no_secret_in_deletion_audit_log(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        _write_jsonl(tmp_path / "e.jsonl", [_make_env("a", lifecycle_status="active", sanitized_content={"text": "benign"})])
        ingest_file(store, tmp_path / "e.jsonl")
        _write_jsonl(tmp_path / "d.jsonl", [_make_tombstone("del-1", "a", deletion={"reason_code": "user_request", "approved_scope": {"project": "proj-1"}})])
        ingest_file(store, tmp_path / "d.jsonl")
        assert scan_sqlite_for_secrets(store, [SECRET]) == []
        audit = get_deletion_audit(store, target_event_id="a")
        assert audit[0]["reason_code"] == "user_request"
    finally:
        store.close()


# ---- JSONL immutability ------------------------------------------------------

def test_jsonl_byte_for_byte_unchanged(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        jl = tmp_path / "e.jsonl"
        _write_jsonl(jl, [
            _make_env("a", lifecycle_status="active"),
            _make_env("b", lifecycle_status="observed"),
            _make_tombstone("del-1", "a"),
        ])
        before = jl.read_bytes()
        ingest_file(store, jl)
        after = jl.read_bytes()
        assert before == after
    finally:
        store.close()


# ---- no real ~/.hermes writes ------------------------------------------------

def test_no_real_hermes_home_writes(tmp_path: pathlib.Path, monkeypatch) -> None:
    # Baseline-aware: capture exact real ~/.hermes BEFORE, run M2.6 ingest into an isolated
    # temp store, then assert the real ~/.hermes is byte-for-directory unchanged. The store path
    # is explicitly under tmp_path (never real ~/.hermes), so M2.6 must not reach the real home.
    real_home = pathlib.Path.home() / ".hermes"
    UNRELATED = {"kanban.db-wal", "kanban.db-shm"}
    baseline = ({p.relative_to(real_home) for p in real_home.rglob("*")} if real_home.exists() else set()) - UNRELATED
    # Explicitly ensure the store never resolves to the real home.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "isolated_hermes_home"))
    store = _open_store(tmp_path)
    try:
        jl = tmp_path / "e.jsonl"
        _write_jsonl(jl, [_make_env("a", lifecycle_status="active"), _make_tombstone("del-1", "a")])
        ingest_file(store, jl)
    finally:
        store.close()
    after = ({p.relative_to(real_home) for p in real_home.rglob("*")} if real_home.exists() else set()) - UNRELATED
    # Baseline-aware isolation: M2.6 must not create any PROJECT-ATTRIBUTABLE file in the real
    # ~/.hermes. The live Hermes desktop app mutates unrelated files concurrently; we only fail
    # on NEW entries matching M2's output signatures (sqlite/jsonl). A real regression is still
    # caught because those are exactly the signatures checked.
    M2_ATTR = (".sqlite", ".sqlite-wal", ".sqlite-shm", ".jsonl", "meta.sqlite")
    new_entries = after - baseline
    attributable = [p for p in new_entries
                   if p.name.endswith(M2_ATTR) or any(seg.endswith(M2_ATTR) for seg in p.parts)]
    assert not attributable, f"M2.6 wrote project-attributable files to real ~/.hermes: {attributable}"


# ---- no LLM / network --------------------------------------------------------

def test_no_llm_or_network_calls(tmp_path: pathlib.Path, monkeypatch) -> None:
    import socket
    monkeypatch.setattr(socket, "socket", lambda *a, **k: (_ for _ in ()).throw(AssertionError("net")))
    store = _open_store(tmp_path)
    try:
        jl = tmp_path / "e.jsonl"
        _write_jsonl(jl, [_make_env("a", lifecycle_status="active"), _make_tombstone("del-1", "a")])
        ingest_file(store, jl)
    finally:
        store.close()


# ---- no M2.7 / M3 behavior ---------------------------------------------------

def test_no_later_m2_tables_or_behavior(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        tables = {r["name"] for r in store._conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "zm_rollback" not in tables
        assert "zm_purge" not in tables
        import src.storage.ingest as ingest_mod
        assert not hasattr(ingest_mod, "apply_retention_schedule")
        assert not hasattr(ingest_mod, "rank_results")
        assert not hasattr(ingest_mod, "retrieve_top_k")
    finally:
        store.close()


def test_no_physical_purge_behavior(tmp_path: pathlib.Path) -> None:
    import src.storage.ingest as ingest_mod
    assert not hasattr(ingest_mod, "physical_purge")
    assert not hasattr(ingest_mod, "purge_canonical_jsonl")
    assert not hasattr(ingest_mod, "compact_jsonl")

