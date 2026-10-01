"""DEF-062 - MCP transport defects.

1. ``isError`` tested ``"DENIED"`` but the real status is ``POLICY_DENIED`` (and
   ``DOWNSTREAM_ERROR`` etc.), so denials looked like successes to clients.
2. ``arguments.tool`` overrode the called tool name (defeats per-tool allowlists in
   clients such as ``mcp__zero-mem__corpus_search``).
3. ``inputSchema`` required a redundant ``tool``; descriptions were the generic
   ``Zero-Mem read tool: <name>``.
4. The full envelope was sent twice (``content`` text + ``structuredContent``).
5. ``python src/integration/m6/mcp_server.py`` failed from any other cwd
   (``zero_mem`` was imported before the sys.path fallback).
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from src.integration.m6 import mcp_server, mcp_wrapper
from src.integration.m6.contracts import ResponseStatus
from src.integration.m6.dispatcher import Dispatcher
from src.integration.m6.tools import TOOL_REGISTRY
from tests.unit.t3_corpus_helpers import build_store, doc
from tests.unit.t6a_mcp_helpers import (
    REPO_ROOT, StdioServer, build_matrix_store, call_tool, configure_inprocess,
    envelope_of, markers,
)

OK_STATUSES = {ResponseStatus.SUCCESS.value, ResponseStatus.EMPTY.value}


@pytest.fixture()
def mcp(tmp_path):
    return configure_inprocess(build_matrix_store(tmp_path))


# --------------------------------------------------------------------------
# 1. isError for every real status
# --------------------------------------------------------------------------
@pytest.mark.parametrize("status", [s.value for s in ResponseStatus])
def test_is_error_for_every_envelope_status(monkeypatch, status):
    monkeypatch.setattr(mcp_server, "handle_call",
                        lambda tool, arguments, dispatcher=None: {"status": status})
    resp = mcp_server._handle_rpc(
        "tools/call", {"name": "corpus_search", "arguments": {"search_text": "x"}}, 1)
    assert resp["result"]["isError"] is (status not in OK_STATUSES), status
    assert resp["result"]["structuredContent"]["status"] == status


def test_policy_denied_is_an_error_through_the_real_path(mcp):
    resp = call_tool(mcp, "corpus_search", {
        "search_text": "zebra", "requesting_profile_id": "claude-code",
        "target_profile_ids": ["codex"]})
    assert envelope_of(resp)["status"] == "POLICY_DENIED"
    assert resp["result"]["isError"] is True


def test_empty_and_success_are_not_errors(mcp):
    empty = call_tool(mcp, "corpus_search", {
        "search_text": "nothingmatchesthis", "requesting_profile_id": "claude-code"})
    assert envelope_of(empty)["status"] == "EMPTY"
    assert empty["result"]["isError"] is False
    ok = call_tool(mcp, "corpus_search", {
        "search_text": "zebra", "requesting_profile_id": "claude-code"})
    assert envelope_of(ok)["status"] == "SUCCESS"
    assert ok["result"]["isError"] is False


def test_invalid_unsupported_and_downstream_are_errors(mcp, monkeypatch):
    invalid = call_tool(mcp, "corpus_search", {"requesting_profile_id": "claude-code"})
    assert envelope_of(invalid)["status"] == "INVALID_REQUEST"
    assert invalid["result"]["isError"] is True
    unknown = call_tool(mcp, "no_such_tool", {})
    assert envelope_of(unknown)["status"] == "UNSUPPORTED_TOOL"
    assert unknown["result"]["isError"] is True
    write = call_tool(mcp, "corpus_search", {"search_text": "x", "operation": "WRITE"})
    assert envelope_of(write)["status"] == "UNSUPPORTED_OPERATION"
    assert write["result"]["isError"] is True

    boom = Dispatcher()
    boom.register("corpus_search", lambda req: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(mcp_server, "_make_dispatcher", lambda: boom)
    down = call_tool(mcp, "corpus_search", {"search_text": "x"})
    assert envelope_of(down)["status"] == "DOWNSTREAM_ERROR"
    assert down["result"]["isError"] is True

    monkeypatch.setattr(mcp_server, "_make_dispatcher", lambda: Dispatcher())
    unwired = call_tool(mcp, "corpus_search", {"search_text": "x"})
    assert envelope_of(unwired)["status"] == "CAPABILITY_UNAVAILABLE"
    assert unwired["result"]["isError"] is True


# --------------------------------------------------------------------------
# 2. arguments.tool never overrides the called tool
# --------------------------------------------------------------------------
def test_arguments_tool_cannot_redirect_the_call(mcp):
    resp = call_tool(mcp, "corpus_search", {
        "tool": "memory_search", "search_text": "zebra",
        "requesting_profile_id": "claude-code"})
    env = envelope_of(resp)
    assert env["diagnostics"]["tool"] == "corpus_search"
    assert env["status"] == "SUCCESS"
    assert all("normalized_text" in item for item in env["results"])  # corpus units


def test_arguments_tool_cannot_redirect_to_a_forbidden_or_unknown_tool(mcp):
    resp = call_tool(mcp, "corpus_search", {
        "tool": "execute_sql", "search_text": "zebra", "requesting_profile_id": "claude-code"})
    env = envelope_of(resp)
    assert env["status"] == "SUCCESS" and env["diagnostics"]["tool"] == "corpus_search"


def test_wrapper_handle_call_forces_the_called_tool_name(mcp):
    out = mcp_wrapper.handle_call("corpus_search", {
        "tool": "memory_get_event", "search_text": "zebra", "requesting_profile_id": "codex"},
        dispatcher=mcp_server._make_dispatcher())
    assert out["diagnostics"]["tool"] == "corpus_search"
    # the matching name keeps working
    same = mcp_wrapper.handle_call("corpus_search", {
        "tool": "corpus_search", "search_text": "zebra", "requesting_profile_id": "codex"},
        dispatcher=mcp_server._make_dispatcher())
    assert same["status"] == "SUCCESS"


# --------------------------------------------------------------------------
# 3. inputSchema + descriptions
# --------------------------------------------------------------------------
class TestSchemas:
    def test_tool_is_not_required_but_still_documented_as_const(self):
        for schema in mcp_wrapper.tool_schemas():
            inp = schema["inputSchema"]
            assert "tool" not in inp.get("required", []), schema["name"]
            assert inp["properties"]["tool"]["const"] == schema["name"]
            assert inp["properties"]["operation"]["const"] == "READ"
            assert inp["additionalProperties"] is False

    def test_search_tools_require_search_text(self):
        by_name = {s["name"]: s for s in mcp_wrapper.tool_schemas()}
        for name in ("corpus_search", "memory_search"):
            assert by_name[name]["inputSchema"]["required"] == ["search_text"], name
        for name in set(by_name) - {"corpus_search", "memory_search"}:
            assert not by_name[name]["inputSchema"].get("required"), name

    def test_every_tool_has_a_specific_bounded_description(self):
        descriptions = {}
        for schema in mcp_wrapper.tool_schemas():
            text = schema["description"]
            assert not text.startswith("Zero-Mem read tool:"), schema["name"]
            assert 80 <= len(text) <= 900, (schema["name"], len(text))
            descriptions[schema["name"]] = text
        assert len(set(descriptions.values())) == len(descriptions)
        assert set(descriptions) == set(TOOL_REGISTRY)

    def test_descriptions_say_when_to_call_and_which_args(self):
        by_name = {s["name"]: s["description"] for s in mcp_wrapper.tool_schemas()}
        corpus = by_name["corpus_search"]
        for needle in ("search_text", "limit", "memory_type", "external_ref_prefix",
                       "knowledge_space_ids"):
            assert needle in corpus, needle
        assert "Use" in corpus or "Call" in corpus
        for name in ("project_get_charter", "project_get_state", "project_list_requirements",
                     "project_list_decisions", "project_list_verifications",
                     "project_list_artifacts"):
            assert "project_ids" in by_name[name], name
        assert "event_id" in by_name["memory_get_event"]
        assert "event_id" in by_name["memory_get_related"]
        assert "relation" in by_name["memory_get_related"]

    def test_tools_list_payload_stays_small(self):
        assert len(json.dumps(mcp_wrapper.tool_schemas())) < 20_000

    def test_pinned_schema_drops_the_identity_property(self):
        for schema in mcp_wrapper.tool_schemas(include_identity=False):
            assert "requesting_profile_id" not in schema["inputSchema"]["properties"]
        for schema in mcp_wrapper.tool_schemas():
            assert "requesting_profile_id" in schema["inputSchema"]["properties"]


# --------------------------------------------------------------------------
# 4. one copy of the envelope
# --------------------------------------------------------------------------
class TestEnvelopeSentOnce:
    def _big(self, tmp_path):
        ro = build_store(tmp_path, [doc(f"zebra note number {i}") for i in range(40)])
        return configure_inprocess(ro.path)

    def test_text_is_a_short_summary_and_structured_content_is_the_envelope(self, tmp_path):
        server = self._big(tmp_path)
        resp = call_tool(server, "corpus_search", {
            "search_text": "zebra", "requesting_profile_id": "p1", "limit": 30})
        result = resp["result"]
        env = result["structuredContent"]
        assert env["status"] == "SUCCESS" and len(env["results"]) == 30
        (block,) = result["content"]
        text = block["text"]
        assert block["type"] == "text"
        assert json.dumps(env, ensure_ascii=False) not in text
        assert len(text) < 0.25 * len(json.dumps(env, ensure_ascii=False))
        assert len(text) <= 2400
        assert "SUCCESS" in text and "30" in text and "corpus_search" in text
        # not parseable as the envelope (it is a summary, not a second copy)
        with pytest.raises(ValueError):
            json.loads(text)

    def test_summary_of_a_denial_names_status_and_reason(self, mcp):
        resp = call_tool(mcp, "corpus_search", {
            "search_text": "zebra", "requesting_profile_id": "claude-code",
            "target_profile_ids": ["codex"]})
        text = resp["result"]["content"][0]["text"]
        assert "POLICY_DENIED" in text
        assert envelope_of(resp)["reason_code"] in text

    def test_summary_previews_provenance_for_text_only_clients(self, mcp):
        resp = call_tool(mcp, "corpus_search", {
            "search_text": "zebra", "requesting_profile_id": "claude-code",
            "knowledge_space_ids": ["ks-shared"]})
        text = resp["result"]["content"][0]["text"]
        assert "mem://persona/a" in text and "marker-A" in text

    def test_the_poc_client_still_parses_the_result(self, tmp_path):
        db = build_matrix_store(tmp_path)
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "examples" / "mcp_client_poc.py"),
             "--store-path", str(db), "--tool", "corpus_search",
             "--arguments", json.dumps({"search_text": "zebra",
                                         "requesting_profile_id": "claude-code"})],
            cwd=str(tmp_path), capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stderr
        printed = json.loads(proc.stdout)
        assert printed["structuredContent"]["status"] == "SUCCESS"
        assert markers(printed["structuredContent"]["results"]) == ["A", "C", "E", "H"]
        assert printed["isError"] is False


# --------------------------------------------------------------------------
# 5. direct script start from any cwd
# --------------------------------------------------------------------------
class TestStartModes:
    def test_direct_script_start_from_a_foreign_cwd(self, tmp_path):
        db = build_matrix_store(tmp_path)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        with StdioServer(["--store-path", str(db), "--profile-id", "claude-code"],
                         cwd=elsewhere, script=True) as srv:
            info = srv.initialize()["result"]["serverInfo"]
            assert info["name"] == "zero-mem-m6"
            resp = srv.call("corpus_search", {"search_text": "zebra"})
            assert markers(resp["result"]["structuredContent"]["results"]) == ["A", "C", "E", "H"]
            err = srv.close()
        assert "Traceback" not in err

    def test_module_start_still_works(self, tmp_path):
        db = build_matrix_store(tmp_path)
        with StdioServer(["--store-path", str(db)]) as srv:
            assert srv.initialize()["result"]["serverInfo"]["name"] == "zero-mem-m6"
            assert len(srv.tools_list()) == 11

    def test_module_start_from_a_foreign_cwd_with_pythonpath(self, tmp_path):
        db = build_matrix_store(tmp_path)
        elsewhere = tmp_path / "elsewhere2"
        elsewhere.mkdir()
        with StdioServer(["--store-path", str(db)], cwd=elsewhere) as srv:
            assert len(srv.tools_list()) == 11
