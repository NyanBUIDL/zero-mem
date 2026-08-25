"""V1.5.1 WP-02 (DEF-021 + DEF-022) — limit integrity and FTS ceiling.

DEF-021: the facade must NOT silently default/clamp invalid limits.
DEF-022: multi-scope FTS search must never return more than ``limit`` items
(regardless of how many scopes/grants are composed) and must paginate the
union rather than one query per scope.

RED on V1.5.0 baseline, GREEN after fix.
"""
from __future__ import annotations

import sqlite3

import pytest

from src.access.authorized_read import AuthorizedReadService
from src.access.contracts import AccessRequest
from src.access.grants import AuthorizedReadGrant
from src.retrieval.db import ReadonlyStore
from src.retrieval.models import INVALID_LIMIT, QueryError
from src.storage.ingest import ingest_file
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from tests.unit.test_m3_query import (
    _checkpoint_and_close,
    _make_env,
    _open_store,
    _write_jsonl,
)


def _store_with_events(tmp_path, rows):
    store = _open_store(tmp_path, "m.sqlite")
    jl = tmp_path / "e.jsonl"
    _write_jsonl(jl, rows)
    ingest_file(store, jl)
    _checkpoint_and_close(store)
    conn = sqlite3.connect(tmp_path / "m.sqlite")
    conn.row_factory = sqlite3.Row
    return ReadonlyStore(conn, tmp_path / "m.sqlite")


def _grant(target_id: str, target_type: str = "knowledge_space") -> AuthorizedReadGrant:
    return AuthorizedReadGrant(
        grant_id="g-test", subject_profile="prof-owner",
        operation="READ", target_type=target_type,
        target_id=target_id, resource_types=["memory_event"],
    )


class TestDef021StrictLimit:
    def test_invalid_limit_raises_in_facade(self, tmp_path):
        rows = [_make_env(f"e{i:02d}", project_id="P") for i in range(10)]
        ro = _store_with_events(tmp_path, rows)
        svc = AuthorizedReadService(ro, "prof-owner", grant_conn=ro.conn)
        req = AccessRequest(operation="READ", requesting_profile_id="prof-owner",
                            project_ids=["P"])
        for bad in [0, -1, 10_000, True, 1.5, "50"]:
            with pytest.raises(QueryError) as ei:
                svc.query_events(req, project_filter="P", limit=bad,
                                 grants=[_grant("P", target_type="project")])
            assert ei.value.code == INVALID_LIMIT, bad

    def test_limit_none_uses_default(self, tmp_path):
        rows = [_make_env(f"e{i:02d}", project_id="P") for i in range(200)]
        ro = _store_with_events(tmp_path, rows)
        svc = AuthorizedReadService(ro, "prof-owner", grant_conn=ro.conn)
        req = AccessRequest(operation="READ", requesting_profile_id="prof-owner",
                            project_ids=["P"])
        res = svc.query_events(req, project_filter="P", grants=[_grant("P", target_type="project")])
        assert res.allowed
        # Default limit (50) is an explicit server-owned ceiling, not unbounded.
        assert len(res.items) == 50
        assert res.next_cursor is not None

    def test_limit_one_returns_one(self, tmp_path):
        rows = [_make_env(f"e{i:02d}", project_id="P") for i in range(20)]
        ro = _store_with_events(tmp_path, rows)
        svc = AuthorizedReadService(ro, "prof-owner", grant_conn=ro.conn)
        req = AccessRequest(operation="READ", requesting_profile_id="prof-owner",
                            project_ids=["P"])
        res = svc.query_events(req, project_filter="P", limit=1,
                               grants=[_grant("P", target_type="project")])
        assert len(res.items) == 1


class TestDef022FtsCeiling:
    def _fts_store(self, tmp_path, items):
        jl = tmp_path / "fts.jsonl"
        _write_jsonl(jl, items)
        store = _open_store(tmp_path, "m.sqlite")
        ingest_file(store, jl)
        _checkpoint_and_close(store)
        conn = sqlite3.connect(tmp_path / "m.sqlite")
        conn.row_factory = sqlite3.Row
        return ReadonlyStore(conn, tmp_path / "m.sqlite")

    def test_multi_scope_fts_never_exceeds_limit(self, tmp_path):
        # Two knowledge spaces with many matching events each.
        items = []
        for i in range(30):
            items.append(_make_env(f"a{i:02d}", sanitized_content={"text": "shared token"},
                                   knowledge_space_id="ks-a", profile_id="prof-x"))
            items.append(_make_env(f"b{i:02d}", sanitized_content={"text": "shared token"},
                                   knowledge_space_id="ks-b", profile_id="prof-x"))
        ro = self._fts_store(tmp_path, items)
        svc = AuthorizedReadService(ro, "prof-owner", grant_conn=ro.conn,
                                    corpus_conn=None)
        req = AccessRequest(operation="READ", requesting_profile_id="prof-owner",
                            knowledge_space_ids=["ks-a", "ks-b"])
        res = svc.search_text(req, "shared",
                              grants=[_grant("ks-a"), _grant("ks-b")], limit=10)
        assert res.allowed, res.error
        # Two scopes x 10 would be 20 without a ceiling; must be exactly <= 10.
        assert len(res.items) == 10

    def test_multi_scope_fts_union_paginates(self, tmp_path):
        items = []
        for i in range(20):
            items.append(_make_env(f"a{i:02d}", sanitized_content={"text": "shared token"},
                                   knowledge_space_id="ks-a", profile_id="prof-x"))
            items.append(_make_env(f"b{i:02d}", sanitized_content={"text": "shared token"},
                                   knowledge_space_id="ks-b", profile_id="prof-x"))
        ro = self._fts_store(tmp_path, items)
        svc = AuthorizedReadService(ro, "prof-owner", grant_conn=ro.conn,
                                    corpus_conn=None)
        req = AccessRequest(operation="READ", requesting_profile_id="prof-owner",
                            knowledge_space_ids=["ks-a", "ks-b"])
        seen = []
        cur = None
        for _ in range(20):
            res = svc.search_text(req, "shared", grants=[_grant("ks-a"), _grant("ks-b")],
                                  limit=7, cursor=cur)
            assert len(res.items) <= 7
            seen += [h.event_id for h in res.items]
            cur = res.next_cursor
            if cur is None:
                break
        # No duplicates, and the full union (both spaces) is recovered.
        assert len(seen) == len(set(seen))
        assert set(seen) == {f"a{i:02d}" for i in range(20)} | {f"b{i:02d}" for i in range(20)}

    def test_invalid_fts_limit_raises(self, tmp_path):
        ro = self._fts_store(tmp_path, [
            _make_env("x1", sanitized_content={"text": "alpha"},
                      knowledge_space_id="ks-a", profile_id="prof-x"),
        ])
        svc = AuthorizedReadService(ro, "prof-owner", grant_conn=ro.conn,
                                    corpus_conn=None)
        req = AccessRequest(operation="READ", requesting_profile_id="prof-owner",
                            knowledge_space_ids=["ks-a"])
        with pytest.raises(QueryError) as ei:
            svc.search_text(req, "alpha", grants=[_grant("ks-a")], limit=0)
        assert ei.value.code == INVALID_LIMIT
