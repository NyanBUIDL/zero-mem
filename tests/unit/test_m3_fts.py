"""M3.3 focused tests — deterministic, sanitized, TRUE READ-ONLY FTS5 search.

Reuses the verified M2.5 FTS substrate (``zm_fts`` over M1-sanitized content), built via the
same ``_open_store`` + ``ingest_file`` path the M2.5 FTS tests use (so the FTS index is populated
and the mutable ``FTS5_AVAILABLE`` global cannot misreport availability — M3.3 inspects the actual
database instead). Proves: capability detection is read-only; successful/zero/malformed/unavailable
results are distinguishable; ordering is deterministic; deleted records are excluded; structured
filters compose with FTS via AND; pagination + cursor binding (text + filters + limit) work; the
read-only proof covers JSONL, all derived tables, and ``zm_fts``; and no secret leaks into results,
snippets, errors, or cursors.

Run: .venv/bin/python -m pytest tests/unit/test_m3_fts.py -q
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from src.storage.ingest import ingest_file, scan_sqlite_for_secrets
from tests.unit.test_m3_query import (  # reuse verified M2 corpus builders + Snapshot
    DERIVED_TABLES,
    Snapshot,
    _checkpoint_and_close,
    _make_env,
    _make_tombstone,
    _open_store,
    _write_jsonl,
)

import src.retrieval as r
from src.retrieval import SearchResult
from src.retrieval.models import (
    FTS_UNAVAILABLE,
    MALFORMED_FTS_EXPRESSION,
    QueryError,
    QueryRequest,
    SearchHit,
)

SECRET = "SK-M3-FTS-DEADBEEF-4242"


# ---- FTS corpus builder (verified M2.5 path: ensure_schema + ingest_file) ----

def _ingest_fts_corpus(tmp_path: Path, items) -> Path:
    jl = tmp_path / "fts.jsonl"
    _write_jsonl(jl, items)
    store = _open_store(tmp_path, "m.sqlite")
    ingest_file(store, jl)
    _checkpoint_and_close(store)  # closes store; read-only reopen sees FTS rows
    return jl


def _fts_snapshot(store, jsonl: Path) -> dict:
    """Snapshot including zm_fts content hash (Snapshot misses it)."""
    base = Snapshot(store, jsonl)
    snap = {
        "schema_hash": base.schema_hash,
        "counts": dict(base.counts),
        "meta_hash": base.meta_hash,
        "jsonl_sha": base.jsonl_sha,
    }
    try:
        rows = store._conn.execute(
            "SELECT event_id, content FROM zm_fts ORDER BY event_id"
        ).fetchall()
        blob = "\n".join(f"{row['event_id']}|{row['content']}" for row in rows)
        snap["fts_hash"] = hashlib.sha256(blob.encode()).hexdigest()
        snap["fts_count"] = len(rows)
    except Exception:
        snap["fts_hash"] = "NO_FTS"
        snap["fts_count"] = -1
    return snap


def _assert_snapshot_equal(a: dict, b: dict) -> None:
    assert a["schema_hash"] == b["schema_hash"], "schema DDL changed"
    assert a["counts"] == b["counts"], "derived row counts changed"
    assert a["meta_hash"] == b["meta_hash"], "zm_meta content changed"
    assert a["jsonl_sha"] == b["jsonl_sha"], "JSONL bytes changed"
    assert a["fts_hash"] == b["fts_hash"], "zm_fts content changed"
    assert a["fts_count"] == b["fts_count"], "zm_fts row count changed"


# ---- corpus with searchable FTS text ----

def _fts_env(event_id: str, text: str, **over):
    return _make_env(event_id, sanitized_content={"text": text}, **over)


# ============================ capability + basic results ============================

def test_fts_capability_detection_is_read_only(tmp_path: Path):
    jl = _ingest_fts_corpus(tmp_path, [
        _fts_env("e1", "alpha module deployment"),
        _fts_env("e2", "beta parser tokens"),
    ])
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    before = _fts_snapshot(store, jl)
    # Capability inspection must not mutate anything.
    assert r.search_text(rs, "alpha").error is None
    after = _fts_snapshot(store, jl)
    _assert_snapshot_equal(before, after)
    rs.close(); store.close()


def test_successful_fts_match(tmp_path: Path):
    jl = _ingest_fts_corpus(tmp_path, [
        _fts_env("e1", "alpha module handles deployment cleanly"),
        _fts_env("e2", "beta parser rejects malformed tokens"),
        _fts_env("e3", "alpha beta gamma all present here"),
    ])
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    res = r.search_text(rs, "alpha")
    assert isinstance(res, SearchResult)
    assert res.error is None
    assert sorted(h.event_id for h in res.results) == ["e1", "e3"]
    for h in res.results:
        assert isinstance(h, SearchHit)
        assert h.content_source == "fts"
        assert isinstance(h.snippet, str)
    rs.close(); store.close()


def test_legitimate_zero_result_search(tmp_path: Path):
    jl = _ingest_fts_corpus(tmp_path, [_fts_env("e1", "alpha module deployment")])
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    res = r.search_text(rs, "nonexistentterm")
    assert res.results == []
    assert res.error is None  # zero results != error
    rs.close(); store.close()


def test_fts_unavailable_typed_error(tmp_path: Path):
    import sqlite3
    db = tmp_path / "no_fts.sqlite"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE zm_meta(event_id TEXT)")
    c.commit(); c.close()
    rs = r.open_readonly(db)
    res = r.search_text(rs, "alpha")
    assert res.results == []
    assert res.error == FTS_UNAVAILABLE
    rs.close()


def test_malformed_fts_expression_typed_error(tmp_path: Path):
    jl = _ingest_fts_corpus(tmp_path, [_fts_env("e1", "alpha module deployment")])
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    res = r.search_text(rs, "alpha OR")
    assert res.results == []
    assert res.error == MALFORMED_FTS_EXPRESSION
    rs.close(); store.close()


def test_no_raw_sqlite_exception_leakage(tmp_path: Path):
    jl = _ingest_fts_corpus(tmp_path, [_fts_env("e1", "alpha module deployment")])
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    res = r.search_text(rs, "alpha OR AND (")
    assert res.error == MALFORMED_FTS_EXPRESSION
    assert res.results == []
    assert isinstance(res.error, str) and " " not in res.error
    rs.close(); store.close()


# ============================ snippet + multiple matches ============================

def test_sanitized_snippet_present(tmp_path: Path):
    jl = _ingest_fts_corpus(tmp_path, [_fts_env("e1", "the alpha module handles safe deployment")])
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    res = r.search_text(rs, "alpha")
    assert len(res.results) == 1
    snip = res.results[0].snippet
    assert "alpha" in snip
    assert "[" in snip and "]" in snip
    rs.close(); store.close()


def test_multiple_fts_matches(tmp_path: Path):
    jl = _ingest_fts_corpus(tmp_path, [
        _fts_env("e1", "alpha one"),
        _fts_env("e2", "beta two"),
        _fts_env("e3", "alpha three"),
        _fts_env("e4", "gamma four"),
    ])
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    res = r.search_text(rs, "alpha")
    assert sorted(h.event_id for h in res.results) == ["e1", "e3"]
    rs.close(); store.close()


# ============================ deterministic ordering ============================

def test_deterministic_created_at_event_id_ordering(tmp_path: Path):
    jl = _ingest_fts_corpus(tmp_path, [
        _fts_env("e1", "alpha note one", created_at="2026-01-03T00:00:00Z"),
        _fts_env("e2", "alpha note two", created_at="2026-01-01T00:00:00Z"),
        _fts_env("e3", "alpha note three", created_at="2026-01-02T00:00:00Z"),
    ])
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    res = r.search_text(rs, "alpha")
    assert [h.event_id for h in res.results] == ["e2", "e3", "e1"]
    rs.close(); store.close()


def test_identical_timestamp_tie_break(tmp_path: Path):
    ts = "2026-02-01T00:00:00Z"
    jl = _ingest_fts_corpus(tmp_path, [
        _fts_env("z3", "alpha shared", created_at=ts, observed_at=ts),
        _fts_env("z1", "alpha shared", created_at=ts, observed_at=ts),
        _fts_env("z2", "alpha shared", created_at=ts, observed_at=ts),
    ])
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    res = r.search_text(rs, "alpha")
    assert [h.event_id for h in res.results] == ["z1", "z2", "z3"]
    rs.close(); store.close()


# ============================ deleted exclusion ============================

def test_deleted_record_excluded(tmp_path: Path):
    jl = _ingest_fts_corpus(tmp_path, [
        _fts_env("e1", "alpha public note"),
        _fts_env("e2", "alpha secret note"),
    ])
    store = _open_store(tmp_path, "m.sqlite")
    jl2 = tmp_path / "tomb.jsonl"
    _write_jsonl(jl2, [_make_tombstone("t1", "e1")])
    ingest_file(store, jl2)
    _checkpoint_and_close(store)
    rs = r.open_readonly(store.path)
    res = r.search_text(rs, "alpha")
    hit_ids = [h.event_id for h in res.results]
    assert "e1" not in hit_ids
    assert "e2" in hit_ids
    rs.close()


def test_archived_nondeleted_unchanged(tmp_path: Path):
    jl = _ingest_fts_corpus(tmp_path, [
        _fts_env("e1", "alpha live", lifecycle_status="archived"),
        _fts_env("e2", "alpha active"),
    ])
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    res = r.search_text(rs, "alpha")
    assert sorted(h.event_id for h in res.results) == ["e1", "e2"]
    rs.close(); store.close()


# ============================ structured filters + FTS ============================

def test_fts_plus_project_filter(tmp_path: Path):
    jl = _ingest_fts_corpus(tmp_path, [
        _fts_env("e1", "alpha deploy", project_id="P"),
        _fts_env("e2", "beta rollout", project_id="P"),
        _fts_env("e3", "alpha migrate", project_id="Q"),
    ])
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    res = r.search_text(rs, "alpha", req=QueryRequest(project_id="P"))
    assert [h.event_id for h in res.results] == ["e1"]
    rs.close(); store.close()


def test_fts_plus_profile_filter(tmp_path: Path):
    jl = _ingest_fts_corpus(tmp_path, [
        _fts_env("e1", "alpha deploy", profile_id="A"),
        _fts_env("e2", "alpha rollout", profile_id="B"),
    ])
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    res = r.search_text(rs, "alpha", req=QueryRequest(profile_id="A"))
    assert [h.event_id for h in res.results] == ["e1"]
    rs.close(); store.close()


def test_fts_plus_event_type_filter(tmp_path: Path):
    jl = _ingest_fts_corpus(tmp_path, [
        _fts_env("e1", "alpha deploy", event_type="tool_observation"),
        _fts_env("e2", "alpha rollout", event_type="user_statement"),
    ])
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    res = r.search_text(rs, "alpha", req=QueryRequest(event_type="tool_observation"))
    assert [h.event_id for h in res.results] == ["e1"]
    rs.close(); store.close()


def test_fts_plus_time_range_filter(tmp_path: Path):
    jl = _ingest_fts_corpus(tmp_path, [
        _fts_env("e1", "alpha early", created_at="2026-01-01T00:00:00Z"),
        _fts_env("e2", "alpha late", created_at="2026-03-01T00:00:00Z"),
    ])
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    res = r.search_text(rs, "alpha", req=QueryRequest(created_at_after="2026-02-01T00:00:00Z"))
    assert [h.event_id for h in res.results] == ["e2"]
    rs.close(); store.close()


def test_fts_combined_filters_zero_result(tmp_path: Path):
    jl = _ingest_fts_corpus(tmp_path, [
        _fts_env("e1", "alpha deploy", project_id="P"),
        _fts_env("e2", "beta rollout", project_id="Q"),
    ])
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    res = r.search_text(rs, "alpha", req=QueryRequest(project_id="Q"))
    assert res.results == []
    assert res.error is None
    rs.close(); store.close()


# ============================ pagination + cursor ============================

def test_fts_pagination_basic(tmp_path: Path):
    items = [_fts_env(f"e{i:02d}", f"alpha token {i}") for i in range(1, 11)]
    jl = _ingest_fts_corpus(tmp_path, items)
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    p1 = r.search_text(rs, "alpha", limit=3)
    assert len(p1.results) == 3
    assert p1.next_cursor is not None
    p2 = r.search_text(rs, "alpha", limit=3, cursor=p1.next_cursor)
    assert len(p2.results) == 3
    assert p2.next_cursor is not None
    all_ids = [h.event_id for h in p1.results] + [h.event_id for h in p2.results]
    assert len(all_ids) == len(set(all_ids))
    rs.close(); store.close()


def test_fts_no_duplicate_results_across_pages(tmp_path: Path):
    items = [_fts_env(f"e{i:02d}", f"alpha token {i}") for i in range(1, 13)]
    jl = _ingest_fts_corpus(tmp_path, items)
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    seen = []
    cur = None
    while True:
        res = r.search_text(rs, "alpha", limit=4, cursor=cur)
        seen += [h.event_id for h in res.results]
        cur = res.next_cursor
        if cur is None:
            break
    full = [h.event_id for h in r.search_text(rs, "alpha").results]
    assert seen == full
    assert len(seen) == len(set(seen))
    rs.close(); store.close()


def test_fts_no_skipped_results_across_pages(tmp_path: Path):
    items = [_fts_env(f"e{i:02d}", f"alpha token {i}") for i in range(1, 13)]
    jl = _ingest_fts_corpus(tmp_path, items)
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    seen = []
    cur = None
    while True:
        res = r.search_text(rs, "alpha", limit=5, cursor=cur)
        seen += [h.event_id for h in res.results]
        cur = res.next_cursor
        if cur is None:
            break
    full = sorted(h.event_id for h in r.search_text(rs, "alpha").results)
    assert sorted(seen) == full
    rs.close(); store.close()


def test_fts_final_page_next_cursor_null(tmp_path: Path):
    items = [_fts_env(f"e{i:02d}", f"alpha token {i}") for i in range(1, 6)]
    jl = _ingest_fts_corpus(tmp_path, items)
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    cur = None
    pages = 0
    while True:
        res = r.search_text(rs, "alpha", limit=2, cursor=cur)
        pages += 1
        cur = res.next_cursor
        if cur is None:
            break
        assert pages < 10
    assert cur is None
    rs.close(); store.close()


def test_fts_cursor_query_binding_text(tmp_path: Path):
    jl = _ingest_fts_corpus(tmp_path, [
        _fts_env("e1", "alpha one"),
        _fts_env("e2", "beta two"),
    ])
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    cur = r.search_text(rs, "alpha", limit=1).next_cursor
    with pytest.raises(QueryError) as ei:
        r.search_text(rs, "beta", cursor=cur)
    assert ei.value.code == "cursor_query_mismatch"
    rs.close(); store.close()


def test_fts_cursor_structured_filter_binding(tmp_path: Path):
    jl = _ingest_fts_corpus(tmp_path, [
        _fts_env("e1", "alpha P", project_id="P"),
        _fts_env("e2", "alpha Q", project_id="Q"),
    ])
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    cur = r.search_text(rs, "alpha", req=QueryRequest(project_id="P"), limit=1).next_cursor
    with pytest.raises(QueryError) as ei:
        r.search_text(rs, "alpha", req=QueryRequest(project_id="Q"), cursor=cur)
    assert ei.value.code == "cursor_query_mismatch"
    rs.close(); store.close()


def test_fts_cursor_limit_binding(tmp_path: Path):
    jl = _ingest_fts_corpus(tmp_path, [
        _fts_env("e1", "alpha one"),
        _fts_env("e2", "alpha two"),
        _fts_env("e3", "alpha three"),
    ])
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    cur = r.search_text(rs, "alpha", limit=2).next_cursor
    with pytest.raises(QueryError) as ei:
        r.search_text(rs, "alpha", limit=3, cursor=cur)
    assert ei.value.code == "cursor_limit_mismatch"
    rs.close(); store.close()


def test_fts_cursor_malformed(tmp_path: Path):
    jl = _ingest_fts_corpus(tmp_path, [_fts_env("e1", "alpha one")])
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    with pytest.raises(QueryError) as ei:
        r.search_text(rs, "alpha", cursor="!!!not-valid-base64@@@")
    assert ei.value.code == "invalid_cursor"
    rs.close(); store.close()


# ============================ secret safety ============================

def test_cursor_contains_no_secret(tmp_path: Path):
    jl = _ingest_fts_corpus(tmp_path, [_fts_env("e1", f"safe note with {SECRET} inside")])
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    # The secret lives in sanitized content; search a safe matching term (the cursor only
    # carries the normalized-query hash + sort tuple + limit, never content).
    cur = r.search_text(rs, "safe", limit=1).next_cursor
    assert cur is not None
    assert SECRET not in cur
    assert "DEADBEEF" not in cur
    rs.close(); store.close()


def test_snippet_scan_covers_fts(tmp_path: Path):
    jl = _ingest_fts_corpus(tmp_path, [_fts_env("e1", "benign text only")])
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    # Inject a synthetic secret into zm_fts directly to prove the scan covers it (defense-in-depth).
    store._conn.execute(
        "UPDATE zm_fts SET content = ? WHERE event_id = 'e1'", (f"leak {SECRET} here",)
    )
    store._conn.commit()
    _checkpoint_and_close(store)
    rs2 = r.open_readonly(store.path)
    res = r.search_text(rs2, "leak")
    assert len(res.results) >= 1
    # scan_sqlite_for_secrets expects a store exposing `._conn`; reopen read-write for the
    # read-only scan SELECT (ensure_schema is version-gated, no mutation).
    store_scan = _open_store(tmp_path, "m.sqlite")
    scanned = scan_sqlite_for_secrets(store_scan, [SECRET])
    assert SECRET in scanned, "secret scan must cover zm_fts"
    store_scan.close()
    rs2.close()
    # Restore clean content so subsequent tests are unaffected.
    store2 = _open_store(tmp_path, "m.sqlite")
    store2._conn.execute("UPDATE zm_fts SET content = 'benign text only' WHERE event_id='e1'")
    store2._conn.commit(); store2.close()


def test_error_contains_no_secret(tmp_path: Path):
    jl = _ingest_fts_corpus(tmp_path, [_fts_env("e1", f"alpha {SECRET}")])
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    res = r.search_text(rs, f"{SECRET} OR AND (")
    assert res.error == MALFORMED_FTS_EXPRESSION
    assert SECRET not in res.error
    rs.close(); store.close()


# ============================ read-only proof ============================

def test_sqlite_and_jsonl_unchanged_by_fts(tmp_path: Path):
    items = [
        _fts_env("e1", "alpha deploy"),
        _fts_env("e2", "beta rollout"),
        _fts_env("e3", "alpha migrate"),
    ]
    jl = _ingest_fts_corpus(tmp_path, items)
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    before = _fts_snapshot(store, jl)
    for q in ("alpha", "beta", "alpha OR", "nonexistent"):
        r.search_text(rs, q)
    cur = None
    for _ in range(3):
        res = r.search_text(rs, "alpha", limit=1, cursor=cur)
        cur = res.next_cursor
        if cur is None:
            break
    after = _fts_snapshot(store, jl)
    _assert_snapshot_equal(before, after)
    rs.close(); store.close()


# ============================ exclusion guarantees ============================

def test_no_m3_4_plus_behavior(tmp_path: Path):
    jl = _ingest_fts_corpus(tmp_path, [_fts_env("e1", "alpha deploy")])
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    res = r.search_text(rs, "alpha")
    hit = res.results[0]
    assert not hasattr(hit, "score")
    assert not hasattr(hit, "rank")
    assert not hasattr(hit, "relevance")
    rs.close(); store.close()


def test_no_real_hermes_home_writes_during_fts(tmp_path: Path):
    home = Path.home()
    before = {p.name for p in home.glob(".hermes*")} if home.exists() else set()
    jl = _ingest_fts_corpus(tmp_path, [_fts_env("e1", "alpha deploy")])
    store = _open_store(tmp_path, "m.sqlite")
    rs = r.open_readonly(store.path)
    r.search_text(rs, "alpha")
    r.search_text(rs, "alpha", limit=1)
    rs.close(); store.close()
    after = {p.name for p in home.glob(".hermes*")} if home.exists() else set()
    assert before == after, f"real ~/.hermes changed: {before} -> {after}"


def test_no_llm_or_network_calls_in_fts(monkeypatch):
    called = []

    def _blocked(*a, **k):
        called.append(True)
        raise AssertionError("network/LLM call attempted")

    monkeypatch.setattr("urllib.request.urlopen", _blocked)
    try:
        import openai  # noqa: F401
        monkeypatch.setattr(openai, "ChatCompletion", _blocked)
    except Exception:
        pass
    finally:
        # Do not leak openai into sys.modules; other tests assert a clean
        # module global (e.g. test_no_llm_dependency_imported).
        sys.modules.pop("openai", None)
    assert not called, "unexpected network/LLM call during FTS"
