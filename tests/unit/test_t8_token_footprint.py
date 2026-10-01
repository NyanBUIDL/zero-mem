"""T8 - token footprint: the product goal is zero token cost, so what an agent session pays for the memory tools is a
tested budget (``tools/list`` schemas, ``initialize.instructions`` and the typical tool results).

* the memory-only tool set (``memory_recall``, ``memory_context`` and, with writes, ``memory_add`` / ``memory_ingest`` /
  ``memory_forget``) is the default of ``zero-mem serve`` and of the ``mcp-config`` output; the 11 legacy M6 tools
  (``corpus_search``, ``memory_query``, ``project_*``, ...) are only listed behind ``--tools all``;
* tool descriptions are short but keep the "when to call" guidance;
* ``memory_context`` defaults to 2000 characters;
* ``memory_recall`` hits are ``{id, type, ref, score, text}`` with the text trimmed to <= 300 characters (ellipsis,
  ``truncated`` flag) and the whole answer of a ``limit=8`` recall stays within 3 KB.
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import sys

import pytest

from src.integration.m6w import build_tool_set
from src.integration.m6w import contracts as c
from tests.unit.t5_memory_helpers import Env
from tests.unit.t6b_helpers import AGENTS, McpProc, apply_env, isolated_env, registration
from zero_mem import cli

BUDGET_3KB = 3 * 1024
LEGACY = {"corpus_search", "memory_get_event", "memory_get_related", "memory_query", "memory_search",
          "project_get_charter", "project_get_state", "project_list_artifacts", "project_list_decisions",
          "project_list_requirements", "project_list_verifications"}


def compact(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    e.close()


def toolset(env, profile="claude-code", write=True):
    env.prov.add_agent(profile)
    return build_tool_set(profile_id=profile, layout=env.layout, enable_write=write)


def call(ts, tool, **arguments):
    result = ts.call(tool, arguments)
    return result["structuredContent"], result["content"][0]["text"], result["isError"]


# ----------------------------------------------------------------------------------------------- schemas and prose
def test_the_memory_tool_schemas_fit_the_token_budget():
    write, read = c.tool_definitions(write=True), c.tool_definitions(write=False)
    assert [t["name"] for t in read] == ["memory_recall", "memory_context"]
    assert len(compact(write)) <= 4600, len(compact(write))  # was 6008 characters before T8
    assert len(compact(read)) <= 1650, len(compact(read))   # was 2182
    for tool in write:
        assert len(tool["description"]) <= 420, (tool["name"], len(tool["description"]))
        for name, prop in tool["inputSchema"]["properties"].items():
            assert len(prop["description"]) <= 150, (tool["name"], name)


def test_short_descriptions_keep_the_when_to_call_guidance():
    desc = {t["name"]: t["description"].lower() for t in c.tool_definitions(write=True)}
    assert "before asking" in desc["memory_recall"] and "not instructions" in desc["memory_recall"]
    assert "read-only" in desc["memory_recall"] and "read-only" in desc["memory_context"]
    assert "start of a session" in desc["memory_context"] and "memory_recall" in desc["memory_context"]
    assert "shared" in desc["memory_add"] and "operator" in desc["memory_add"] and "do not retry" in desc["memory_add"]
    assert "secret" in desc["memory_add"] and "same name" in desc["memory_add"]
    scope = next(t for t in c.tool_definitions(write=True) if t["name"] == "memory_add")["inputSchema"]["properties"]["scope"]
    assert "private = only you" in scope["description"] and "operator" in scope["description"]
    assert "absolute" in desc["memory_ingest"] and "allowed" in desc["memory_ingest"]
    assert "wrong or outdated" in desc["memory_forget"] and "operator" in desc["memory_forget"]


def test_the_initialize_instructions_are_short():
    assert len(c.SERVER_INSTRUCTIONS) <= 230
    assert len(c.SERVER_INSTRUCTIONS) + len(c.SERVER_INSTRUCTIONS_WRITE) <= 400
    assert "memory_context" in c.SERVER_INSTRUCTIONS and "memory_recall" in c.SERVER_INSTRUCTIONS


def test_the_context_default_is_2000_characters_and_advertised():
    assert c.CONTEXT_DEFAULT_CHARS == 2000
    schema = next(t for t in c.tool_definitions(write=False) if t["name"] == "memory_context")["inputSchema"]
    assert "2000" in schema["properties"]["max_chars"]["description"]
    assert schema["properties"]["max_chars"]["maximum"] == 4000


# ----------------------------------------------------------------------------------------------- recall payload
def _seed_long_hits(ts, n=12):
    for i in range(n):
        body = (f"Deployment note {i}: the wallaby service rolls out through staging first and then production, "
                "with health checks, a canary phase and an automatic rollback when the error rate rises. ") * 7
        out, _text, err = call(ts, "memory_add", text=body, memory_type="fact", scope="private")
        assert out["status"] == "SUCCESS" and not err


def test_a_limit_8_recall_answer_stays_within_3_kb(env):
    ts = toolset(env)
    _seed_long_hits(ts)
    out, text, err = call(ts, "memory_recall", query="wallaby rollout canary", limit=8)
    assert out["status"] == "SUCCESS" and not err and len(out["hits"]) == 8
    assert len(compact(out)) <= BUDGET_3KB, len(compact(out))   # was 4811 characters before T8
    assert len(text) <= BUDGET_3KB, len(text)
    for hit in out["hits"]:
        assert set(hit) == {"id", "type", "ref", "score", "text"}
        assert len(hit["text"]) <= 300 and hit["text"].endswith("…")
    assert out["truncated"] is True and set(out) <= {"status", "hits", "truncated", "warning"}


def test_short_hits_are_returned_whole_and_unflagged(env):
    ts = toolset(env)
    call(ts, "memory_add", text="Alice prefers PostgreSQL for storage.", memory_type="fact", scope="private")
    out, text, _err = call(ts, "memory_recall", query="postgresql")
    assert out["status"] == "SUCCESS" and "truncated" not in out
    assert out["hits"][0]["text"] == "Alice prefers PostgreSQL for storage."
    assert out["hits"][0]["type"] == "fact" and out["hits"][0]["ref"].startswith("mem://fact/")
    assert isinstance(out["hits"][0]["score"], float) and "Alice prefers PostgreSQL" in text


def test_the_recall_id_is_short_and_is_what_memory_forget_takes(env):
    ts = toolset(env)
    added, _t, _e = call(ts, "memory_add", text="Gazelles run very fast.", memory_type="fact", scope="private")
    hit = call(ts, "memory_recall", query="gazelles")[0]["hits"][0]
    assert re.fullmatch(r"[0-9a-f]{10}", hit["id"]) and added["id"] == hit["id"]
    gone, _t, err = call(ts, "memory_forget", source_id=hit["id"])
    assert gone["status"] == "SUCCESS" and gone["result"] == "forgotten" and not err
    assert call(ts, "memory_recall", query="gazelles")[0]["status"] == "EMPTY"


def test_a_long_hit_is_trimmed_around_the_part_that_matched(env):
    ts = toolset(env)
    text = ("Filler sentence about nothing in particular. " * 12) + "The zyzzyva beetle is the last word. " \
           + ("More filler sentence for padding. " * 8)
    call(ts, "memory_add", text=text, memory_type="fact", scope="private")
    hit = call(ts, "memory_recall", query="zyzzyva beetle")[0]["hits"][0]
    assert "zyzzyva" in hit["text"] and len(hit["text"]) <= 300
    assert hit["text"].startswith("…") and hit["text"].endswith("…")


def test_an_empty_recall_is_just_a_status(env):
    out, text, err = call(toolset(env), "memory_recall", query="nothing saved yet")
    assert out == {"status": "EMPTY"} and err is False and "EMPTY" in text


# ----------------------------------------------------------------------------------------------- context
def test_context_defaults_to_2000_characters_and_carries_only_what_the_model_needs(env):
    ts = toolset(env)
    env.prov.grant_write("claude-code", space="ks-shared")
    env.prov.grant_write("claude-code", project="zero-mem")
    filler = "the user likes concise, direct answers without filler words or emojis. " * 12
    for i in range(6):
        for kind in ("persona", "workflow"):
            added = call(ts, "memory_add", text=f"{kind} facet {i}: {filler}", memory_type=kind, name=f"{kind}{i}",
                         scope="shared")[0]
            assert added["status"] == "SUCCESS"
        skill = f"---\nname: skill{i}\ndescription: {filler}\n---\nSteps follow."
        assert call(ts, "memory_add", text=skill, memory_type="skill", name=f"skill{i}", scope="shared")[0]["status"] == "SUCCESS"
        assert call(ts, "memory_add", text=f"day {i}: {filler}", memory_type="devlog", scope="project",
                    project_id="zero-mem")[0]["status"] == "SUCCESS"
    out, text, _err = call(ts, "memory_context", project_id="zero-mem")
    assert out["status"] == "SUCCESS" and out["text"] == text
    assert 1700 <= len(text) <= 2000 and out["truncated"] is True
    assert set(out) == {"status", "text", "truncated"}  # no chars / max_chars / sections echo
    bigger = call(ts, "memory_context", max_chars=4000, project_id="zero-mem")[1]
    assert 2000 < len(bigger) <= 4000


def test_an_empty_context_is_small(env):
    out, _text, err = call(toolset(env), "memory_context")
    assert out["status"] == "EMPTY" and err is False and set(out) == {"status", "message"}


# ----------------------------------------------------------------------------------------------- compact write results
def test_write_results_drop_what_the_caller_already_knows(env):
    ts = toolset(env)
    added, _t, _e = call(ts, "memory_add", text="Remember the staging password policy.", memory_type="fact",
                         scope="private", name="policy")
    assert set(added) == {"status", "result", "ref", "id", "scope"} and added["ref"] == "mem://fact/policy"
    gone, _t, _e = call(ts, "memory_forget", source_id=added["id"])
    assert set(gone) == {"status", "result", "ref", "id"} and gone["result"] == "forgotten"


def test_failures_say_what_to_do_and_carry_no_tool_echo(env):
    ts = toolset(env)
    out, text, err = call(ts, "memory_add", text="shared persona", memory_type="persona", scope="shared")
    assert err is True and out["status"] == "DENIED" and "tool" not in out
    assert out["reason_code"] == "DENY_CROSS_PROFILE_WRITE" and "grant-write claude-code" in out["operator_hint"]
    assert text.startswith("memory_add: DENIED") and "grant-write claude-code --space ks-shared" in text


# ----------------------------------------------------------------------------------------------- --tools: serve / mcp-config
def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(list(argv))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


@pytest.fixture
def home(tmp_path, monkeypatch):
    apply_env(monkeypatch, tmp_path)
    return tmp_path


@pytest.fixture
def execs(monkeypatch):
    from zero_mem import commands_mcp

    calls = []
    monkeypatch.setattr(commands_mcp.os, "execv", lambda exe, argv: calls.append((exe, list(argv))))
    return calls


def test_serve_defaults_to_the_memory_only_tool_set_and_all_is_explicit(home, execs):
    assert run_cli("serve", "--profile", "codex")[0] == 0
    assert run_cli("serve", "--profile", "codex", "--tools", "all")[0] == 0
    default, everything = execs[0][1], execs[1][1]
    assert default[default.index("--tools") + 1] == "memory" and "--enable-memory" in default
    assert everything[everything.index("--tools") + 1] == "all"
    code, _out, err = run_cli("serve", "--profile", "codex", "--tools", "bogus")
    assert code == 2 and len(execs) == 2


def test_mcp_config_prints_the_memory_only_default_and_adds_tools_all_when_asked(home):
    default = registration("claude-code")
    assert default["tools"] == "memory" and "--tools" not in default["args"]
    assert default["args"] == ["-m", "zero_mem.cli", "serve", "--profile", "claude-code"]
    for agent in AGENTS:
        everything = registration(agent, "--tools", "all", "--enable-write")
        assert everything["tools"] == "all" and everything["args"][-2:] == ["--tools", "all"]
        assert "--tools" in json.dumps(everything["snippets"])


def test_serve_lists_only_the_memory_tools_by_default(home):
    with McpProc(sys.executable, ["-m", "zero_mem.cli", "serve", "--profile", "codex"],
                 isolated_env(home), cwd=home) as srv:
        srv.initialize()
        assert srv.tool_names() == ["memory_recall", "memory_context"]
        result = srv.call("corpus_search", {"query": "x"})  # a legacy tool is not exposed at all
        assert result["isError"] is True and result["structuredContent"]["status"] == "UNSUPPORTED_TOOL"
        assert srv.env("memory_recall", {"query": "nothing yet"})["status"] == "EMPTY"


def test_serve_with_writes_lists_five_tools_within_the_budget_and_all_lists_sixteen(home):
    env = isolated_env(home)
    with McpProc(sys.executable, ["-m", "zero_mem.cli", "serve", "--profile", "codex", "--enable-write"], env,
                 cwd=home) as srv:
        srv.initialize()
        reply = srv.rpc("tools/list", {})["result"]
        names = [t["name"] for t in reply["tools"]]
        assert names == ["memory_recall", "memory_context", "memory_add", "memory_ingest", "memory_forget"]
        assert not LEGACY & set(names)
        assert len(compact(reply)) <= 4700, len(compact(reply))  # was 22565 characters (16 tools) before T8
    with McpProc(sys.executable, ["-m", "zero_mem.cli", "serve", "--profile", "codex", "--enable-write",
                                  "--tools", "all"], env, cwd=home) as srv:
        srv.initialize()
        names = srv.tool_names()
        assert len(names) == 16 and LEGACY <= set(names)
        assert srv.call("corpus_search", {"query": "x"})["structuredContent"]["status"] != "UNSUPPORTED_TOOL"


def test_the_printed_tools_all_registration_starts_a_server_with_the_legacy_tools(home):
    reg = registration("hermes", "--tools", "all")
    with McpProc(reg["command"], reg["args"], {**reg["env"], **isolated_env(home)}, cwd=home) as srv:
        srv.initialize()
        assert len(srv.tool_names()) == 13


def test_the_plain_server_module_keeps_its_legacy_default_and_validates_the_switch(home):
    env = isolated_env(home)
    store = str(home / "data" / "data" / "derived" / "memory.sqlite3")
    assert run_cli("setup")[0] == 0
    with McpProc(sys.executable, ["-m", "src.integration.m6.mcp_server", "--profile-id", "codex", "--enable-memory"],
                 env, cwd=home) as srv:
        srv.initialize()
        assert len(srv.tool_names()) == 13  # unchanged: T6a / T6b pin it
    with McpProc(sys.executable, ["-m", "src.integration.m6.mcp_server", "--profile-id", "codex", "--enable-memory",
                                  "--tools", "memory"], env, cwd=home) as srv:
        srv.initialize()
        assert srv.tool_names() == ["memory_recall", "memory_context"]
    import subprocess

    import os

    base = {k: v for k, v in os.environ.items() if not k.startswith(("ZM_M6_", "ZERO_MEM_"))}
    base.update(env)
    from tests.unit.t6b_helpers import REPO_ROOT

    base["PYTHONPATH"] = str(REPO_ROOT)
    done = subprocess.run([sys.executable, "-m", "src.integration.m6.mcp_server", "--store-path", store,
                           "--tools", "memory"], stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
                          cwd=str(REPO_ROOT), env=base, timeout=60)
    assert done.returncode == 2 and "--enable-memory" in done.stderr
