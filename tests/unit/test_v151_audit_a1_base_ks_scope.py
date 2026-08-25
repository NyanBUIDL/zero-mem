"""RED-first — DEF-028 (DEF-A1, P1): base-scope KS request treated as GRANT scope.

Reproduction (confirmed executable on baseline):
  - query_events with knowledge_space_ids=["K"], include_global=False (explicit
    local-only mode) returns CROSS-PROFILE events in K: ids=['ev-p1-k','ev-p2-k'].
  - get_event with the same request RETURNS another profile's event.
  - Default (include_global unset -> True) + KS: requester's OWN rows are DENIED
    (DENY_ISOLATED_SCOPE_ESCAPE) — false-negative availability bug.
Root cause: base scope with ks is conflated with grant scopes:
  _profile_predicate (authorized_read.py:123) returns (None,[]) -> no profile
  clause; _scope_allows is_grant_scope conflation (:179) -> KS branch authorizes
  any profile; corpus enumeration (None,None,K) (:924-930).

Expected post-fix: base scope (is_grant=False) is always requester-scoped;
grant scopes keep profile-unrestricted semantics.
"""
from __future__ import annotations

import sqlite3

import pytest

from src.access.authorized_read import AuthorizedReadService
from src.access.contracts import AccessRequest
from src.retrieval.db import ReadonlyStore
from src.storage.ingest import ingest_file
from tests.unit.test_m3_query import (
    _checkpoint_and_close,
    _make_env,
    _open_store,
    _write_jsonl,
)


def _event_store(tmp_path):
    items = [
        _make_env("ev-p1-k", profile_id="p1", project_id="P",
                  knowledge_space_id="K"),
        _make_env("ev-p2-k", profile_id="p2", project_id="Q",
                  knowledge_space_id="K"),
        _make_env("ev-p1-other", profile_id="p1", project_id="P",
                  knowledge_space_id="other-K"),
        _make_env("ev-p1-null", profile_id="p1", project_id="P",
                  knowledge_space_id=None),
    ]
    jl = tmp_path / "a1-events.jsonl"
    _write_jsonl(jl, items)
    store = _open_store(tmp_path, "a1.sqlite")
    ingest_file(store, jl)
    _checkpoint_and_close(store)
    conn = sqlite3.connect(tmp_path / "a1.sqlite")
    conn.row_factory = sqlite3.Row
    return ReadonlyStore(conn, tmp_path / "a1.sqlite")


class TestDef028BaseKsScope:
    def test_event_ks_local_only_does_not_leak_cross_profile(self, tmp_path):
        """P1: include_global=False + KS must NOT expose another profile's row."""
        ro = _event_store(tmp_path)
        svc = AuthorizedReadService(ro, "p1", grant_conn=ro.conn)
        try:
            res = svc.query_events(
                AccessRequest(operation="READ", requesting_profile_id="p1",
                              knowledge_space_ids=["K"], include_global=False))
            ids = {v.event_id for v in res.items}
            assert "ev-p1-k" in ids, "requester's own row in K must surface"
            assert "ev-p2-k" not in ids, (
                "cross-profile row in K must NOT surface in local-only mode")
        finally:
            ro.close()

    def test_get_event_local_only_does_not_leak(self, tmp_path):
        ro = _event_store(tmp_path)
        svc = AuthorizedReadService(ro, "p1", grant_conn=ro.conn)
        try:
            req = AccessRequest(operation="READ", requesting_profile_id="p1",
                                knowledge_space_ids=["K"], include_global=False)
            g = svc.get_event(req, "ev-p2-k")
            assert not g.items, "get_event must not return another profile's row"
        finally:
            ro.close()

    def test_event_default_ks_returns_own_rows(self, tmp_path):
        """P2 false-negative: default (include_global unset) + KS must not deny."""
        ro = _event_store(tmp_path)
        svc = AuthorizedReadService(ro, "p1", grant_conn=ro.conn)
        try:
            res = svc.query_events(
                AccessRequest(operation="READ", requesting_profile_id="p1",
                              knowledge_space_ids=["K"]))
            assert res.allowed, (
                "own rows must not be denied under default include_global + KS; "
                f"reason={res.reason_code}")
            ids = {v.event_id for v in res.items}
            assert "ev-p1-k" in ids
            assert "ev-p2-k" not in ids
        finally:
            ro.close()

    def test_corpus_ks_local_only_does_not_leak(self, tmp_path):
        from tests.unit.test_m10_5_retrieval import AUTH_DOC, _project, _svc
        ro = _project(tmp_path, [
            (AUTH_DOC, {"profile_id": "p1", "project_id": "P",
                        "knowledge_space_id": "K"}),
            (AUTH_DOC, {"profile_id": "p2", "project_id": "Q",
                        "knowledge_space_id": "K"}),
        ], tag="a1")
        svc = _svc(ro, profile="p1")
        try:
            res = svc.corpus_unit_search(
                AccessRequest(operation="READ", requesting_profile_id="p1",
                              knowledge_space_ids=["K"],
                              resource_type="corpus_unit",
                              include_global=False),
                "quantum superposition")
            assert res.allowed
            assert len(res.items) == 1, (
                f"cross-profile corpus units leaked: {len(res.items)}")
            assert res.items[0].profile_id == "p1"
        finally:
            ro.close()

    def test_fts_local_only_does_not_leak(self, tmp_path):
        """P1 FTS parity: search_text must not return another profile's row."""
        from src.retrieval.search import search_text  # FTS substrate check
        ro = _event_store(tmp_path)
        svc = AuthorizedReadService(ro, "p1", grant_conn=ro.conn)
        try:
            res = svc.search_text(
                AccessRequest(operation="READ", requesting_profile_id="p1",
                              knowledge_space_ids=["K"], include_global=False),
                "clean content")
            ids = {h.event_id for h in res.items}
            assert "ev-p1-k" in ids, "requester's own FTS hit in K must surface"
            assert "ev-p2-k" not in ids, (
                "cross-profile FTS hit in K must NOT surface in local-only mode")
        finally:
            ro.close()

