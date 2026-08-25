"""RED-first draft — DEF-B1 (P2): facade structured cursor fingerprint omits
project_filter and created_at_after/before.

Static evidence: src/access/authorized_read.py query_events builds
`fp_request = _QR(profile_id=profile_filter, session_id=session_filter,
verification_status=verification_filter, lifecycle_status=lifecycle_filter)`
— project_filter (passed as `proj`) and the two time-window filters are applied
to the query but NOT bound to the cursor fingerprint. A cursor minted under
project=P1 / window=T is accepted by a call with project=P2 / window=U (same
fingerprint), so the keyset is applied against a different filter set and rows
are silently skipped (pagination integrity, DEF-027 family).

Expected post-fix behavior: fingerprint includes every filter actually applied
to the query; reuse across a different project/time window raises
`cursor_query_mismatch`.

DRAFT STATUS: written without execution (no Python in environment).
Run: python -m pytest tests/unit/test_v151_audit_b1_cursor_filters.py
"""
from __future__ import annotations

import sqlite3

import pytest

from src.access.authorized_read import AuthorizedReadService
from src.access.contracts import AccessRequest
from src.retrieval.cursor import CURSOR_QUERY_MISMATCH
from src.retrieval.db import ReadonlyStore
from src.retrieval.models import QueryError
from src.storage.ingest import ingest_file
from tests.unit.test_m3_query import (
    _checkpoint_and_close,
    _make_env,
    _open_store,
    _write_jsonl,
)


def _store(tmp_path: Path):
    items = [
        _make_env("e1", project_id="P1", session_id="s1",
                  created_at="2026-01-01T00:00:00Z"),
        _make_env("e2", project_id="P1", session_id="s1",
                  created_at="2026-01-02T00:00:00Z"),
        _make_env("e3", project_id="P2", session_id="s1",
                  created_at="2026-01-03T00:00:00Z"),
    ]
    jl = tmp_path / "b1.jsonl"
    _write_jsonl(jl, items)
    store = _open_store(tmp_path, "b1.sqlite")
    ingest_file(store, jl)
    _checkpoint_and_close(store)
    conn = sqlite3.connect(tmp_path / "b1.sqlite")
    conn.row_factory = sqlite3.Row
    return ReadonlyStore(conn, tmp_path / "b1.sqlite")


class TestDefB1CursorBindsAllFilters:
    def test_cursor_rejected_across_project_filter(self, tmp_path):
        ro = _store(tmp_path)
        svc = AuthorizedReadService(ro, "p1", grant_conn=ro.conn)
        try:
            req = AccessRequest(operation="READ", requesting_profile_id="p1",
                                target_profile_ids=["p1"])
            page1 = svc.query_events(req, project_filter="P1", limit=1)
            assert page1.next_cursor, "expected a cursor from page 1"
            with pytest.raises(QueryError) as exc_info:
                svc.query_events(req, project_filter="P2",
                                 cursor=page1.next_cursor, limit=1)
            assert exc_info.value.code == CURSOR_QUERY_MISMATCH, (
                "cursor minted under project=P1 must not be reusable under "
                f"project=P2; got {getattr(exc_info.value, 'code', None)}")
        finally:
            ro.close()

    def test_cursor_rejected_across_time_window(self, tmp_path):
        ro = _store(tmp_path)
        svc = AuthorizedReadService(ro, "p1", grant_conn=ro.conn)
        try:
            req = AccessRequest(operation="READ", requesting_profile_id="p1",
                                target_profile_ids=["p1"])
            page1 = svc.query_events(
                req, project_filter="P1", limit=1,
                created_at_after="2026-01-01T00:00:00Z")
            assert page1.next_cursor
            with pytest.raises(QueryError) as exc_info:
                svc.query_events(
                    req, project_filter="P1", limit=1,
                    created_at_after="2026-01-02T00:00:00Z",
                    cursor=page1.next_cursor)
            assert exc_info.value.code == CURSOR_QUERY_MISMATCH, (
                "cursor minted under a different time window must be rejected")
        finally:
            ro.close()

    def test_full_pagination_within_same_filter_no_skip(self, tmp_path):
        """Control: with the same filter set, pagination must not skip rows."""
        ro = _store(tmp_path)
        svc = AuthorizedReadService(ro, "p1", grant_conn=ro.conn)
        try:
            req = AccessRequest(operation="READ", requesting_profile_id="p1",
                                target_profile_ids=["p1"])
            seen = []
            cursor = None
            while True:
                page = svc.query_events(req, project_filter="P1", limit=1,
                                        cursor=cursor)
                seen.extend(v.event_id for v in page.items)
                if not page.next_cursor:
                    break
                cursor = page.next_cursor
            assert seen == ["e1", "e2"], f"pagination skipped rows: {seen}"
        finally:
            ro.close()
