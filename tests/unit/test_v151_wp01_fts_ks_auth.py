"""V1.5.1 WP-01 (DEF-020) — FTS knowledge-space authorization parity.

The structured read path was fixed in V150-WP2/WP3 (DEF-010/011) to authorize
per-row via ``zm_meta.knowledge_space_id``. The FTS path did NOT carry that
boundary: ``SearchHit`` had no ``knowledge_space_id`` and the sidecar FTS
facilitator (``AuthorizedReadService.search_text``) only passed the plain
``req.knowledge_space_id`` filter, never the effective grant scope. So a
cross-profile space grant could not authorize an FTS hit, and an event in a
NON-granted knowledge space (but same profile/project) leaked into FTS results.

These tests must RED on the V1.5.0 baseline and GREEN after the fix.
"""
from __future__ import annotations

import sqlite3

import pytest

from src.access.contracts import AccessRequest
from src.access.grants import AuthorizedReadGrant
from src.retrieval.db import ReadonlyStore
from src.retrieval.models import SearchHit
from src.storage.ingest import ingest_file
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from tests.unit.test_m3_query import (
    _checkpoint_and_close,
    _make_env,
    _open_store,
    _write_jsonl,
)


def _fts_store(tmp_path):
    items = [
        _make_env("ev-in-space", sanitized_content={"text": "alpha module"},
                  knowledge_space_id="quant-theory", profile_id="prof-x"),
        _make_env("ev-other-space", sanitized_content={"text": "alpha module"},
                  knowledge_space_id="other-ks", profile_id="prof-x"),
        _make_env("ev-unscoped", sanitized_content={"text": "alpha module"},
                  knowledge_space_id=None, profile_id="prof-x"),
    ]
    jl = tmp_path / "fts.jsonl"
    _write_jsonl(jl, items)
    store = _open_store(tmp_path, "m.sqlite")
    ingest_file(store, jl)
    _checkpoint_and_close(store)
    conn = sqlite3.connect(tmp_path / "m.sqlite")
    conn.row_factory = sqlite3.Row
    return ReadonlyStore(conn, tmp_path / "m.sqlite")


def _grant(target_id: str) -> AuthorizedReadGrant:
    return AuthorizedReadGrant(
        grant_id="g-test", subject_profile="prof-owner",
        operation="READ", target_type="knowledge_space",
        target_id=target_id, resource_types=["memory_event"],
    )


class TestDef020FtsKnowledgeSpaceAuth:
    def test_fts_hit_carries_knowledge_space_id(self, tmp_path):
        import src.retrieval as r

        ro = _fts_store(tmp_path)
        res = r.search_text(ro, "alpha")
        assert res.error is None
        assert res.results, "expected at least one FTS hit"
        for h in res.results:
            assert isinstance(h, SearchHit)
            # Must expose the row's own ks so authorization can validate it.
            assert hasattr(h, "knowledge_space_id")
            # The authorized None value is permitted; the attribute must exist.
            _ = h.knowledge_space_id

    def test_fts_space_grant_authorizes_only_granted_ks(self, tmp_path):
        from src.access.authorized_read import AuthorizedReadService

        ro = _fts_store(tmp_path)
        svc = AuthorizedReadService(ro, "prof-owner", grant_conn=ro.conn,
                                    corpus_conn=None)
        req = AccessRequest(operation="READ",
                            requesting_profile_id="prof-owner",
                            knowledge_space_ids=["quant-theory"])
        result = svc.search_text(req, "alpha", grants=[_grant("quant-theory")])
        assert result.allowed, result.error
        ids = {h.event_id for h in result.items}
        assert "ev-in-space" in ids
        # Same profile/project, different (non-granted) KS must NOT surface.
        assert "ev-other-space" not in ids
        # NULL ks is unscoped and never authorized by a space grant.
        assert "ev-unscoped" not in ids

    def test_fts_space_grant_union_of_two_spaces(self, tmp_path):
        from src.access.authorized_read import AuthorizedReadService

        items = [
            _make_env("a1", sanitized_content={"text": "shared token"},
                      knowledge_space_id="ks-a", profile_id="prof-x"),
            _make_env("b1", sanitized_content={"text": "shared token"},
                      knowledge_space_id="ks-b", profile_id="prof-x"),
            _make_env("c1", sanitized_content={"text": "shared token"},
                      knowledge_space_id="ks-c", profile_id="prof-x"),
        ]
        jl = tmp_path / "fts2.jsonl"
        _write_jsonl(jl, items)
        store = _open_store(tmp_path, "m2.sqlite")
        ingest_file(store, jl)
        _checkpoint_and_close(store)
        conn = sqlite3.connect(tmp_path / "m2.sqlite")
        conn.row_factory = sqlite3.Row
        ro = ReadonlyStore(conn, tmp_path / "m2.sqlite")

        svc = AuthorizedReadService(ro, "prof-owner", grant_conn=ro.conn,
                                    corpus_conn=None)
        req = AccessRequest(operation="READ",
                            requesting_profile_id="prof-owner",
                            knowledge_space_ids=["ks-a", "ks-b"])
        result = svc.search_text(req, "shared",
                                 grants=[_grant("ks-a"), _grant("ks-b")])
        assert result.allowed, result.error
        ids = {h.event_id for h in result.items}
        assert ids == {"a1", "b1"}
