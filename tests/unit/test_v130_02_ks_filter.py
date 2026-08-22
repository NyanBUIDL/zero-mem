"""V130-02 — Knowledge-space filter: zm_meta.knowledge_space_id (contract-first test frame).

Contract (docs/v1.3.0/plans/V130-02-SPEC.md):
- Migration 11: ALTER TABLE zm_meta ADD COLUMN knowledge_space_id TEXT + index; down drops both.
- Ingest điền cột từ envelope knowledge_space_id; thiếu -> NULL.
- NULL = unscoped = visible theo global-default-read (D-2026-08-22-03); bị loại khi filter ks cụ thể.
- search_text + structured query enforce exact-equality ks filter qua _build_where.
- Rebuild từ JSONL tái tạo đúng cột.

RED until V130-02 implemented.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.storage.ingest import ingest_file
from tests.unit.test_m3_query import (
    TS,
    _checkpoint_and_close,
    _make_env,
    _open_store,
    _write_jsonl,
)

import src.retrieval as r


def _corpus(tmp_path: Path, with_ks: bool = True) -> Path:
    over_a = {"knowledge_space_id": "ks-a"} if with_ks else {}
    items = [
        _make_env("ka-1", sanitized_content={"text": "quantum notes shared"}, **over_a),
        _make_env("kb-1", sanitized_content={"text": "quantum notes private"},
                  **({"knowledge_space_id": "ks-b"} if with_ks else {})),
        _make_env("nk-1", sanitized_content={"text": "quantum notes unscoped"}),
    ]
    jl = tmp_path / "ks.jsonl"
    _write_jsonl(jl, items)
    store = _open_store(tmp_path, "m.sqlite")
    ingest_file(store, jl)
    _checkpoint_and_close(store)
    return jl


@pytest.fixture
def ro(tmp_path):
    from src.retrieval.db import open_readonly

    _corpus(tmp_path)
    return open_readonly(tmp_path / "m.sqlite")


# --- migration ---------------------------------------------------------------

def test_migration_11_adds_column_and_index(tmp_path):
    store = _open_store(tmp_path, "mig.sqlite")
    cols = {row[1] for row in store._conn.execute("PRAGMA table_info(zm_meta)")}
    assert "knowledge_space_id" in cols
    names = {row["name"] for row in store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='zm_meta'"
    ).fetchall()}
    assert any("knowledge_space_id" in n or n == "idx_zm_meta_ks" for n in names)


def test_migration_11_ledger_version(tmp_path):
    store = _open_store(tmp_path, "ledger.sqlite")
    versions = [row[0] for row in store._conn.execute("SELECT version FROM zm_migrations")]
    assert 11 in versions


# --- ingest ------------------------------------------------------------------

def test_ingest_fills_ks_column(tmp_path):
    _corpus(tmp_path)
    import sqlite3
    conn = sqlite3.connect(tmp_path / "m.sqlite")
    rows = dict(conn.execute("SELECT event_id, knowledge_space_id FROM zm_meta").fetchall())
    conn.close()
    assert rows["ka-1"] == "ks-a"
    assert rows["kb-1"] == "ks-b"
    assert rows["nk-1"] is None


# --- query enforcement -------------------------------------------------------

def test_search_with_ks_filter_excludes_other_and_null(ro):
    req = r.QueryRequest(knowledge_space_id="ks-a")
    res = r.search_text(ro, "quantum", req=req)
    ids = {h.event_id for h in res.results}
    assert "kb-1" not in ids and "nk-1" not in ids
    assert "ka-1" in ids


def test_unfiltered_search_shows_null_ks_events(ro):
    # D-2026-08-22-03: NULL = unscoped = visible under global-default-read
    res = r.search_text(ro, "unscoped")
    assert {h.event_id for h in res.results} == {"nk-1"}


def test_structured_query_enforces_ks_filter(ro):
    res = r.query_events(ro, r.QueryRequest(knowledge_space_id="ks-b"))
    ids = {h.event_id for h in res.items}
    assert ids == {"kb-1"}


def test_no_leak_between_ks_scopes(ro):
    a = r.search_text(ro, "quantum", req=r.QueryRequest(knowledge_space_id="ks-a"))
    b = r.search_text(ro, "quantum", req=r.QueryRequest(knowledge_space_id="ks-b"))
    ids_a = {h.event_id for h in a.results}
    ids_b = {h.event_id for h in b.results}
    assert ids_a and ids_b
    assert not (ids_a & ids_b)


# --- rebuild -----------------------------------------------------------------

def test_rebuild_recreates_ks_column(tmp_path):
    jl = _corpus(tmp_path, with_ks=True)
    from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
    from src.storage.ingest import rebuild_from_jsonl
    store2 = SQLiteStore(SQLiteStoreConfig(path=tmp_path / "rebuild.sqlite"))
    store2.ensure_schema()
    rebuild_from_jsonl(store2, [jl])
    _checkpoint_and_close(store2)
    import sqlite3
    conn = sqlite3.connect(tmp_path / "rebuild.sqlite")
    rows = dict(conn.execute("SELECT event_id, knowledge_space_id FROM zm_meta").fetchall())
    conn.close()
    assert rows["ka-1"] == "ks-a" and rows["kb-1"] == "ks-b"
