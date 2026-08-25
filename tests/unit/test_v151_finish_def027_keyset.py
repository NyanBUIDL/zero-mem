"""V1.5.1 Finish — DEF-027 structured keyset pagination data loss.

``AuthorizedReadService.query_events`` extracts the cursor keyset but never
forwards it to ``_select_m3``, so every page re-fetches the first
``limit+1`` rows of the keyset-ordered result set and the Python-side filter
keeps only rows after the cursor — permanently skipping everything between.

RED on the V1.5.1-Finish candidate tree (repro:
``zero-mem-dev-data/evidence/v151f-b3-def027-repro.out``), GREEN after wiring
the keyset through to the SQL layer.
"""
from __future__ import annotations

import sqlite3

from src.access.authorized_read import AuthorizedReadService
from src.access.contracts import AccessRequest
from src.access.grants import AuthorizedReadGrant
from src.retrieval.db import ReadonlyStore
from src.storage.ingest import ingest_file
from tests.unit.test_m3_query import (
    _checkpoint_and_close,
    _make_env,
    _open_store,
    _write_jsonl,
)


def _store_with_unique_timestamps(tmp_path, n_events=300):
    rows = []
    for i in range(n_events):
        ts = f"2026-01-01T{i // 3600:02d}:{(i % 3600) // 60:02d}:{i % 60:02d}Z"
        rows.append(_make_env(f"e{i:03d}", project_id="P", created_at=ts, observed_at=ts))
    jl = tmp_path / "e.jsonl"
    _write_jsonl(jl, rows)
    store = _open_store(tmp_path, "m.sqlite")
    ingest_file(store, jl)
    _checkpoint_and_close(store)
    conn = sqlite3.connect(tmp_path / "m.sqlite")
    conn.row_factory = sqlite3.Row
    return ReadonlyStore(conn, tmp_path / "m.sqlite")


class TestDef027KeysetWiring:
    def test_full_walk_returns_every_event(self, tmp_path):
        ro = _store_with_unique_timestamps(tmp_path, 300)
        svc = AuthorizedReadService(ro, "prof-owner", grant_conn=ro.conn)
        req = AccessRequest(operation="READ", requesting_profile_id="prof-owner",
                            project_ids=["P"])
        grant = AuthorizedReadGrant(
            grant_id="g1", subject_profile="prof-owner", operation="READ",
            target_type="project", target_id="P",
            resource_types=["memory_event"],
        )
        seen = set()
        cursor = None
        pages = 0
        for _ in range(100):
            res = svc.query_events(req, project_filter="P", limit=5,
                                   cursor=cursor, grants=[grant])
            assert res.allowed, res.reason_code
            pages += 1
            for item in res.items:
                assert item.event_id not in seen, f"duplicate {item.event_id}"
                seen.add(item.event_id)
            cursor = res.next_cursor
            if cursor is None:
                break
        # 300 events at limit=5 -> ~61 pages (60 full + partial). Anything less
        # means rows were silently dropped between page boundaries.
        assert len(seen) == 300, (
            f"keyset pagination dropped {300 - len(seen)} of 300 events "
            f"across {pages} pages"
        )

    def test_page2_starts_after_page1_boundary(self, tmp_path):
        ro = _store_with_unique_timestamps(tmp_path, 40)
        svc = AuthorizedReadService(ro, "prof-owner", grant_conn=ro.conn)
        req = AccessRequest(operation="READ", requesting_profile_id="prof-owner",
                            project_ids=["P"])
        grant = AuthorizedReadGrant(
            grant_id="g1", subject_profile="prof-owner", operation="READ",
            target_type="project", target_id="P",
            resource_types=["memory_event"],
        )
        p1 = svc.query_events(req, project_filter="P", limit=10, grants=[grant])
        assert [i.event_id for i in p1.items] == [f"e{i:03d}" for i in range(10)]
        p2 = svc.query_events(req, project_filter="P", limit=10,
                              cursor=p1.next_cursor, grants=[grant])
        ids = [i.event_id for i in p2.items]
        assert ids == [f"e{i:03d}" for i in range(10, 20)], (
            f"page 2 skipped rows: {ids[:5]}..."
        )
