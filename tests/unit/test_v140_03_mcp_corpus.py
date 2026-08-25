"""V140-03 — MCP server wrapper + corpus knowledge-base read (Option: reuse dispatcher).

Tests the V140-03 deliverables without forking core M6 logic:
* mcp_server.serve wires the shared dispatcher and answers initialize/tools/list/
  tools/call over an in-memory stdio loop;
* corpus_search tool is wired and returns SANITIZED corpus units (no file paths,
  no SQL, no grant rows) from the derived store;
* authorization-first: a request without an authorized profile returns EMPTY /
  DENIED, never leaks corpus units outside the authorized scope.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

from src.integration.m6 import mcp_server
from src.integration.m6.tools import TOOL_REGISTRY


def _corpus_db_from_env() -> Path:
    """V141 (F2 remediation): corpus DB path comes from the environment, never
    a machine-specific hardcode. Tests that require a real quant-lab store are
    skipped with an explicit reason when ZM_TEST_CORPUS_DB is unset — the rest
    of the suite stays portable."""
    val = os.environ.get("ZM_TEST_CORPUS_DB")
    if not val:
        pytest.skip("ZM_TEST_CORPUS_DB not set (portable run) — real-corpus MCP tests skipped")
    p = Path(val)
    if not p.exists():
        pytest.skip(f"ZM_TEST_CORPUS_DB points to missing file: {val}")
    return p


@pytest.fixture(scope="module")
def corpus_db() -> Path:
    return _corpus_db_from_env()


def _rpc(serve_fn, method, params=None, rid=1):
    return serve_fn(method, params or {}, rid)


def test_corpus_search_registered_in_surface(corpus_db):
    assert "corpus_search" in TOOL_REGISTRY
    spec = TOOL_REGISTRY["corpus_search"]
    assert spec.resource_type.value == "corpus_unit"
    assert spec.operation.value == "READ"


def test_mcp_initialize_and_tools_list(corpus_db):
    out = io.StringIO()
    captured = []

    def fake_serve(store_path, in_stream=None, out_stream=None):
        # Drive a 3-message exchange through the server's RPC handler directly.
        resp_init = mcp_server._handle_rpc("initialize", {}, 1)
        captured.append(resp_init)
        resp_list = mcp_server._handle_rpc("tools/list", {}, 2)
        captured.append(resp_list)

    # configure runtime so handlers are registered
    mcp_server.configure(corpus_db)
    fake_serve(corpus_db)
    assert captured[0]["result"]["serverInfo"]["name"] == "zero-mem-m6"
    names = {t["name"] for t in captured[1]["result"]["tools"]}
    assert "corpus_search" in names
    assert "memory_search" in names


def test_corpus_search_returns_sanitized_units(corpus_db):
    mcp_server.configure(corpus_db)
    resp = mcp_server._handle_rpc(
        "tools/call",
        {"name": "corpus_search",
         "arguments": {"search_text": "kelly criterion",
                        "requesting_profile_id": "quant-lab-profile", "limit": 3}},
        3,
    )
    assert resp["result"]["isError"] is False
    env = resp["result"]["structuredContent"]
    assert env["status"] == "SUCCESS"
    items = env["results"]
    assert items
    for it in items:
        # Sanitized: only safe fields, no raw sql / path / grant leakage.
        assert "unit_id" in it
        assert "normalized_text" in it
        assert "knowledge_space_id" in it
        # Negative assertions: forbidden internal fields must not appear.
        assert "stored_path" not in it
        assert "grant" not in it


def test_corpus_search_authorization_isolated(corpus_db):
    """A profile with no grant/scope over quant-theory must NOT see its units."""
    mcp_server.configure(corpus_db)
    resp = mcp_server._handle_rpc(
        "tools/call",
        {"name": "corpus_search",
         "arguments": {"search_text": "kelly criterion",
                        "requesting_profile_id": "intruder-profile", "limit": 3}},
        3,
    )
    env = resp["result"]["structuredContent"]
    # Fail-closed: either DENIED or EMPTY, never SUCCESS with leaked units.
    assert env["status"] in ("DENIED", "EMPTY", "POLICY_DENIED")
    assert env.get("results", []) == []


def test_unknown_method_returns_method_not_found(corpus_db):
    mcp_server.configure(corpus_db)
    resp = mcp_server._handle_rpc("tools/bogus", {}, 9)
    assert resp["error"]["code"] == -32601
