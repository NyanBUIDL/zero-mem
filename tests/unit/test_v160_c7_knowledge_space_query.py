"""V1.6.0 C7 RED-first tests for Knowledge-Space relation helpers."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.retrieval import list_knowledge_space, open_readonly
from src.retrieval.models import CURSOR_QUERY_MISMATCH, QueryError
from tests.unit.test_m3_query import _make_env
from tests.unit.test_v160_c4_auth_junction import _build


def _store(tmp_path):
    items = [
        _make_env("multi-ab", knowledge_space_ids=["A", "B"]),
        _make_env("only-b", knowledge_space_ids=["B"]),
        _make_env("only-c", knowledge_space_ids=["C"]),
        _make_env("unscoped", knowledge_space_ids=[]),
        _make_env("deleted-b", knowledge_space_ids=["B"], lifecycle_status="deleted"),
    ]
    return open_readonly(Path(_build(tmp_path, items, name="c7.sqlite")))


def test_list_knowledge_space_reads_junction_membership(tmp_path):
    store = _store(tmp_path)
    try:
        result = list_knowledge_space(store, "B")
        assert [item.event_id for item in result.items] == ["multi-ab", "only-b"]
        assert result.query == {"knowledge_space_id": "B"}
    finally:
        store.close()


def test_list_knowledge_space_has_no_primary_or_global_fallback(tmp_path):
    store = _store(tmp_path)
    try:
        assert list_knowledge_space(store, "missing").items == []
    finally:
        store.close()


def test_list_knowledge_space_paginates_and_binds_cursor_to_space(tmp_path):
    store = _store(tmp_path)
    try:
        first = list_knowledge_space(store, "B", limit=1)
        second = list_knowledge_space(store, "B", limit=1, cursor=first.next_cursor)
        assert [item.event_id for item in first.items + second.items] == [
            "multi-ab", "only-b"
        ]
        with pytest.raises(QueryError) as exc:
            list_knowledge_space(store, "A", limit=1, cursor=first.next_cursor)
        assert exc.value.code == CURSOR_QUERY_MISMATCH
    finally:
        store.close()
