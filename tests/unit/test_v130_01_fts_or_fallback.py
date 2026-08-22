"""V130-01 — FTS OR-fallback + precision guard (contract-first test frame).

Contract (docs/v1.3.0/plans/V130-01-SPEC.md):
- search_text giữ nguyên chữ ký; thêm SearchResult.match_mode: "and" | "or_fallback".
- AND trước; OR-fallback CHỈ khi AND 0 hàng và >=2 term.
- Cursor fingerprint bao gồm match_mode: cursor chéo chế độ bị từ chối.
Reuses the verified M2/M3 corpus builders (test_m3_query/test_m3_fts) so the FTS
substrate is populated exactly like production ingest.
"""
from __future__ import annotations

import json
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
from src.retrieval.models import QueryError, SearchResult


def _ingest_fts_corpus(tmp_path: Path, items) -> Path:
    jl = tmp_path / "fts.jsonl"
    _write_jsonl(jl, items)
    store = _open_store(tmp_path, "m.sqlite")
    ingest_file(store, jl)
    _checkpoint_and_close(store)
    return jl


def _corpus(tmp_path: Path) -> Path:
    items = [
        _make_env("e-a", sanitized_content={"text": "quantum lattice simulation notes"}),
        _make_env("e-b", sanitized_content={"text": "crystal lattice structure"}),
        _make_env("e-c", sanitized_content={"text": "quantum tunneling basics"}),
    ]
    return _ingest_fts_corpus(tmp_path, items)


@pytest.fixture
def ro(tmp_path):
    from src.retrieval.db import open_readonly

    jl = _corpus(tmp_path)
    return open_readonly(tmp_path / "m.sqlite")


# --- contract tests (RED until V130-01 implemented) ------------------------


def test_search_result_has_match_mode_field(ro):
    res = r.search_text(ro, "quantum lattice")
    assert isinstance(res, SearchResult)
    assert res.match_mode == "and"
    assert [h.event_id for h in res.results] == ["e-a"]


def test_or_fallback_only_when_and_empty(ro):
    # no single event has both terms -> AND empty -> fallback hits e-b,e-c
    res = r.search_text(ro, "tunneling crystal")
    assert res.error is None
    assert res.match_mode == "or_fallback"
    ids = {h.event_id for h in res.results}
    assert ids == {"e-b", "e-c"}


def test_and_hits_never_fall_back(ro):
    res = r.search_text(ro, "quantum lattice")
    assert res.match_mode == "and"
    assert {h.event_id for h in res.results} == {"e-a"}


def test_single_term_no_fallback(ro):
    res = r.search_text(ro, "lattice")
    assert res.match_mode == "and"
    assert {h.event_id for h in res.results} == {"e-a", "e-b"}

    empty = r.search_text(ro, "nonexistentterm")
    assert empty.match_mode == "and"
    assert empty.results == []


def test_fts_special_chars_safe_in_fallback(ro):
    res = r.search_text(ro, 'weird"(query)*')
    assert isinstance(res, SearchResult)
    assert res.match_mode in ("and", "or_fallback")


def test_cursor_rejected_across_match_modes(tmp_path):
    """Same text+filters, different mode: an OR-fallback cursor must be rejected on
    a forced-AND query and vice versa (fingerprint binds match_mode)."""
    from src.retrieval.db import open_readonly
    # Corpus long enough that both modes paginate: 3 events share 'lattice'.
    items = [
        _make_env(f"e-{i}", sanitized_content={"text": f"lattice doc {i}"})
        for i in range(4)
    ]
    items += [_make_env("x-1", sanitized_content={"text": "quantum lattice"}),
              _make_env("x-2", sanitized_content={"text": "quantum zzqqx"})]
    _ingest_fts_corpus(tmp_path, items)
    ro = open_readonly(tmp_path / "m.sqlite")

    # Fallback pass: 'zzqqx nomatch' -> AND 0 hits -> OR hits x-2 (via zzqqx)
    r_fb = r.search_text(ro, "nomatch zzqqx", limit=1)
    assert r_fb.match_mode == "or_fallback" and r_fb.next_cursor is not None
    with pytest.raises(QueryError):
        # different text, AND mode -> fingerprint mismatch regardless of mode
        r.search_text(ro, "quantum lattice", limit=1, cursor=r_fb.next_cursor)

    # AND pass cursor rejected when reused for a query whose rows come from fallback
    r_and = r.search_text(ro, "lattice", limit=1)
    assert r_and.match_mode == "and" and r_and.next_cursor is not None
    with pytest.raises(QueryError):
        r.search_text(ro, "nomatch zzqqx", limit=1, cursor=r_and.next_cursor)

    # Same-mode pagination still works end to end
    r2 = r.search_text(ro, "nomatch zzqqx", limit=1, cursor=r_fb.next_cursor)
    assert r2.match_mode == "or_fallback"
    assert r2.results == []  # x-2 was the only OR hit; page 2 is empty


def test_deterministic_order_preserved_in_fallback(ro):
    res = r.search_text(ro, "tunneling crystal")
    order = [(h.created_at, h.event_id) for h in res.results]
    assert order == sorted(order)


def test_structured_filters_apply_in_fallback(ro):
    req = r.QueryRequest(project_id="proj-nope")
    res = r.search_text(ro, "tunneling crystal", req=req)
    assert res.error is None
    # structured filter composes with whichever mode ran; nothing in proj-nope
    assert all(h.project_id == "proj-nope" for h in res.results)


def test_former_sidecar_zero_probe_is_now_positive_or_fallback(tmp_path):
    """GATE-A-REPLY V130-01 Bước 2: the old integration probe "no such sidecar
    fixture" (multi-term, terms present in the indexed envelope JSON) is now a
    legitimate or_fallback hit — asserted here as a positive case."""
    from src.retrieval.db import open_readonly
    items = [_make_env("r02-event", sanitized_content={
        "result": "sidecar fixture",
        "event_id": "r02-event",
    })]
    _ingest_fts_corpus(tmp_path, items)
    ro = open_readonly(tmp_path / "m.sqlite")
    res = r.search_text(ro, "no such sidecar fixture")
    assert res.error is None
    assert res.match_mode == "or_fallback"
    assert {h.event_id for h in res.results} == {"r02-event"}


def test_single_nonce_term_is_zero_hit_no_fallback(tmp_path):
    """GATE-A-REPLY V130-01 Bước 2: a single nonce term returns zero hits and
    never falls back — the sanctioned shape of a zero-result probe."""
    from src.retrieval.db import open_readonly
    items = [_make_env("r02-event", sanitized_content={"result": "sidecar fixture"})]
    _ingest_fts_corpus(tmp_path, items)
    ro = open_readonly(tmp_path / "m.sqlite")
    res = r.search_text(ro, "zm_probe_no_such_token_v130")
    assert res.error is None
    assert res.match_mode == "and"
    assert res.results == []
