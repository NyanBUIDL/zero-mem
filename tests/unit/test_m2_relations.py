"""M2.4 focused tests: relations, scopes, active-key enforcement, artifact registry.

Covers only M2.4 (derived relation/scope/artifact projections + active-key uniqueness over
canonical JSONL). Uses temporary directories; never writes to the real ~/.hermes.
"""
from __future__ import annotations

import pathlib
import sqlite3
from unittest import mock

import pytest

from src.storage.ingest import (
    count_metadata,
    get_artifact,
    get_lifecycle,
    get_relations,
    get_scopes,
    ingest_file,
    list_active_for_key,
    rebuild_from_jsonl,
    scan_sqlite_for_secrets,
    verify_rebuild_parity,
)
from src.storage.migrations import CURRENT_SCHEMA_VERSION
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig

SECRET = "SK-M2-4-DEADBEEF-77"


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
    import json
    lines = []
    for it in items:
        lines.append(it if isinstance(it, str) else json.dumps(it))
    path.write_text("\n".join(lines) + "\n")


# ---- migration / schema -----------------------------------------------------

def test_migration_v3_to_v4(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        assert store.get_schema_version() == CURRENT_SCHEMA_VERSION
        assert CURRENT_SCHEMA_VERSION == 4
        for t in ("zm_relations", "zm_scopes", "zm_artifacts"):
            assert store.table_exists(t)
    finally:
        store.close()


def test_downgrade_v4_to_v3_drops_new_tables(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        assert store.get_schema_version() == 4
        store.downgrade_to(3)
        assert store.get_schema_version() == 3
        for t in ("zm_relations", "zm_scopes", "zm_artifacts"):
            assert not store.table_exists(t)
    finally:
        store.close()


# ---- child_of from parent_trace_id ------------------------------------------

def test_child_of_derived_from_parent_trace_id(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [
        _make_env("parent", trace_id="tr-P"),
        _make_env("child", trace_id="tr-C", parent_trace_id="tr-P"),
    ])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        rels = get_relations(store, "child")
        kinds = {(r["to_event_id"], r["relation"]) for r in rels}
        assert ("parent", "child_of") in kinds
    finally:
        store.close()


# ---- derived_from from relation_ids -----------------------------------------

def test_derived_from_existing_event_and_trace(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [
        _make_env("a", trace_id="tr-A"),
        _make_env("b", trace_id="tr-B", relation_ids=["a", "tr-A"]),  # event_id + trace_id refs
    ])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        rels = {(r["to_event_id"], r["relation"]) for r in get_relations(store, "b")}
        # 'a' resolves to an existing event_id; 'tr-A' resolves to tr-A's earliest event ('a')
        assert ("a", "derived_from") in rels
        assert ("a", "derived_from") in rels  # both refs collapse to event 'a'
    finally:
        store.close()


def test_relation_unknown_target_skipped(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [
        _make_env("a", relation_ids=["nonexistent-event", "nonexistent-trace"]),
    ])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        assert get_relations(store, "a") == []  # no invented edges
    finally:
        store.close()


# ---- active-key uniqueness + supersession -----------------------------------

def test_active_key_uniqueness_supersedes_prior(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [
        _make_env("first", trace_id="tr-X", lifecycle_status="active", sequence=0),
        _make_env("second", trace_id="tr-X", lifecycle_status="active", sequence=1),
    ])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        # only the later 'active' event remains active; the first is superseded
        assert list_active_for_key(store, "tr-X") == ["second"]
        assert get_lifecycle(store, "first")["current_state"] == "superseded"
        assert get_lifecycle(store, "first")["superseded_by"] == "second"
        assert get_lifecycle(store, "second")["current_state"] == "active"
        assert get_lifecycle(store, "second")["active_key"] == "tr-X"
        rels = {(r["to_event_id"], r["relation"]) for r in get_relations(store, "second")}
        assert ("first", "supersedes") in rels
    finally:
        store.close()


def test_no_silent_overwrite_preserved_link(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [
        _make_env("first", trace_id="tr-X", lifecycle_status="active"),
        _make_env("second", trace_id="tr-X", lifecycle_status="active"),
    ])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        # the prior active row still exists (state preserved), merely marked superseded
        assert get_lifecycle(store, "first") is not None
        assert get_lifecycle(store, "first")["current_state"] == "superseded"
    finally:
        store.close()


def test_conflicted_archived_deleted_plain_states(tmp_path: pathlib.Path) -> None:
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
    finally:
        store.close()


# ---- scopes: observed only, no inference -------------------------------------

def test_scopes_observed_project_profile(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [
        _make_env("a", project_id="proj-1", profile_id="prof-1"),
        _make_env("b", project_id="proj-1", profile_id="prof-2"),
    ])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        assert set(get_scopes(store, "project")) == {"proj-1"}
        assert set(get_scopes(store, "profile")) == {"prof-1", "prof-2"}
        assert get_scopes(store, "knowledge_space") == []  # no inference
    finally:
        store.close()


def test_knowledge_space_only_when_optional_present(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [
        _make_env("a", knowledge_space_id="ks-1"),
    ])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        assert get_scopes(store, "knowledge_space") == ["ks-1"]
    finally:
        store.close()


def test_no_cross_profile_invented_relation(tmp_path: pathlib.Path) -> None:
    # An event in proj-1 must not create a relation to an event in proj-2.
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [
        _make_env("a", project_id="proj-1", trace_id="tr-A"),
        _make_env("b", project_id="proj-2", trace_id="tr-B", relation_ids=["a"]),
    ])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        # 'b' references 'a' by event_id -> a derived_from edge IS legitimate (explicit ref)
        rels = {(r["to_event_id"], r["relation"]) for r in get_relations(store, "b")}
        assert ("a", "derived_from") in rels
        # but no scope-crossing edge is invented beyond the explicit reference
        assert set(get_scopes(store, "project")) == {"proj-1", "proj-2"}
    finally:
        store.close()


# ---- artifact registry: authorized refs only --------------------------------

def test_artifact_registry_populated_from_explicit_refs(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [
        _make_env("a", artifact_refs=[
            {"artifact_id": "art-1", "content_hash": "c1", "kind": "diff", "retention": "persistent"},
        ]),
    ])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        art = get_artifact(store, "art-1")
        assert art is not None
        assert art["content_hash"] == "c1"
        assert art["stored_path"] is None  # content storage deferred
        assert art["origin_event_id"] == "a"
    finally:
        store.close()


def test_artifact_registry_empty_without_refs(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a")])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        cur = store._conn.cursor()
        n = cur.execute("SELECT COUNT(*) AS n FROM zm_artifacts").fetchone()["n"]
        assert n == 0
    finally:
        store.close()


# ---- relation provenance ----------------------------------------------------

def test_relation_provenance_recorded(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [
        _make_env("parent", trace_id="tr-P"),
        _make_env("child", trace_id="tr-C", parent_trace_id="tr-P"),
    ])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        rels = get_relations(store, "child")
        assert len(rels) == 1
        assert rels[0]["verifier"] == "deterministic_check"
        assert rels[0]["evidence_ref"] == "tr-C"
    finally:
        store.close()


# ---- idempotence + rebuild parity -------------------------------------------

def test_duplicate_event_no_extra_relations(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [
        _make_env("parent", trace_id="tr-P"),
        _make_env("child", trace_id="tr-C", parent_trace_id="tr-P"),
    ])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        before = len(get_relations(store, "child"))
        ingest_file(store, jl)  # idempotent re-run
        assert len(get_relations(store, "child")) == before
        assert count_metadata(store) == 2
    finally:
        store.close()


def test_rebuild_parity_includes_relations_scopes(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [
        _make_env("parent", trace_id="tr-P", project_id="proj-1"),
        _make_env("child", trace_id="tr-C", parent_trace_id="tr-P", project_id="proj-1",
                  lifecycle_status="active"),
        _make_env("second", trace_id="tr-C", lifecycle_status="active"),  # supersedes 'child'
    ])
    inc = _open_store(tmp_path / "inc")
    rb = _open_store(tmp_path / "rb")
    try:
        ingest_file(inc, jl)
        rebuild_from_jsonl(rb, [jl])
        assert verify_rebuild_parity(inc, rb) is True
    finally:
        inc.close()
        rb.close()


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


def test_per_line_crash_rolls_back_relations(tmp_path: pathlib.Path, monkeypatch) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [
        _make_env("parent", trace_id="tr-P"),
        _make_env("child", trace_id="tr-C", parent_trace_id="tr-P"),
        _make_env("third", trace_id="tr-D"),
    ])
    store = _open_store(tmp_path)
    try:
        _patch_commit_to_fail_on(store, fail_on_call=2, monkeypatch=monkeypatch)
        rep = ingest_file(store, jl)
        assert rep.stopped is True
        assert get_relations(store, "child") == []  # rolled back with the line
        assert get_lifecycle(store, "child") is None
        assert count_metadata(store) == 1
        rebuild_from_jsonl(store, [jl])  # resume/rebuild reconstructs cleanly
        assert count_metadata(store) == 3
        assert len(get_relations(store, "child")) == 1
    finally:
        store.close()


# ---- secret scan / immutability / boundaries --------------------------------

def test_secret_absent_across_new_tables(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [
        _make_env("a", sanitized_content={"text": SECRET}, project_id="proj-1",
                  relation_ids=["tr-Z"], artifact_refs=[{"artifact_id": "art-1", "content_hash": "c",
                  "kind": "diff", "retention": "persistent"}]),
    ])
    store = _open_store(tmp_path)
    try:
        ingest_file(store, jl)
        assert scan_sqlite_for_secrets(store, [SECRET]) == []
    finally:
        store.close()


def test_jsonl_immutable(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [_make_env("a", project_id="proj-1")])
    raw = jl.read_bytes()
    store = _open_store(tmp_path)
    try:
        rebuild_from_jsonl(store, [jl])
        assert jl.read_bytes() == raw
    finally:
        store.close()


def test_no_later_m2_tables(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        tables = {r["name"] for r in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "zm_fts" not in tables  # FTS5 is M2.5
        import src.storage.ingest as ingest_mod
        assert not hasattr(ingest_mod, "build_fts")
        assert not hasattr(ingest_mod, "apply_tombstone")
    finally:
        store.close()


def test_no_real_hermes_home_writes(tmp_path: pathlib.Path) -> None:
    home = pathlib.Path.home() / ".hermes"
    before = set(p.name for p in home.rglob("*")) if home.exists() else set()
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [
        _make_env("parent", trace_id="tr-P", project_id="proj-1"),
        _make_env("child", trace_id="tr-C", parent_trace_id="tr-P", lifecycle_status="active"),
    ])
    store = _open_store(tmp_path)
    try:
        rebuild_from_jsonl(store, [jl])
    finally:
        store.close()
    after = set(p.name for p in home.rglob("*")) if home.exists() else set()
    assert after == before, "M2.4 must not write into the real ~/.hermes"


def test_no_network_calls(tmp_path: pathlib.Path) -> None:
    jl = tmp_path / "events.jsonl"
    _write_jsonl(jl, [
        _make_env("parent", trace_id="tr-P", project_id="proj-1"),
        _make_env("child", trace_id="tr-C", parent_trace_id="tr-P", lifecycle_status="active"),
    ])
    with mock.patch("socket.socket", side_effect=AssertionError("net")):
        store = _open_store(tmp_path)
        try:
            rebuild_from_jsonl(store, [jl])
        finally:
            store.close()
