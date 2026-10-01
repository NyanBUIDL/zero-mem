"""DEF-052 - the MCP server pins the requesting profile server-side.

Before: ``requesting_profile_id`` came from the tool-call arguments, so any client
could pass ``codex`` and read codex-private rows.  Now ``--profile-id`` /
``ZM_M6_PROFILE_ID`` fixes the identity for the whole server process:

  * the pinned value overwrites ``arguments.requesting_profile_id``;
  * a different caller-supplied value is REJECTED with a structured error
    (``isError`` true, ``POLICY_DENIED`` / ``DENY_IDENTITY_PINNED``), never
    silently replaced;
  * ``requesting_profile_id`` is dropped from every ``tools/list`` schema;
  * ``--default-ks`` / ``ZM_M6_DEFAULT_KS`` is applied to ``corpus_search`` only
    when the caller omits ``knowledge_space_ids``;
  * unpinned keeps today's behaviour but warns on stderr and reports
    ``serverInfo.identity = "unpinned"``.

Everything below drives a REAL server subprocess over stdio JSON-RPC (pipes).
"""
from __future__ import annotations

import pytest

from tests.unit.t6a_mcp_helpers import StdioServer, build_matrix_store, markers

SEARCH = {"search_text": "zebra", "limit": 50}


@pytest.fixture()
def db(tmp_path):
    return build_matrix_store(tmp_path)


def _env(resp):
    return resp["result"]["structuredContent"]


class TestPinnedByFlag:
    def test_server_info_reports_pinned_and_no_warning(self, db):
        with StdioServer(["--store-path", str(db), "--profile-id", "claude-code"]) as srv:
            info = srv.initialize()["result"]["serverInfo"]
            assert info["identity"] == "pinned"
            assert info["name"] == "zero-mem-m6"
            err = srv.close()
        assert "unpinned" not in err.lower()

    def test_requesting_profile_id_is_removed_from_every_schema(self, db):
        with StdioServer(["--store-path", str(db), "--profile-id", "claude-code"]) as srv:
            tools = srv.tools_list()
        assert len(tools) == 11
        for tool in tools:
            assert "requesting_profile_id" not in tool["inputSchema"]["properties"], tool["name"]

    def test_omitted_identity_is_filled_from_the_pin(self, db):
        with StdioServer(["--store-path", str(db), "--profile-id", "claude-code"]) as srv:
            resp = srv.call("corpus_search", dict(SEARCH))
        assert resp["result"]["isError"] is False
        assert markers(_env(resp)["results"]) == ["A", "C", "E", "H"]

    def test_matching_caller_value_is_accepted(self, db):
        with StdioServer(["--store-path", str(db), "--profile-id", "claude-code"]) as srv:
            resp = srv.call("corpus_search", {**SEARCH, "requesting_profile_id": "claude-code"})
        assert resp["result"]["isError"] is False
        assert markers(_env(resp)["results"]) == ["A", "C", "E", "H"]

    def test_null_caller_value_is_treated_as_omitted(self, db):
        with StdioServer(["--store-path", str(db), "--profile-id", "claude-code"]) as srv:
            resp = srv.call("corpus_search", {**SEARCH, "requesting_profile_id": None})
        assert markers(_env(resp)["results"]) == ["A", "C", "E", "H"]

    @pytest.mark.parametrize("other", ["codex", "hermes", "", "claude-code ", "*"])
    def test_other_caller_value_is_rejected_with_a_structured_error(self, db, other):
        with StdioServer(["--store-path", str(db), "--profile-id", "claude-code"]) as srv:
            resp = srv.call("corpus_search", {**SEARCH, "requesting_profile_id": other})
        assert "error" not in resp  # a tool-level error, not a transport failure
        assert resp["result"]["isError"] is True
        env = _env(resp)
        assert env["status"] == "POLICY_DENIED"
        assert env["reason_code"] == "DENY_IDENTITY_PINNED"
        assert env.get("results", []) == []

    def test_cannot_read_another_profiles_private_rows_by_any_route(self, db):
        """D is codex's private row; it must never reach a claude-code-pinned server."""
        attempts = [
            {**SEARCH, "requesting_profile_id": "codex"},                   # impersonate
            {**SEARCH, "target_profile_ids": ["codex"]},                    # ask for codex
            {**SEARCH, "target_profile_ids": ["codex"],
             "requesting_profile_id": "codex"},                              # both
            {**SEARCH, "knowledge_space_ids": ["ks-shared"]},               # shared space
            {**SEARCH},                                                     # implicit
        ]
        with StdioServer(["--store-path", str(db), "--profile-id", "claude-code"]) as srv:
            for args in attempts:
                for tool in ("corpus_search", "memory_search"):
                    resp = srv.call(tool, dict(args))
                    got = markers(_env(resp).get("results", [])) if tool == "corpus_search" else []
                    assert "D" not in got, (tool, args, got)
                    assert "G" not in got, (tool, args, got)
        # the denied routes really were denied, not just empty
        with StdioServer(["--store-path", str(db), "--profile-id", "claude-code"]) as srv:
            assert _env(srv.call("corpus_search", attempts[0]))["status"] == "POLICY_DENIED"
            assert _env(srv.call("corpus_search", attempts[1]))["status"] == "POLICY_DENIED"

    def test_pinned_identity_applies_to_every_tool(self, db):
        """Event/project tools are pinned too (rejected, not silently re-bound)."""
        with StdioServer(["--store-path", str(db), "--profile-id", "claude-code"]) as srv:
            for tool in ("memory_query", "memory_search", "project_get_state"):
                resp = srv.call(tool, {"requesting_profile_id": "codex", "search_text": "x",
                                       "project_ids": ["p"]})
                assert resp["result"]["isError"] is True, tool
                assert _env(resp)["reason_code"] == "DENY_IDENTITY_PINNED", tool


class TestPinnedByEnvironment:
    def test_env_var_pins_the_identity(self, db):
        with StdioServer(["--store-path", str(db)],
                         env={"ZM_M6_PROFILE_ID": "codex"}) as srv:
            assert srv.initialize()["result"]["serverInfo"]["identity"] == "pinned"
            resp = srv.call("corpus_search", dict(SEARCH))
            assert markers(_env(resp)["results"]) == ["B", "D", "E", "G"]
            denied = srv.call("corpus_search", {**SEARCH, "requesting_profile_id": "claude-code"})
            assert denied["result"]["isError"] is True

    def test_flag_wins_over_env(self, db):
        with StdioServer(["--store-path", str(db), "--profile-id", "claude-code"],
                         env={"ZM_M6_PROFILE_ID": "codex"}) as srv:
            resp = srv.call("corpus_search", dict(SEARCH))
        assert markers(_env(resp)["results"]) == ["A", "C", "E", "H"]

    @pytest.mark.parametrize("bad", ["   ", "x" * 257, "a\nb"])
    def test_malformed_pin_refuses_to_start(self, db, bad):
        srv = StdioServer(["--store-path", str(db), "--profile-id", bad])
        err = srv.close()
        assert srv.proc.returncode == 2
        assert "profile-id" in err.lower()


class TestDefaultKnowledgeSpace:
    def test_default_ks_applies_when_omitted(self, db):
        args = ["--store-path", str(db), "--profile-id", "claude-code",
                "--default-ks", "ks-shared"]
        with StdioServer(args) as srv:
            resp = srv.call("corpus_search", dict(SEARCH))
        assert markers(_env(resp)["results"]) == ["A", "B", "E", "F"]

    def test_default_ks_from_env(self, db):
        with StdioServer(["--store-path", str(db), "--profile-id", "claude-code"],
                         env={"ZM_M6_DEFAULT_KS": "ks-shared"}) as srv:
            resp = srv.call("corpus_search", dict(SEARCH))
        assert markers(_env(resp)["results"]) == ["A", "B", "E", "F"]

    def test_explicit_spaces_win_and_empty_list_opts_out(self, db):
        args = ["--store-path", str(db), "--profile-id", "claude-code",
                "--default-ks", "ks-shared"]
        with StdioServer(args) as srv:
            other = _env(srv.call("corpus_search",
                                  {**SEARCH, "knowledge_space_ids": ["ks-other"]}))
            assert markers(other["results"]) == ["E", "H"]  # no grant on ks-other
            private = _env(srv.call("corpus_search", {**SEARCH, "knowledge_space_ids": []}))
            assert markers(private["results"]) == ["A", "C", "E", "H"]

    def test_default_ks_is_not_applied_to_other_tools(self, db):
        args = ["--store-path", str(db), "--profile-id", "claude-code",
                "--default-ks", "ks-shared"]
        with StdioServer(args) as srv:
            resp = srv.call("memory_query", {"limit": 5})
        # event tools would otherwise be filtered to a space no event has
        assert _env(resp)["status"] in ("EMPTY", "SUCCESS")
        assert resp["result"]["isError"] is False


class TestUnpinned:
    def test_unpinned_warns_once_and_reports_it(self, db):
        with StdioServer(["--store-path", str(db)]) as srv:
            info = srv.initialize()["result"]["serverInfo"]
            err = srv.close()
        assert info["identity"] == "unpinned"
        warnings = [ln for ln in err.splitlines() if "unpinned" in ln.lower()]
        assert len(warnings) == 1, err
        assert "--profile-id" in warnings[0] and "ZM_M6_PROFILE_ID" in warnings[0]

    def test_unpinned_keeps_todays_behaviour(self, db):
        with StdioServer(["--store-path", str(db)]) as srv:
            tools = srv.tools_list()
            assert all("requesting_profile_id" in t["inputSchema"]["properties"] for t in tools)
            resp = srv.call("corpus_search", {**SEARCH, "requesting_profile_id": "codex"})
        # the documented risk: the caller chooses the identity (hence the warning)
        assert markers(_env(resp)["results"]) == ["B", "D", "E", "G"]
