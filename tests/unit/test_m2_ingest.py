"""M2.2 focused tests: idempotent JSONL metadata ingestion.

These tests cover only M2.2 (derived SQLite ingestion over canonical JSONL). They
use temporary directories exclusively and never write to the real ~/.hermes.
"""
from __future__ import annotations

import json
import os
import pathlib
import sqlite3
from typing import Any, Optional

import pytest

from src.capture.validation import REQUIRED_FIELDS
from src.storage.migrations import CURRENT_SCHEMA_VERSION
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.storage.ingest import (
    IngestionOutcome,
    IngestionFailure,
    ingest_file,
    get_trace,
    count_metadata,
    get_checkpoint,
    scan_sqlite_for_secrets,
)


SECRET = "SK-CONFIDENTIAL-9f2a7b"  # synthetic, never stored


def _make_env(eid: str = "evt-1", **kw: Any) -> dict:
    base = dict(
        event_id=eid,
        trace_id="tr-1",
        event_type="tool_observation",
        source="pre_tool_call",
        schema_version=1,
        created_at="2026-08-05T00:00:00Z",
        observed_at="2026-08-05T00:00:00Z",
        sequence=0,
        lifecycle_status="observed",
        verification_status="none",
        confidence="medium",
        sensitivity="internal",
        retention="persistent",
        sanitized_content_hash="h-" + eid,
        sanitized_content={"text": "clean"},
        redaction_audit=[],
    )
    base.update(kw)
    return base


def _write_jsonl(path: pathlib.Path, records: list) -> bytes:
    text = "".join(
        (r if isinstance(r, str) else json.dumps(r)) + "\n" for r in records
    )
    path.write_text(text, encoding="utf-8")
    return path.read_bytes()


def _open_store(tmp_path: pathlib.Path) -> SQLiteStore:
    store = SQLiteStore(SQLiteStoreConfig(path=tmp_path / "m2.sqlite"))
    store.ensure_schema()
    return store


def _real_hermes_entries() -> set:
    home = pathlib.Path.home() / ".hermes"
    if not home.exists():
        return set()
    return set(p.relative_to(home).as_posix() for p in home.rglob("*"))


# ---- migration framework ----------------------------------------------------

def test_migration_upgrade_1_to_current(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        assert store.get_schema_version() == CURRENT_SCHEMA_VERSION
        assert store.table_exists("zm_meta")
        assert store.table_exists("zm_ingest_checkpoint")
        assert store.table_exists("zm_ingest_log")
    finally:
        store.close()


def test_migration_downgrade_2_to_1(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        assert store.get_schema_version() == CURRENT_SCHEMA_VERSION
        store.downgrade_to(1)
        assert store.get_schema_version() == 1
        assert not store.table_exists("zm_ingest_checkpoint")
        assert not store.table_exists("zm_ingest_log")
        assert store.table_exists("zm_meta")  # v1 table preserved
    finally:
        store.close()


def test_reopen_upgraded_db_is_idempotent(tmp_path: pathlib.Path) -> None:
    s1 = _open_store(tmp_path)
    s1.close()
    s2 = _open_store(tmp_path)
    try:
        assert s2.get_schema_version() == CURRENT_SCHEMA_VERSION
        assert s2.table_exists("zm_ingest_checkpoint")
    finally:
        s2.close()


# ---- core ingestion ----------------------------------------------------------

def test_valid_new_event_ingestion(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a")])
    store = _open_store(tmp_path)
    try:
        rep = ingest_file(store, jl)
        assert rep.counts[IngestionOutcome.NEW_EVENT.value] == 1
        assert count_metadata(store) == 1
        assert get_trace(store, "a") is not None
        assert not rep.stopped
    finally:
        store.close()


def test_deterministic_file_order_ingestion(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    envs = [_make_env(f"e{i}", sequence=i) for i in range(5)]
    _write_jsonl(jl, envs)
    store = _open_store(tmp_path)
    try:
        rep = ingest_file(store, jl)
        assert rep.counts[IngestionOutcome.NEW_EVENT.value] == 5
        for i in range(5):
            assert get_trace(store, f"e{i}") is not None
    finally:
        store.close()


def test_envelope_validation_rejects_invalid(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    bad = _make_env("a")
    del bad["trace_id"]  # required field missing
    _write_jsonl(jl, [bad])
    store = _open_store(tmp_path)
    try:
        rep = ingest_file(store, jl)
        assert rep.counts[IngestionOutcome.INVALID_RECORD.value] == 1
        assert count_metadata(store) == 0
    finally:
        store.close()


def test_approved_metadata_projection(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a", project_id="p1", profile_id="u1", session_id="s1")])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        row = get_trace(store, "a")
        assert row["event_id"] == "a"
        assert row["trace_id"] == "tr-1"
        assert row["project_id"] == "p1"
        assert row["profile_id"] == "u1"
        assert row["session_id"] == "s1"
        assert row["content_hash"] == "h-a"
        assert "sanitized_content" not in row
    finally:
        store.close()


def test_sanitized_content_blob_excluded(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a")])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        cols = store._conn.execute("PRAGMA table_info(zm_meta)").fetchall()
        names = {c["name"] for c in cols}
        assert "sanitized_content" not in names
        assert "content_hash" in names
    finally:
        store.close()


def test_duplicate_event_id(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a"), _make_env("a")])
    store = _open_store(tmp_path)
    try:
        rep = ingest_file(store, jl)
        assert rep.counts[IngestionOutcome.NEW_EVENT.value] == 1
        assert rep.counts[IngestionOutcome.DUPLICATE_EVENT_ID.value] == 1
        assert count_metadata(store) == 1
    finally:
        store.close()


def test_duplicate_content_hash(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a", sanitized_content_hash="H"),
                       _make_env("b", sanitized_content_hash="H")])
    store = _open_store(tmp_path)
    try:
        rep = ingest_file(store, jl)
        assert rep.counts[IngestionOutcome.NEW_EVENT.value] == 1
        assert rep.counts[IngestionOutcome.DUPLICATE_CONTENT_HASH.value] == 1
        assert count_metadata(store) == 1  # second not inserted
    finally:
        store.close()


def test_event_id_content_conflict_first_write_wins(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a", sanitized_content_hash="H1"),
                       _make_env("a", sanitized_content_hash="H2")])
    store = _open_store(tmp_path)
    try:
        rep = ingest_file(store, jl)
        assert rep.counts[IngestionOutcome.NEW_EVENT.value] == 1
        assert rep.counts[IngestionOutcome.EVENT_ID_CONTENT_CONFLICT.value] == 1
        row = get_trace(store, "a")
        assert row["content_hash"] == "H1"  # original kept
        assert count_metadata(store) == 1
    finally:
        store.close()


def test_idempotent_rerun_no_duplicates(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a"), _make_env("b"), _make_env("c")])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        assert count_metadata(store) == 3
        ingest_file(store, jl)  # re-run
        assert count_metadata(store) == 3
    finally:
        store.close()


def test_no_invented_identity(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a")])  # no project_id/profile_id/session_id
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        row = get_trace(store, "a")
        assert row["project_id"] is None
        assert row["profile_id"] is None
        assert row["session_id"] is None
    finally:
        store.close()


# ---- per-record transactions / checkpoint -----------------------------------

def _patch_commit_to_fail_on(store: SQLiteStore, fail_on_call: int, monkeypatch):
    import src.storage.ingest as ingest_mod
    calls = {"n": 0}
    original = ingest_mod._commit

    def fake_commit(conn):
        calls["n"] += 1
        if calls["n"] == fail_on_call:
            raise sqlite3.OperationalError("simulated commit failure")
        return original(conn)

    monkeypatch.setattr(ingest_mod, "_commit", fake_commit)


def test_per_record_transaction_isolation(tmp_path: pathlib.Path, monkeypatch) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a"), _make_env("b"), _make_env("c")])
    store = _open_store(tmp_path)
    try:
        _patch_commit_to_fail_on(store, fail_on_call=2, monkeypatch=monkeypatch)  # line b fails
        rep = ingest_file(store, jl)
        assert rep.stopped
        assert rep.counts[IngestionOutcome.TRANSACTION_FAILED.value] == 1
        # line a committed; line b rolled back; line c never reached (halt)
        assert count_metadata(store) == 1
        assert get_trace(store, "a") is not None
        assert get_trace(store, "b") is None
    finally:
        store.close()


def test_checkpoint_advances_for_committed_outcomes(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a"), _make_env("b")])
    store = _open_store(tmp_path)
    try:
        rep = ingest_file(store, jl)
        cp = get_checkpoint(store, jl.name)
        assert cp is not None
        assert cp["last_line_number"] == 2
        assert rep.counts[IngestionOutcome.NEW_EVENT.value] == 2
    finally:
        store.close()


def test_checkpoint_does_not_advance_on_transaction_failure(tmp_path: pathlib.Path, monkeypatch) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a"), _make_env("b"), _make_env("c")])
    store = _open_store(tmp_path)
    try:
        _patch_commit_to_fail_on(store, fail_on_call=2, monkeypatch=monkeypatch)
        rep = ingest_file(store, jl)
        cp = get_checkpoint(store, jl.name)
        assert cp["last_line_number"] == 1  # only line a advanced
        assert rep.counts[IngestionOutcome.TRANSACTION_FAILED.value] == 1
    finally:
        store.close()


def test_crash_before_commit_resume_retries(tmp_path: pathlib.Path, monkeypatch) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a"), _make_env("b"), _make_env("c")])
    store = _open_store(tmp_path)
    try:
        # Simulate crash-before-commit on the final line: its commit fails, no advance.
        _patch_commit_to_fail_on(store, fail_on_call=3, monkeypatch=monkeypatch)
        rep = ingest_file(store, jl)
        assert rep.counts[IngestionOutcome.TRANSACTION_FAILED.value] == 1
        assert count_metadata(store) == 2
        cp = get_checkpoint(store, jl.name)
        assert cp["last_line_number"] == 2
    finally:
        store.close()
    # Resume with a healthy store.
    store2 = _open_store(tmp_path)
    try:
        rep2 = ingest_file(store2, jl)
        assert not rep2.stopped
        assert count_metadata(store2) == 3  # line c now committed
        assert get_trace(store2, "c") is not None
    finally:
        store2.close()


def test_crash_after_commit_resume_idempotent(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a"), _make_env("b")])
    store = _open_store(tmp_path)
    try:
        rep = ingest_file(store, jl)
        assert rep.counts[IngestionOutcome.NEW_EVENT.value] == 2
        cp = get_checkpoint(store, jl.name)
        assert cp["last_line_number"] == 2
    finally:
        store.close()
    # Resume: checkpoint already reflects committed lines; nothing new ingested.
    store2 = _open_store(tmp_path)
    try:
        rep2 = ingest_file(store2, jl)
        assert rep2.counts[IngestionOutcome.NEW_EVENT.value] == 0
        assert count_metadata(store2) == 2
    finally:
        store2.close()


# ---- malformed / invalid lines ---------------------------------------------

def test_malformed_json_handling(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a"), "not json {{{", _make_env("b")])
    store = _open_store(tmp_path)
    try:
        rep = ingest_file(store, jl)
        assert rep.counts[IngestionOutcome.INVALID_RECORD.value] == 1
        assert rep.counts[IngestionOutcome.NEW_EVENT.value] == 2
    finally:
        store.close()


def test_invalid_envelope_handling(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    bad = _make_env("a")
    del bad["lifecycle_status"]
    _write_jsonl(jl, [_make_env("a"), bad, _make_env("b")])
    store = _open_store(tmp_path)
    try:
        rep = ingest_file(store, jl)
        assert rep.counts[IngestionOutcome.INVALID_RECORD.value] == 1
        assert rep.counts[IngestionOutcome.NEW_EVENT.value] == 2
    finally:
        store.close()


def test_continuation_after_invalid_lines(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a"), "garbage", _make_env("b"), "more garbage",
                       _make_env("c")])
    store = _open_store(tmp_path)
    try:
        rep = ingest_file(store, jl)
        assert rep.counts[IngestionOutcome.NEW_EVENT.value] == 3
        assert rep.counts[IngestionOutcome.INVALID_RECORD.value] == 2
        for e in ("a", "b", "c"):
            assert get_trace(store, e) is not None
    finally:
        store.close()


def test_sanitized_failure_records_no_payload(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, ["{not valid json with secret " + SECRET + "}"])
    store = _open_store(tmp_path)
    try:
        rep = ingest_file(store, jl)
        # Sanitized failure is in both the in-memory report and the committed log.
        assert len(rep.failures) == 1
        f: IngestionFailure = rep.failures[0]
        assert isinstance(f, IngestionFailure)
        assert f.failure_class == "invalid_record"
        assert f.diagnostic_code == "json_unparseable"
        assert SECRET not in f.source_id
        assert SECRET not in f.failure_class
        assert SECRET not in f.diagnostic_code
        assert SECRET not in str(f)
        # Committed zm_ingest_log row is also sanitized (no replayable input).
        rows = store._conn.execute(
            "SELECT outcome, diagnostic_code, event_id, content_hash "
            "FROM zm_ingest_log"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["outcome"] == "invalid_record"
        assert rows[0]["diagnostic_code"] == "json_unparseable"
        blob = " ".join("" if rows[0][c] is None else str(rows[0][c]) for c in ("event_id", "content_hash"))
        assert SECRET not in blob
    finally:
        store.close()


# ---- append-safe source integrity ------------------------------------------

def test_normal_append_growth_accepted(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a"), _make_env("b")])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        assert count_metadata(store) == 2
        with jl.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_make_env("c")) + "\n")
            fh.write(json.dumps(_make_env("d")) + "\n")
        rep = ingest_file(store, jl)
        assert not rep.stopped
        assert rep.counts[IngestionOutcome.NEW_EVENT.value] == 2
        assert count_metadata(store) == 4
    finally:
        store.close()


def test_mtime_only_change_accepted(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a")])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        past = (jl.stat().st_mtime_ns - 10_000_000_000)
        os.utime(jl, ns=(past, past))
        rep = ingest_file(store, jl)
        assert not rep.stopped
        assert rep.counts[IngestionOutcome.NEW_EVENT.value] == 0
        assert count_metadata(store) == 1
    finally:
        store.close()


def test_consumed_prefix_modification_rejected(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a"), _make_env("b")])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        lines = jl.read_text(encoding="utf-8").splitlines(keepends=True)
        lines[0] = lines[0].replace("tool_observation", "system_event")
        jl.write_text("".join(lines), encoding="utf-8")
        rep = ingest_file(store, jl)
        assert rep.stopped
        assert rep.counts[IngestionOutcome.SOURCE_CHANGED.value] == 1
    finally:
        store.close()


def test_consumed_line_reordering_rejected(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a"), _make_env("b")])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        lines = jl.read_text(encoding="utf-8").splitlines(keepends=True)
        lines[0], lines[1] = lines[1], lines[0]
        jl.write_text("".join(lines), encoding="utf-8")
        rep = ingest_file(store, jl)
        assert rep.stopped
        assert rep.counts[IngestionOutcome.SOURCE_CHANGED.value] == 1
    finally:
        store.close()


def test_consumed_prefix_replacement_rejected(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a"), _make_env("b")])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        jl.write_text(json.dumps(_make_env("x")) + "\n" + json.dumps(_make_env("y")) + "\n",
                        encoding="utf-8")
        rep = ingest_file(store, jl)
        assert rep.stopped
        assert rep.counts[IngestionOutcome.SOURCE_CHANGED.value] == 1
    finally:
        store.close()


def test_truncation_below_checkpoint_rejected(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a"), _make_env("b")])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        jl.write_text(json.dumps(_make_env("a")) + "\n", encoding="utf-8")
        rep = ingest_file(store, jl)
        assert rep.stopped
        assert rep.counts[IngestionOutcome.SOURCE_CHANGED.value] == 1
    finally:
        store.close()


def test_trailing_partial_line_is_truncation_guard(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a")])
    with jl.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(_make_env("b")))  # no trailing newline (partial)
    store = _open_store(tmp_path)
    try:
        rep = ingest_file(store, jl)
        assert rep.counts[IngestionOutcome.NEW_EVENT.value] == 1
        assert rep.counts[IngestionOutcome.INVALID_RECORD.value] == 1
        cp = get_checkpoint(store, jl.name)
        assert cp["last_line_number"] == 1  # checkpoint stays before partial line
    finally:
        store.close()


# ---- immutability / secrets / helpers ---------------------------------------

def test_jsonl_byte_for_byte_unchanged(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    original = _write_jsonl(jl, [_make_env("a"), _make_env("b", sanitized_content_hash="H2")])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        assert jl.read_bytes() == original
    finally:
        store.close()


def test_source_input_dict_not_mutated(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    env = _make_env("a", sanitized_content={"text": SECRET})
    _write_jsonl(jl, [env])
    snapshot = json.dumps(env, sort_keys=True)
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        assert json.dumps(env, sort_keys=True) == snapshot
    finally:
        store.close()


def test_secret_absent_from_sqlite_and_outputs(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a", sanitized_content={"text": SECRET})])
    store = _open_store(tmp_path)
    try:
        rep = ingest_file(store, jl)
        found = scan_sqlite_for_secrets(store, [SECRET])
        assert found == [], f"secret leaked into SQLite: {found}"
        assert SECRET not in str(rep)
        assert SECRET not in str(rep.failures)
    finally:
        store.close()


def test_minimal_inspection_helpers(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a", project_id="p1")])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        assert count_metadata(store) == 1
        row = get_trace(store, "a")
        assert row["project_id"] == "p1"
        cp = get_checkpoint(store, jl.name)
        assert cp["last_line_number"] == 1
        assert get_trace(store, "missing") is None
        assert get_checkpoint(store, "nope") is None
    finally:
        store.close()


def test_no_real_hermes_home_writes(tmp_path: pathlib.Path) -> None:
    before = _real_hermes_entries()
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a")])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
    finally:
        store.close()
    after = _real_hermes_entries()
    assert before == after, "ingestion wrote outside the temporary directory"


def test_no_later_m2_behavior(tmp_path: pathlib.Path) -> None:
    # zm_relations/zm_scopes/zm_artifacts ARE created by M2.4; only FTS5 (zm_fts) is strictly later
    store = _open_store(tmp_path)
    try:
        for t in ("zm_fts",):
            assert not store.table_exists(t), f"unexpected later-M2 table {t}"
        for meth in ("rebuild_from_jsonl", "replay", "dead_letter"):
            assert not hasattr(store, meth)
    finally:
        store.close()


def test_no_llm_or_network_calls(tmp_path: pathlib.Path, monkeypatch) -> None:
    import socket
    calls = {"n": 0}

    def fake_socket(*a, **k):
        calls["n"] += 1
        raise RuntimeError("network call blocked in M2.2 test")

    monkeypatch.setattr(socket, "socket", fake_socket)
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a")])
    store = _open_store(tmp_path)
    try:
        rep = ingest_file(store, jl)
        assert rep.counts[IngestionOutcome.NEW_EVENT.value] == 1
    finally:
        store.close()
    assert calls["n"] == 0
    for mod in ("openai", "anthropic"):
        assert mod not in getattr(__import__("sys"), "modules", {}), f"{mod} imported"
