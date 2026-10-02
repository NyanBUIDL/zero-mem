"""T15 - MCP ``memory_brief`` (default read set) and ``memory_propose`` (only with ``--enable-propose``).

In-process tool-set tests plus REAL stdio subprocesses: injection is off by default, the owner's settings.toml switches
it on per profile, identity / authority arguments are rejected, and a proposal is inert until the owner approves it.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

from src.integration.m6w import build_tool_set
from src.integration.m6w import contracts as c
from tests.unit.t5_memory_helpers import SECRET_TOKEN, Env
from tests.unit.t6b_helpers import AGENTS, McpProc, apply_env, isolated_env, registration
from zero_mem import cli
from zero_mem import learning_settings as ls
from zero_mem.learning import Reviewer
from zero_mem.memory_layout import Layout

BASE_READ_CHARS = 1577      # compact(tool_definitions(write=False)) before T15 (T8 pin was <= 1650)
BASE_WRITE_CHARS = 4543     # compact(tool_definitions(write=True)) before T15 (T8 pin was <= 4600)


def compact(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


# ================================================================ contracts / token budget
def test_the_default_read_tool_list_grows_by_at_most_450_characters():
    read = c.tool_definitions(write=False)
    assert [t["name"] for t in read] == ["memory_recall", "memory_context", "memory_brief"]
    growth = len(compact(read)) - BASE_READ_CHARS
    assert 0 < growth <= 450, growth
    assert len(compact(c.tool_definitions(write=True))) - BASE_WRITE_CHARS == growth  # only memory_brief was added
    brief = next(t for t in read if t["name"] == "memory_brief")
    assert brief["inputSchema"]["additionalProperties"] is False and "required" not in brief["inputSchema"]
    assert set(brief["inputSchema"]["properties"]) == {"task", "max_chars"}
    desc = brief["description"].lower()
    assert "start" in desc and "task" in desc and "read-only" in desc and "not instructions" in desc
    assert len(brief["description"]) <= 230


def test_propose_is_a_closed_schema_without_identity_or_authority_fields():
    tools = c.tool_definitions(write=False, propose=True)
    assert [t["name"] for t in tools] == ["memory_recall", "memory_context", "memory_brief", "memory_propose"]
    schema = tools[-1]["inputSchema"]
    assert schema["additionalProperties"] is False and schema["required"] == ["text", "memory_type", "scope"]
    assert set(schema["properties"]) == {"text", "memory_type", "name", "scope", "project_id", "evidence"}
    assert schema["properties"]["memory_type"]["enum"] == [t for t in c.MEMORY_TYPES if t != "file"]
    assert schema["properties"]["evidence"]["maxItems"] == 5
    for forbidden in c.IDENTITY_FIELDS | c.SCOPE_AUTHORITY_FIELDS | {"source", "status"}:
        assert forbidden not in schema["properties"]
    assert len(tools[-1]["description"]) <= 420 and "owner" in tools[-1]["description"].lower()
    both = c.tool_definitions(write=True, propose=True)
    assert [t["name"] for t in both] == ["memory_recall", "memory_context", "memory_brief", "memory_add",
                                         "memory_ingest", "memory_forget", "memory_propose"]


# ================================================================ in-process tool set
@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    e.close()


@pytest.fixture
def settings(tmp_path, monkeypatch):
    path = tmp_path / "cfg" / "settings.toml"
    monkeypatch.setenv("ZERO_MEM_SETTINGS", str(path))
    return path


def toolset(env, profile="codex", **kw):
    env.prov.add_agent(profile)
    return build_tool_set(profile_id=profile, layout=env.layout, **kw)


def call(ts, tool, **arguments):
    result = ts.call(tool, arguments)
    return result["structuredContent"], result["content"][0]["text"], result["isError"]


def test_propose_is_not_mounted_unless_enabled(env, settings):
    ts = toolset(env, enable_write=True)
    assert "memory_propose" not in ts.names and not ts.handles("memory_propose")
    out, _t, err = call(ts, "memory_propose", text="x y", memory_type="rule", scope="shared")
    assert err and out["reason_code"] == "UNKNOWN_TOOL"
    ts = toolset(env, "claude-code", enable_propose=True)
    assert list(ts.names) == ["memory_recall", "memory_context", "memory_brief", "memory_propose"]
    assert ts.propose_enabled and "memory_propose" in ts.instructions and "owner" in ts.instructions


def test_brief_is_empty_with_a_reason_until_the_owner_enables_injection(env, settings):
    ts = toolset(env, enable_write=True)
    env.prov.grant_write("codex", space="ks-shared")
    call(ts, "memory_add", text="Never force push to main.", memory_type="rule", name="nofp", scope="shared")
    out, text, err = call(ts, "memory_brief", task="push my change")
    assert err is False and out["status"] == "EMPTY" and out["reason_code"] == "injection_disabled" and "text" not in out
    assert "injection_disabled" in text
    ls.set_value("injection.enabled", "true", settings)
    out, text, err = call(ts, "memory_brief", task="push my change")
    assert out["status"] == "SUCCESS" and err is False and out["text"] == text
    assert text.startswith("## Rules\n- mem://rule/nofp: Never force push to main.")
    assert set(out) <= {"status", "text", "truncated"}
    ls.set_value("safety.kill_switch", "true", settings)
    assert call(ts, "memory_brief")[0]["reason_code"] == "kill_switch"


def test_brief_validates_and_rejects_identity(env, settings):
    ts = toolset(env)
    ls.set_value("injection.enabled", "true", settings)
    for bad in ({"max_chars": 0}, {"max_chars": 8001}, {"max_chars": "5"}, {"task": 5}, {"nope": 1}):
        out, _t, err = call(ts, "memory_brief", **bad)
        assert err and out["status"] == "INVALID", bad
    for spoof in ({"profile_id": "codex"}, {"agent": "x"}, {"requesting_profile_id": "other"}):
        out, _t, err = call(ts, "memory_brief", **spoof)
        assert err and out["status"] == "DENIED" and out["reason_code"] == "DENY_IDENTITY_PINNED"
    assert call(ts, "memory_brief", max_chars=200)[0]["status"] in ("SUCCESS", "EMPTY")
    assert call(ts, "memory_brief", task="x " * 3000)[0]["status"] in ("SUCCESS", "EMPTY")  # a long task is clipped


def test_propose_returns_an_inert_pending_result_and_nothing_is_recallable(env, settings):
    ts = toolset(env, enable_propose=True)
    out, text, err = call(ts, "memory_propose", text="Prefer small pull requests about falcons.", memory_type="rule",
                          name="small-prs", scope="shared", evidence=["review of PR 12"])
    assert err is False and out["status"] == "PROPOSED" and out["proposal_id"].startswith("p-")
    assert set(out) == {"status", "proposal_id", "message"} and "owner" in out["message"].lower()
    assert call(ts, "memory_recall", query="falcons")[0]["status"] == "EMPTY"
    assert env.registry_lines() == []  # nothing became a source
    again, _t, err = call(ts, "memory_propose", text="Prefer small pull requests about falcons.", memory_type="rule",
                          name="small-prs", scope="shared")
    assert err is False and again["proposal_id"] == out["proposal_id"] and again["status"] == "PROPOSED"
    memory = env.open("codex", settings_path=settings)
    assert len(memory.proposals("pending")) == 1 and memory.proposals("pending")[0]["source"] == "agent"


def test_propose_rejections_are_errors_with_a_reason_and_nothing_is_stored(env, settings):
    ts = toolset(env, enable_propose=True)
    out, _t, err = call(ts, "memory_propose", text=f"use {SECRET_TOKEN}", memory_type="rule", scope="shared")
    assert err and out["status"] == "REJECTED_SECRET" and "proposal_id" not in out and SECRET_TOKEN not in json.dumps(out)
    ls.set_value("learning.mode", "off", settings)
    out, text, err = call(ts, "memory_propose", text="a rule here", memory_type="rule", scope="shared")
    assert err and out["status"] == "REJECTED" and out["reason_code"] == "learning_off" and "learning_off" in text
    ls.set_value("learning.mode", "suggest", settings)
    ls.set_value("safety.kill_switch", "true", settings)
    out, _t, err = call(ts, "memory_propose", text="a rule here", memory_type="rule", scope="shared")
    assert err and out["reason_code"] == "kill_switch"
    ls.set_value("safety.kill_switch", "false", settings)
    ls.set_value("learning.allow_agent_proposals", "false", settings)
    out, _t, err = call(ts, "memory_propose", text="a rule here", memory_type="rule", scope="shared")
    assert err and out["reason_code"] == "agent_proposals_disallowed"
    ls.unset_value("learning.allow_agent_proposals", settings)
    ls.set_value("learning.max_proposals_per_day", "1", settings)
    assert call(ts, "memory_propose", text="first rule here", memory_type="rule", scope="shared")[0]["status"] == "PROPOSED"
    out, _t, err = call(ts, "memory_propose", text="second rule here", memory_type="rule", scope="shared")
    assert err and out["reason_code"] == "daily_limit"
    out, _t, err = call(ts, "memory_propose", text="x", memory_type="rule", scope="project")
    assert err and out["status"] == "INVALID" and out["reason_code"] == "project_id_required"
    out, _t, err = call(ts, "memory_propose", text="x", memory_type="file", scope="shared")
    assert err and out["status"] == "INVALID"
    assert env.registry_lines() == []


def test_propose_rejects_identity_authority_and_unknown_arguments(env, settings):
    ts = toolset(env, enable_propose=True)
    base = {"text": "a rule here", "memory_type": "rule", "scope": "shared"}
    for extra, status, reason in (
        ({"profile_id": "claude-code"}, "DENIED", "DENY_IDENTITY_PINNED"),
        ({"agent_id": "x"}, "DENIED", "DENY_IDENTITY_PINNED"),
        ({"knowledge_space_id": "ks-shared"}, "DENIED", "DENY_SCOPE_NOT_CALLER_CONTROLLED"),
        ({"approval_ref": "ok"}, "DENIED", "DENY_SCOPE_NOT_CALLER_CONTROLLED"),
        ({"source": "user"}, "INVALID", "UNKNOWN_ARGUMENT"),
        ({"status": "approved"}, "INVALID", "UNKNOWN_ARGUMENT"),
    ):
        out, _t, err = call(ts, "memory_propose", **base, **extra)
        assert err and out["status"] == status and out["reason_code"] == reason, extra
    assert call(ts, "memory_propose", text="a rule here", memory_type="rule", scope="shared",
                evidence=["e"] * 6)[0]["status"] == "INVALID"
    assert env.open("codex", settings_path=settings).proposals() == []


# ================================================================ real stdio subprocesses
@pytest.fixture
def home(tmp_path, monkeypatch):
    apply_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ZERO_MEM_SETTINGS", str(tmp_path / "cfg" / "settings.toml"))
    assert cli.main(["setup"]) == 0
    for profile in ("codex", "claude-code"):
        assert cli.main(["agents", "add", profile]) == 0
    assert cli.main(["agents", "grant-write", "codex", "--space", "ks-shared", "--yes"]) == 0
    return tmp_path


def senv(home):
    return {**isolated_env(home), "ZERO_MEM_SETTINGS": str(home / "cfg" / "settings.toml")}


def serve(home, *flags, profile="codex"):
    return McpProc(sys.executable, ["-m", "zero_mem.cli", "serve", "--profile", profile, *flags], senv(home), cwd=home)


def test_stdio_brief_is_off_by_default_then_on_per_profile_and_tools_list_is_tiny(home):
    assert cli.main(["--profile", "codex", "add", "Never force push to main.", "--type", "rule", "--scope", "shared",
                     "--name", "nofp"]) == 0
    with serve(home) as srv:
        srv.initialize()
        reply = srv.rpc("tools/list", {})["result"]
        assert [t["name"] for t in reply["tools"]] == ["memory_recall", "memory_context", "memory_brief"]
        assert len(compact(reply)) <= BASE_READ_CHARS + 450 + 40  # the reply wrapper adds a few characters
        off = srv.env("memory_brief", {"task": "push to main"})
        assert off["status"] == "EMPTY" and off["reason_code"] == "injection_disabled"
        ls.set_value("injection.profiles.codex.enabled", "true", home / "cfg" / "settings.toml")
        on = srv.env("memory_brief", {"task": "push to main"})
        assert on["status"] == "SUCCESS" and "mem://rule/nofp" in on["text"]
    with serve(home, profile="claude-code") as other:  # the override was for codex only
        other.initialize()
        assert other.env("memory_brief", {})["reason_code"] == "injection_disabled"


def test_stdio_spoofed_identity_is_rejected_on_the_new_tools(home):
    with serve(home, "--enable-propose") as srv:
        srv.initialize()
        for tool, args in (("memory_brief", {"profile_id": "claude-code"}),
                           ("memory_propose", {"text": "a rule here", "memory_type": "rule", "scope": "shared",
                                               "requesting_profile_id": "claude-code"})):
            result = srv.call(tool, args)
            assert result["isError"] is True and result["structuredContent"]["reason_code"] == "DENY_IDENTITY_PINNED"


def test_stdio_propose_is_only_mounted_with_the_flag_or_env(home):
    with serve(home) as srv:
        srv.initialize()
        assert "memory_propose" not in srv.tool_names()
        res = srv.call("memory_propose", {"text": "x", "memory_type": "rule", "scope": "shared"})
        assert res["isError"] is True and res["structuredContent"]["status"] == "UNSUPPORTED_TOOL"
    with serve(home, "--enable-propose") as srv:
        srv.initialize()
        assert srv.tool_names() == ["memory_recall", "memory_context", "memory_brief", "memory_propose"]
    with serve(home, "--enable-write", "--enable-propose") as srv:
        srv.initialize()
        assert srv.tool_names()[-1] == "memory_propose" and len(srv.tool_names()) == 7
    env = {**senv(home), "ZM_M6_ENABLE_PROPOSE": "1"}
    with McpProc(sys.executable, ["-m", "src.integration.m6.mcp_server", "--profile-id", "codex",
                                  "--enable-memory", "--tools", "memory"], env, cwd=home) as srv:
        srv.initialize()
        assert srv.tool_names()[-1] == "memory_propose"


def test_stdio_propose_then_pending_then_owner_approves_then_brief_includes_it(home):
    cfg = home / "cfg" / "settings.toml"
    ls.set_value("injection.enabled", "true", cfg)
    with serve(home, "--enable-propose", profile="claude-code") as srv:  # no write grant at all
        srv.initialize()
        out = srv.env("memory_propose", {"text": "Prefer small pull requests about falcons.", "memory_type": "rule",
                                         "name": "small-prs", "scope": "shared"})
        assert out["status"] == "PROPOSED"
        assert srv.env("memory_recall", {"query": "falcons"})["status"] == "EMPTY"  # pending: not recallable
        assert "falcons" not in json.dumps(srv.call("memory_brief", {"task": "falcons"}))
        reviewer = Reviewer(Layout.resolve(None), operator="owner", settings_path=cfg)
        assert reviewer.list()[0]["id"] == out["proposal_id"]
        assert reviewer.approve(out["proposal_id"]).status == "approved"  # the OWNER, out of band
        brief = srv.env("memory_brief", {"task": "falcons"})
        assert brief["status"] == "SUCCESS" and "mem://rule/small-prs" in brief["text"] and "falcons" in brief["text"]
        assert srv.env("memory_recall", {"query": "falcons"})["status"] == "SUCCESS"


# ================================================================ serve / mcp-config
@pytest.fixture
def execs(monkeypatch):
    from zero_mem import commands_mcp

    calls = []
    monkeypatch.setattr(commands_mcp.os, "execv", lambda exe, argv: calls.append((exe, list(argv))))
    return calls


def test_serve_forwards_enable_propose(home, execs):
    assert cli.main(["serve", "--profile", "codex"]) == 0
    assert cli.main(["serve", "--profile", "codex", "--enable-propose"]) == 0
    assert "--enable-propose" not in execs[0][1] and "--enable-propose" in execs[1][1]


@pytest.mark.parametrize("agent", AGENTS)
def test_mcp_config_surfaces_the_propose_flag(home, agent):
    plain, reg = registration(agent), registration(agent, "--enable-propose")
    assert plain["propose_enabled"] is False and "--enable-propose" not in plain["args"]
    assert reg["propose_enabled"] is True and reg["args"][-1] == "--enable-propose"
    assert "--enable-propose" in json.dumps(reg["snippets"])
    both = registration(agent, "--enable-write", "--enable-propose")
    assert both["args"][-2:] == ["--enable-write", "--enable-propose"]
    import contextlib
    import io

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert cli.main(["mcp-config", "--agent", agent, "--enable-propose"]) == 0
    assert "memory_propose" in out.getvalue() and "zero-mem review" in out.getvalue()


def test_the_printed_registration_with_propose_starts_a_server_with_it(home):
    reg = registration("codex", "--enable-propose")
    with McpProc(reg["command"], reg["args"], {**reg["env"], **senv(home)}, cwd=home) as srv:
        srv.initialize()
        assert srv.tool_names()[-1] == "memory_propose"
