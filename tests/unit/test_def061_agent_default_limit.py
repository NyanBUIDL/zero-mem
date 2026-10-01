"""DEF-061 (agent-facing default) - the authorized corpus read path must not
silently widen the planner's token-friendly default back to 100.

``AuthorizedReadService.corpus_unit_search`` used to call
``build_query_plan(..., limit=limit or 100)``, so an agent that sent no ``limit``
over MCP got up to 100 full-text hits (T3 fixed the planner default to 20 but this
call site overrode it).  An explicit ``limit`` is still honoured up to the
contract cap (``MAX_LIMIT`` = 500); anything above it is a malformed request.
"""
from __future__ import annotations

import pytest

from src.corpus.query_planner import DEFAULT_RESULT_LIMIT, MAX_RESULT_LIMIT
from src.integration.m6.contracts import MAX_LIMIT
from tests.unit.t3_corpus_helpers import build_store, doc, search
from tests.unit.t6a_mcp_helpers import call_tool, configure_inprocess, envelope_of

N_UNITS = 45


@pytest.fixture()
def many(tmp_path):
    ro = build_store(tmp_path, [doc(f"zebra note number {i}") for i in range(N_UNITS)])
    yield ro
    ro.close()


def test_agent_default_is_at_most_twenty():
    assert DEFAULT_RESULT_LIMIT <= 20


def test_facade_without_limit_uses_the_planner_default(many):
    assert len(search(many, "zebra").items) == DEFAULT_RESULT_LIMIT


def test_facade_explicit_limit_is_honoured_below_and_above_the_default(many):
    assert len(search(many, "zebra", limit=5).items) == 5
    assert len(search(many, "zebra", limit=40).items) == 40


def test_mcp_corpus_search_without_limit_is_bounded(many):
    server = configure_inprocess(many.path)
    env = envelope_of(call_tool(
        server, "corpus_search", {"search_text": "zebra", "requesting_profile_id": "p1"}))
    assert env["status"] == "SUCCESS"
    assert len(env["results"]) == DEFAULT_RESULT_LIMIT


def test_mcp_corpus_search_explicit_limit_is_honoured(many):
    server = configure_inprocess(many.path)
    env = envelope_of(call_tool(
        server, "corpus_search",
        {"search_text": "zebra", "requesting_profile_id": "p1", "limit": 30}))
    assert len(env["results"]) == 30


def test_explicit_cap_is_still_enforced_by_the_contract(many):
    assert MAX_LIMIT == MAX_RESULT_LIMIT == 500
    server = configure_inprocess(many.path)
    env = envelope_of(call_tool(
        server, "corpus_search",
        {"search_text": "zebra", "requesting_profile_id": "p1", "limit": MAX_LIMIT + 1}))
    assert env["status"] == "INVALID_REQUEST"
    assert env.get("results", []) == []
