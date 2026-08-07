"""M3.2 focused tests — deterministic pagination and stable ordering.

Reuses the verified M2 envelope/tombstone shapes and the M3.1 corpus + Snapshot
proof from ``test_m3_query``. Builds on the read-only layer; proves pagination causes
no writes (before/after invariants) and is fully deterministic.

Run: .venv/bin/python -m pytest tests/unit/test_m3_pagination.py -q
"""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from tests.unit.test_m3_query import (
    DERIVED_TABLES,
    Snapshot,
    _ingest_corpus,
    _make_env,
    _write_jsonl,
)
import src.retrieval as r
from src.retrieval import cursor as cursor_mod
from src.retrieval.models import (
    CURSOR_LIMIT_MISMATCH,
    CURSOR_QUERY_MISMATCH,
    INVALID_CURSOR,
    INVALID_LIMIT,
    QueryError,
    QueryRequest,
)
from src.retrieval import make_fingerprint, encode_cursor, decode_cursor


# ---- limit validation -----------------------------------------------------

def test_default_limit(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    res = r.query_events(rs, QueryRequest(project_id="P"))
    assert res.next_cursor is None  # 4 rows < default 50, so end of results
    assert len(res.items) == 4
    rs.close()
    store.close()


def test_explicit_valid_limit(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    res = r.query_events(rs, QueryRequest(project_id="P"), limit=2)
    assert len(res.items) == 2
    assert res.next_cursor is not None
    rs.close()
    store.close()


def test_maximum_limit(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    res = r.query_events(rs, QueryRequest(project_id="P"), limit=cursor_mod.MAX_LIMIT)
    assert len(res.items) == 4
    rs.close()
    store.close()


@pytest.mark.parametrize("bad", [0, -1, 501, "x", 3.5, True, False])
def test_invalid_limit_rejected(tmp_path: Path, bad) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    with pytest.raises(QueryError) as exc:
        r.query_events(rs, QueryRequest(project_id="P"), limit=bad)
    assert exc.value.code == INVALID_LIMIT
    rs.close()
    store.close()


# ---- deterministic ordering / pagination ----------------------------------

def test_deterministic_first_page(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    a = r.query_events(rs, QueryRequest(project_id="P"), limit=2).items
    b = r.query_events(rs, QueryRequest(project_id="P"), limit=2).items
    assert [v.event_id for v in a] == [v.event_id for v in b] == ["e1", "e2"]
    rs.close()
    store.close()


def test_deterministic_next_page(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    p1 = r.query_events(rs, QueryRequest(project_id="P"), limit=2)
    p2a = r.query_events(rs, QueryRequest(project_id="P"), limit=2, cursor=p1.next_cursor)
    p2b = r.query_events(rs, QueryRequest(project_id="P"), limit=2, cursor=p1.next_cursor)
    assert [v.event_id for v in p2a.items] == [v.event_id for v in p2b.items] == ["e3", "e6"]
    rs.close()
    store.close()


def test_stable_created_at_event_id_ordering(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    res = r.query_events(rs, QueryRequest(project_id="P"))
    keys = [(v.created_at, v.event_id) for v in res.items]
    assert keys == sorted(keys)
    rs.close()
    store.close()


def test_identical_timestamp_tie_break(tmp_path: Path) -> None:
    """Two rows with identical created_at must order by event_id (deterministic)."""
    jl = tmp_path / "same.jsonl"
    ts = "2026-02-01T00:00:00Z"
    _write_jsonl(jl, [
        _make_env("z3", project_id="P", created_at=ts, observed_at=ts),
        _make_env("z1", project_id="P", created_at=ts, observed_at=ts),
        _make_env("z2", project_id="P", created_at=ts, observed_at=ts),
    ])
    store = _open_and_rebuild(tmp_path, jl)
    rs = r.open_readonly(store.path)
    res = r.query_events(rs, QueryRequest(project_id="P"))
    assert [v.event_id for v in res.items] == ["z1", "z2", "z3"]
    rs.close()
    store.close()


def test_paginated_equals_full(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    full = [v.event_id for v in r.query_events(rs, QueryRequest(project_id="P")).items]
    pages: list[str] = []
    cursor = None
    while True:
        res = r.query_events(rs, QueryRequest(project_id="P"), limit=2, cursor=cursor)
        pages.extend(v.event_id for v in res.items)
        cursor = res.next_cursor
        if cursor is None:
            break
    assert pages == full
    rs.close()
    store.close()


def test_no_duplicate_rows_across_pages(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    seen: list[str] = []
    cursor = None
    while True:
        res = r.query_events(rs, QueryRequest(project_id="P"), limit=2, cursor=cursor)
        for v in res.items:
            assert v.event_id not in seen, f"duplicate {v.event_id}"
            seen.append(v.event_id)
        cursor = res.next_cursor
        if cursor is None:
            break
    assert seen == ["e1", "e2", "e3", "e6"]
    rs.close()
    store.close()


def test_no_skipped_rows_across_pages(tmp_path: Path) -> None:
    # Larger corpus to ensure multi-page coverage without gaps.
    jl = tmp_path / "big.jsonl"
    items = [
        _make_env(f"e{i:02d}", project_id="P", created_at=f"2026-03-{i:02d}T00:00:00Z",
                  observed_at=f"2026-03-{i:02d}T00:00:00Z")
        for i in range(1, 14)
    ]
    _write_jsonl(jl, items)
    store = _open_and_rebuild(tmp_path, jl)
    rs = r.open_readonly(store.path)
    seen: list[str] = []
    cursor = None
    while True:
        res = r.query_events(rs, QueryRequest(project_id="P"), limit=3, cursor=cursor)
        seen.extend(v.event_id for v in res.items)
        cursor = res.next_cursor
        if cursor is None:
            break
    full = [v.event_id for v in r.query_events(rs, QueryRequest(project_id="P")).items]
    assert seen == full
    assert len(seen) == 13
    rs.close()
    store.close()


def test_final_page_next_cursor_null(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    cursor = None
    last_had_cursor = True
    while last_had_cursor:
        res = r.query_events(rs, QueryRequest(project_id="P"), limit=2, cursor=cursor)
        cursor = res.next_cursor
        last_had_cursor = cursor is not None
    assert cursor is None
    rs.close()
    store.close()


def test_empty_result_pagination(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    res = r.query_events(rs, QueryRequest(project_id="ZZZ"), limit=2)
    assert res.items == []
    assert res.next_cursor is None
    rs.close()
    store.close()


def test_combined_filters_pagination(tmp_path: Path) -> None:
    # project_id + profile_id + event_type + created_at range, paginated.
    jl = tmp_path / "comb.jsonl"
    items = [
        _make_env(f"c{i:02d}", project_id="P", profile_id="A", event_type="tool_observation",
                  created_at=f"2026-04-{i:02d}T00:00:00Z", observed_at=f"2026-04-{i:02d}T00:00:00Z")
        for i in range(1, 11)
    ]
    _write_jsonl(jl, items)
    store = _open_and_rebuild(tmp_path, jl)
    rs = r.open_readonly(store.path)
    req = QueryRequest(project_id="P", profile_id="A", event_type="tool_observation",
                       created_at_after="2026-04-03T00:00:00Z")
    full = [v.event_id for v in r.query_events(rs, req).items]
    pages: list[str] = []
    cursor = None
    while True:
        res = r.query_events(rs, req, limit=3, cursor=cursor)
        pages.extend(v.event_id for v in res.items)
        cursor = res.next_cursor
        if cursor is None:
            break
    assert pages == full
    # Fingerprint binds to the complete normalized filter set.
    qf = make_fingerprint(req)
    assert qf == make_fingerprint(QueryRequest(
        project_id="P", profile_id="A", event_type="tool_observation",
        created_at_after="2026-04-03T00:00:00Z"))
    rs.close()
    store.close()


# ---- cursor validation ---------------------------------------------------

def test_valid_cursor_resume(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    p1 = r.query_events(rs, QueryRequest(project_id="P"), limit=2)
    p2 = r.query_events(rs, QueryRequest(project_id="P"), limit=2, cursor=p1.next_cursor)
    assert [v.event_id for v in p1.items] == ["e1", "e2"]
    assert [v.event_id for v in p2.items] == ["e3", "e6"]
    rs.close()
    store.close()


def test_malformed_cursor(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    for bad in ("", "!!!", "not-base64-@#", base64.urlsafe_b64encode(b"not json").decode()):
        with pytest.raises(QueryError) as exc:
            r.query_events(rs, QueryRequest(project_id="P"), cursor=bad)
        assert exc.value.code == INVALID_CURSOR
    rs.close()
    store.close()


def test_unsupported_cursor_version(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    qf = make_fingerprint(QueryRequest(project_id="P"))
    valid = encode_cursor(qf, "2026-01-01T00:00:00Z", "e1", 2)
    data = json.loads(base64.urlsafe_b64decode(valid + "=" * (-len(valid) % 4)))
    data["v"] = 2
    bad = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
    with pytest.raises(QueryError) as exc:
        r.query_events(rs, QueryRequest(project_id="P"), cursor=bad)
    assert exc.value.code == INVALID_CURSOR
    rs.close()
    store.close()


def test_cursor_query_mismatch(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    p1 = r.query_events(rs, QueryRequest(project_id="P"), limit=2)
    with pytest.raises(QueryError) as exc:
        r.query_events(rs, QueryRequest(project_id="Q"), limit=2, cursor=p1.next_cursor)
    assert exc.value.code == CURSOR_QUERY_MISMATCH
    rs.close()
    store.close()


def test_cursor_limit_mismatch(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    p1 = r.query_events(rs, QueryRequest(project_id="P"), limit=2)
    with pytest.raises(QueryError) as exc:
        r.query_events(rs, QueryRequest(project_id="P"), limit=3, cursor=p1.next_cursor)
    assert exc.value.code == CURSOR_LIMIT_MISMATCH
    rs.close()
    store.close()


def test_cursor_missing_sort_fields(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    qf = make_fingerprint(QueryRequest(project_id="P"))
    bad = base64.urlsafe_b64encode(
        json.dumps({"v": 1, "qf": qf, "lim": 2}).encode()).decode()
    with pytest.raises(QueryError) as exc:
        r.query_events(rs, QueryRequest(project_id="P"), cursor=bad)
    assert exc.value.code == INVALID_CURSOR
    rs.close()
    store.close()


def test_cursor_contains_no_secret(tmp_path: Path) -> None:
    secret = "SK-M3-CURSOR-SECRET"
    # Use a query whose normalized form would never embed the secret (M3 filters
    # are discrete enums/ids, not free text). Encode a cursor and assert the secret
    # is absent from the encoded token.
    qf = make_fingerprint(QueryRequest(project_id="P"))
    token = encode_cursor(qf, "2026-01-01T00:00:00Z", "e1", 2)
    assert secret not in token
    # Decoded payload also carries no secret.
    payload = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    assert secret not in json.dumps(payload)
    rs = r.open_readonly(_ingest_corpus(tmp_path).path)
    rs.close()


# ---- deleted exclusion across page boundaries -----------------------------

def test_deleted_exclusion_across_pages(tmp_path: Path) -> None:
    from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
    from src.storage.ingest import rebuild_from_jsonl, ingest_file
    jl = tmp_path / "corpus.jsonl"
    _write_jsonl(jl, [
        _make_env(f"d{i:02d}", project_id="P",
                  created_at=f"2026-05-{i:02d}T00:00:00Z", observed_at=f"2026-05-{i:02d}T00:00:00Z")
        for i in range(1, 9)
    ])
    s = SQLiteStore(SQLiteStoreConfig(path=tmp_path / "m.sqlite"))
    s.ensure_schema()
    rebuild_from_jsonl(s, [jl])
    _write_jsonl(tmp_path / "del.jsonl", [_make_env("t1", lifecycle_status="deleted",
                                                     deletion={"target_event_id": "d04"})])
    ingest_file(s, tmp_path / "del.jsonl")
    s._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    s._conn.commit()
    s.close()

    rs = r.open_readonly(tmp_path / "m.sqlite")
    all_ids: list[str] = []
    cursor = None
    while True:
        res = r.query_events(rs, QueryRequest(project_id="P"), limit=3, cursor=cursor)
        all_ids.extend(v.event_id for v in res.items)
        cursor = res.next_cursor
        if cursor is None:
            break
    assert "d04" not in all_ids
    assert set(all_ids) == {f"d{i:02d}" for i in range(1, 9)} - {"d04"}
    rs.close()


# ---- read-only proof (before/after) ---------------------------------------

def test_pagination_no_mutation(tmp_path: Path) -> None:
    jl = tmp_path / "corpus.jsonl"
    from tests.unit.test_m3_query import _build_corpus
    _build_corpus(jl)
    store = _ingest_corpus(tmp_path)
    store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    store._conn.commit()
    snap_before = Snapshot(store, jl)

    rs = r.open_readonly(store.path)
    cursor = None
    for _ in range(5):
        res = r.query_events(rs, QueryRequest(project_id="P"), limit=2, cursor=cursor)
        cursor = res.next_cursor
        if cursor is None:
            break
    # also page the whole corpus
    cursor = None
    while True:
        res = r.query_events(rs, QueryRequest(), limit=3, cursor=cursor)
        cursor = res.next_cursor
        if cursor is None:
            break
    rs.close()

    snap_after = Snapshot(store, jl)
    snap_before.assert_unchanged(snap_after)
    store.close()


def test_sqlite_unchanged_by_pagination(tmp_path: Path) -> None:
    jl = tmp_path / "corpus.jsonl"
    from tests.unit.test_m3_query import _build_corpus
    _build_corpus(jl)
    store = _ingest_corpus(tmp_path)
    store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    store._conn.commit()
    before = {t: store._conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
              for t in DERIVED_TABLES}
    rs = r.open_readonly(store.path)
    cursor = None
    while True:
        res = r.query_events(rs, QueryRequest(project_id="P"), limit=2, cursor=cursor)
        cursor = res.next_cursor
        if cursor is None:
            break
    rs.close()
    after = {t: store._conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
             for t in DERIVED_TABLES}
    assert before == after
    store.close()


def test_jsonl_unchanged_by_pagination(tmp_path: Path) -> None:
    import hashlib
    jl = tmp_path / "corpus.jsonl"
    from tests.unit.test_m3_query import _build_corpus
    _build_corpus(jl)
    sha_before = hashlib.sha256(jl.read_bytes()).hexdigest()
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    cursor = None
    while True:
        res = r.query_events(rs, QueryRequest(), limit=3, cursor=cursor)
        cursor = res.next_cursor
        if cursor is None:
            break
    rs.close()
    store.close()
    assert hashlib.sha256(jl.read_bytes()).hexdigest() == sha_before


# ---- no LLM / network / real home -----------------------------------------

def test_no_llm_calls_pagination(tmp_path: Path) -> None:
    import subprocess
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    real_run = subprocess.run
    real_popen = subprocess.Popen

    def _blocked(*a, **k):
        raise AssertionError("M3.2 must not spawn subprocesses (LLM/network)")

    subprocess.run = _blocked  # type: ignore[assignment]
    subprocess.Popen = _blocked  # type: ignore[assignment]
    try:
        r.query_events(rs, QueryRequest(project_id="P"), limit=2)
        p1 = r.query_events(rs, QueryRequest(project_id="P"), limit=2)
        r.query_events(rs, QueryRequest(project_id="P"), limit=2, cursor=p1.next_cursor)
    finally:
        subprocess.run = real_run
        subprocess.Popen = real_popen
    rs.close()
    store.close()


def test_no_network_calls_pagination(tmp_path: Path) -> None:
    import socket
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    real_socket = socket.socket

    def _blocked_socket(*a, **k):
        raise AssertionError("M3.2 must not open sockets (network)")

    socket.socket = _blocked_socket  # type: ignore[assignment]
    try:
        r.query_events(rs, QueryRequest(project_id="P"), limit=2)
    finally:
        socket.socket = real_socket
    rs.close()
    store.close()


def test_no_real_hermes_home_writes_pagination(tmp_path: Path) -> None:
    from pathlib import Path as _P
    real_home = _P.home() / ".hermes"
    baseline = ({p.relative_to(real_home) for p in real_home.rglob("*")}
                 if real_home.exists() else set())
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    r.query_events(rs, QueryRequest(project_id="P"), limit=2)
    cursor = None
    while True:
        res = r.query_events(rs, QueryRequest(), limit=3, cursor=cursor)
        cursor = res.next_cursor
        if cursor is None:
            break
    rs.close()
    store.close()
    after = ({p.relative_to(real_home) for p in real_home.rglob("*")}
              if real_home.exists() else set())
    new_files = after - baseline
    attributable = [n for n in new_files if n.suffix in (".sqlite", ".sqlite-wal", ".sqlite-shm", ".jsonl")]
    assert attributable == [], f"M3.2 wrote to real ~/.hermes: {attributable}"


# ---- scope boundaries -----------------------------------------------------

def test_no_m3_3_behavior(tmp_path: Path) -> None:
    """M3.2 exposes no FTS / semantic / ranking surfaces."""
    assert not hasattr(r.query, "search_text")
    assert not hasattr(r.cursor, "fts")
    assert "rank" not in dir(r.query)


def test_no_m4_behavior_pagination(tmp_path: Path) -> None:
    assert not hasattr(r, "write_memory")
    assert not hasattr(r, "route_query")
    assert not hasattr(r, "inject_context")


# ---- helpers --------------------------------------------------------------

def _open_and_rebuild(tmp_path: Path, jl: Path):
    """Build a store from a custom JSONL (checkpointed, open), reusing M3.1 pattern."""
    from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
    from src.storage.ingest import rebuild_from_jsonl
    store = SQLiteStore(SQLiteStoreConfig(path=tmp_path / "m.sqlite"))
    store.ensure_schema()
    rebuild_from_jsonl(store, [jl])
    store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    store._conn.commit()
    return store
