"""T5 - metadata-only candidate discovery filters in SQL (scope + closed metadata) before the discovery cap.

``retrieve_corpus`` bounds candidate discovery (DEF-030).  For metadata-only queries (no lexical text, as the
Memory context bundle issues) it used to read the first ``cap`` unit rows in rowid order and filter afterwards,
so rows of other profiles or of other source types registered earlier could crowd the caller's own rows out of
the window.  The scope and metadata predicates are exact (the Python filters stay as the final check), so they
are pushed into the SELECT.
"""
from __future__ import annotations

import pytest

from src.corpus import retrieval as retrieval_mod
from tests.unit.t3_corpus_helpers import build_store, doc, search, texts


@pytest.fixture
def tiny_window(monkeypatch):
    """Make the discovery window smaller than the store."""
    monkeypatch.setattr(retrieval_mod, "_DISCOVERY_FACTOR", 0)
    monkeypatch.setattr(retrieval_mod, "_DISCOVERY_CAP_FLOOR", 4)


def _crowd(n=40):
    return [doc(f"crowd unit number {i}", profile="other") for i in range(n)]


def test_own_rows_are_found_even_when_other_profiles_filled_the_window(tmp_path, tiny_window):
    ro = build_store(tmp_path, _crowd() + [doc("mine alpha", profile="me"), doc("mine beta", profile="me")])
    try:
        res = search(ro, "", profile="me", limit=4)
        assert sorted(texts(res)) == ["mine alpha", "mine beta"]
    finally:
        ro.close()


def test_memory_type_filter_is_applied_before_the_window(tmp_path, tiny_window):
    docs = [doc(f"filler fact {i}", profile="me", meta={"memory_type": "fact"}) for i in range(40)]
    docs.append(doc("late persona facet", profile="me", meta={"memory_type": "persona"}))
    ro = build_store(tmp_path, docs)
    try:
        assert texts(search(ro, "", profile="me", limit=4, metadata={"memory_type": "persona"})) == ["late persona facet"]
    finally:
        ro.close()


def test_external_ref_prefix_filter_is_applied_before_the_window(tmp_path, tiny_window):
    docs = [doc(f"filler {i}", ref=f"file://f{i}.txt", profile="me") for i in range(40)]
    docs.append(doc("wanted unit", ref="mem://workflow/late", profile="me"))
    ro = build_store(tmp_path, docs)
    try:
        res = search(ro, "", profile="me", limit=4, metadata={"external_ref_prefix": "mem://workflow/"})
        assert texts(res) == ["wanted unit"]
    finally:
        ro.close()


def test_pushdown_never_widens_authorization(tmp_path, tiny_window):
    ro = build_store(tmp_path, _crowd(10) + [doc("mine only", profile="me")])
    try:
        assert texts(search(ro, "", profile="me", limit=4, metadata={"profile_id": "other"})) == []
        assert "crowd unit number 0" not in texts(search(ro, "", profile="me", limit=50))
    finally:
        ro.close()


def test_scope_with_a_knowledge_space_and_global_rows(tmp_path, tiny_window):
    docs = _crowd(30) + [
        doc("shared by other", profile="other", space="ks-shared"),
        doc("global row", profile=None),
        doc("mine private", profile="me"),
    ]
    ro = build_store(tmp_path, docs)
    try:
        own = search(ro, "", profile="me", limit=5)
        assert sorted(texts(own)) == ["global row", "mine private"]
    finally:
        ro.close()
