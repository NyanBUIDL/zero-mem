"""T6a item 6 - the MCP ``corpus_search`` tool forwards the ``memory_type`` and
``external_ref_prefix`` filters (added to ``retrieve_corpus`` by T3 / DEF-056) and
returns ``external_ref`` / ``memory_type`` in its results.

Filters are post-authorization narrowing only: they can never widen the scope.
"""
from __future__ import annotations

import pytest

from tests.unit.t6a_mcp_helpers import (
    build_matrix_store, call_tool, configure_inprocess, envelope_of, markers,
)


@pytest.fixture()
def mcp(tmp_path):
    return configure_inprocess(build_matrix_store(tmp_path))


def _search(server, profile="claude-code", **extra):
    args = {"search_text": "zebra", "requesting_profile_id": profile, "limit": 50}
    args.update(extra)
    return envelope_of(call_tool(server, "corpus_search", args))


def test_results_carry_external_ref_and_memory_type(mcp):
    env = _search(mcp, knowledge_space_ids=["ks-shared"])
    by_marker = {item["normalized_text"].rsplit("marker-", 1)[1].strip(): item
                 for item in env["results"]}
    assert by_marker["A"]["external_ref"] == "mem://persona/a"
    assert by_marker["A"]["memory_type"] == "persona"
    assert by_marker["B"]["external_ref"] == "mem://workflow/b"
    assert by_marker["B"]["memory_type"] == "workflow"


def test_memory_type_filter_is_forwarded(mcp):
    env = _search(mcp, knowledge_space_ids=["ks-shared"], filters={"memory_type": "workflow"})
    assert markers(env["results"]) == ["B"]
    env = _search(mcp, filters={"memory_type": "persona"})
    assert markers(env["results"]) == ["A", "C"]


def test_external_ref_prefix_filter_is_forwarded(mcp):
    env = _search(mcp, filters={"external_ref_prefix": "mem://fact/"})
    assert markers(env["results"]) == ["E", "H"]
    env = _search(mcp, filters={"external_ref_prefix": "mem://persona/c"})
    assert markers(env["results"]) == ["C"]


def test_filters_combine_with_and(mcp):
    env = _search(mcp, filters={"memory_type": "persona", "external_ref_prefix": "mem://persona/a"})
    assert markers(env["results"]) == ["A"]
    env = _search(mcp, filters={"memory_type": "fact", "external_ref_prefix": "mem://persona/"})
    assert env["status"] == "EMPTY"


def test_filter_never_widens_authorization(mcp):
    # codex's private persona (D) matches the filter but is not claude-code's to read.
    env = _search(mcp, filters={"memory_type": "persona"})
    assert "D" not in markers(env["results"])
    denied = _search(mcp, target_profile_ids=["codex"], filters={"memory_type": "persona"})
    assert denied["status"] == "POLICY_DENIED"


@pytest.mark.parametrize("filters", [
    {"project_id": "x"},                      # not a corpus_search filter
    {"unknown": "x"},
    {"memory_type": "bad type!"},
    {"memory_type": 5},
    {"external_ref_prefix": ""},
    {"external_ref_prefix": "x" * 513},
])
def test_unsupported_or_malformed_filters_are_invalid_requests(mcp, filters):
    resp = call_tool(mcp, "corpus_search", {
        "search_text": "zebra", "requesting_profile_id": "claude-code", "filters": filters})
    env = envelope_of(resp)
    assert env["status"] == "INVALID_REQUEST", env
    assert resp["result"]["isError"] is True
    assert env.get("results", []) == []


def test_corpus_search_schema_documents_the_two_filters():
    from src.integration.m6 import mcp_wrapper

    schema = {s["name"]: s for s in mcp_wrapper.tool_schemas()}["corpus_search"]
    filters = schema["inputSchema"]["properties"]["filters"]
    assert set(filters["properties"]) == {"memory_type", "external_ref_prefix"}


def test_no_filter_still_returns_everything_authorized(mcp):
    env = _search(mcp)
    assert markers(env["results"]) == ["A", "C", "E", "H"]
    env = _search(mcp, filters={})
    assert markers(env["results"]) == ["A", "C", "E", "H"]
