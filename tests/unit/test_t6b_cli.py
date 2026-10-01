"""T6b - ``zero-mem serve`` (really execs the pinned server) and ``zero-mem mcp-config`` (registration snippets)."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import sys
import tomllib
from pathlib import Path

import pytest

from tests.unit.t6b_helpers import AGENTS, REPO_ROOT, McpProc, apply_env, isolated_env, registration
from zero_mem import cli


@pytest.fixture
def home(tmp_path, monkeypatch):
    apply_env(monkeypatch, tmp_path)
    return tmp_path


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(list(argv))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


# ----------------------------------------------------------------------------------------------- serve
@pytest.fixture
def execs(monkeypatch):
    from zero_mem import commands_mcp

    calls = []
    monkeypatch.setattr(commands_mcp.os, "execv", lambda exe, argv: calls.append((exe, list(argv))))
    return calls


def test_the_t5_placeholder_refusal_is_gone():
    from zero_mem import commands_memory

    assert not hasattr(commands_memory, "_mcp_supports_profile_pin")


def test_serve_execs_the_pinned_server_with_the_data_root_database(home, execs):
    code, _out, err = run("--profile", "codex", "serve")
    assert code == 0, err
    (exe, argv), = execs
    assert exe == sys.executable and argv[0] == sys.executable
    db = home / "data" / "data" / "derived" / "memory.sqlite3"
    assert argv[1:] == ["-m", "src.integration.m6.mcp_server", "--store-path", str(db), "--profile-id", "codex",
                        "--enable-memory"]
    assert db.exists()  # first-run setup was ensured before the exec


def test_serve_can_enable_writes_and_allow_roots(home, execs, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    code, _o, err = run("serve", "--profile", "claude-code", "--enable-write", "--allow-root", str(docs),
                        "--allow-root", str(tmp_path))
    assert code == 0, err
    argv = execs[0][1]
    assert argv[argv.index("--profile-id") + 1] == "claude-code"
    assert "--enable-write" in argv and "--enable-memory" in argv
    roots = [argv[i + 1] for i, a in enumerate(argv) if a == "--allow-root"]
    assert roots == [str(docs), str(tmp_path)]


def test_serve_makes_relative_allow_roots_absolute(home, execs, tmp_path, monkeypatch):
    (tmp_path / "rel").mkdir()
    monkeypatch.chdir(tmp_path)
    assert run("serve", "--profile", "codex", "--enable-write", "--allow-root", "rel")[0] == 0
    argv = execs[0][1]
    assert argv[argv.index("--allow-root") + 1] == str((tmp_path / "rel").resolve())


@pytest.mark.parametrize("argv,needle", [
    (["--profile", "bad profile!", "serve"], "profile"),
    (["serve", "--profile", "codex", "--enable-write", "--allow-root", "/definitely/not/here"], "allow-root"),
    (["serve", "--profile", "codex", "--allow-root", "/tmp"], "--enable-write"),
])
def test_serve_refuses_bad_input_without_exec(home, execs, argv, needle):
    code, _o, err = run(*argv)
    assert code == 2 and needle in err and execs == [] and "Traceback" not in err


def test_serve_really_starts_a_pinned_stdio_server(home):
    with McpProc(sys.executable, ["-m", "zero_mem.cli", "serve", "--profile", "codex"],
                 isolated_env(home), cwd=home) as srv:
        info = srv.initialize()
        assert info["serverInfo"]["identity"] == "pinned"
        names = srv.tool_names()
        assert "memory_recall" in names and "memory_context" in names and "corpus_search" in names
        assert not any(n in names for n in ("memory_add", "memory_ingest", "memory_forget"))
        assert srv.env("memory_recall", {"query": "nothing yet"})["status"] == "EMPTY"
        assert srv.env("memory_recall", {"query": "x", "requesting_profile_id": "claude-code"})["status"] == "DENIED"


# ----------------------------------------------------------------------------------------------- mcp-config
@pytest.mark.parametrize("agent", AGENTS)
def test_mcp_config_uses_the_absolute_interpreter_and_pins_the_agent_profile(home, agent):
    reg = registration(agent)
    assert reg["agent"] == agent and reg["profile"] == agent and reg["server_name"] == "zero-mem"
    assert reg["command"] == os.path.abspath(sys.executable) and os.path.isabs(reg["command"])
    assert reg["args"] == ["-m", "zero_mem.cli", "serve", "--profile", agent]
    assert reg["env"]["ZERO_MEM_DATA_ROOT"] == str(home / "data")
    assert reg["env"]["XDG_CONFIG_HOME"] == str(home / "xdg" / "config")
    assert reg["write_enabled"] is False
    assert reg["verified"] == {"server_command": True, "client_config_format": False}


def test_mcp_config_does_not_touch_the_filesystem(home):
    registration("codex", "--enable-write")
    assert not (home / "data").exists() and not (home / "xdg").exists()


def test_mcp_config_options_flow_into_the_command(home, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    reg = registration("codex", "--profile", "codex-2", "--enable-write", "--allow-root", str(docs), "--name", "memory")
    assert reg["profile"] == "codex-2" and reg["server_name"] == "memory"
    assert reg["args"] == ["-m", "zero_mem.cli", "serve", "--profile", "codex-2", "--enable-write",
                           "--allow-root", str(docs)]
    assert reg["write_enabled"] is True and "[mcp_servers.memory]" in reg["snippets"]["config_toml"]


def test_the_corpus_root_override_is_pinned_when_it_is_set(home, monkeypatch, tmp_path):
    monkeypatch.setenv("ZERO_MEM_CORPUS_ROOT", str(tmp_path / "corp"))
    assert registration("hermes")["env"]["ZERO_MEM_CORPUS_ROOT"] == str(tmp_path / "corp")


def test_claude_code_snippets(home):
    reg = registration("claude-code", "--enable-write")
    add = shlex.split(reg["snippets"]["claude_mcp_add"])
    assert add[:4] == ["claude", "mcp", "add", "zero-mem"]
    split = add.index("--")
    assert add[split + 1:] == [reg["command"], *reg["args"]]
    flags = add[4:split]
    assert "-e" in flags and f"ZERO_MEM_DATA_ROOT={home / 'data'}" in flags
    assert ["-s", "user"] == flags[flags.index("-s"):flags.index("-s") + 2]
    mcp_json = json.loads(reg["snippets"]["mcp_json"])
    assert mcp_json == {"mcpServers": {"zero-mem": {"type": "stdio", "command": reg["command"], "args": reg["args"],
                                                    "env": reg["env"]}}}


def test_codex_snippets(home):
    reg = registration("codex")
    parsed = tomllib.loads(reg["snippets"]["config_toml"])
    entry = parsed["mcp_servers"]["zero-mem"]
    assert entry["command"] == reg["command"] and entry["args"] == reg["args"] and entry["env"] == reg["env"]
    add = shlex.split(reg["snippets"]["codex_mcp_add"])
    assert add[:4] == ["codex", "mcp", "add", "zero-mem"] and add[add.index("--") + 1:] == [reg["command"], *reg["args"]]


@pytest.mark.parametrize("agent", ["hermes", "openclaw"])
def test_generic_stdio_snippet_for_hermes_and_openclaw(home, agent):
    reg = registration(agent)
    assert json.loads(reg["snippets"]["mcp_json"]) == {
        "mcpServers": {"zero-mem": {"command": reg["command"], "args": reg["args"], "env": reg["env"]}}}
    assert "claude_mcp_add" not in reg["snippets"] and "config_toml" not in reg["snippets"]


def test_hostile_characters_in_paths_survive_every_format(home, tmp_path, monkeypatch):
    weird = tmp_path / 'a b"c\'d\\e $x'
    weird.mkdir()
    monkeypatch.setenv("ZERO_MEM_DATA_ROOT", str(weird / "d"))
    for agent in ("claude-code", "codex"):
        reg = registration(agent, "--enable-write", "--allow-root", str(weird))
        assert reg["env"]["ZERO_MEM_DATA_ROOT"] == str(weird / "d")
    cc = registration("claude-code", "--enable-write", "--allow-root", str(weird))
    add = shlex.split(cc["snippets"]["claude_mcp_add"])
    assert add[add.index("--") + 1:] == [cc["command"], *cc["args"]]
    cx = registration("codex", "--enable-write", "--allow-root", str(weird))
    entry = tomllib.loads(cx["snippets"]["config_toml"])["mcp_servers"]["zero-mem"]
    assert entry["args"] == cx["args"] and entry["env"]["ZERO_MEM_DATA_ROOT"] == str(weird / "d")
    assert json.loads(cc["snippets"]["mcp_json"])["mcpServers"]["zero-mem"]["args"] == cc["args"]


def test_text_output_is_ready_to_paste_and_says_what_is_verified(home):
    code, out, err = run("mcp-config", "--agent", "codex", "--enable-write")
    assert code == 0 and not err
    assert "[mcp_servers.zero-mem]" in out and os.path.abspath(sys.executable) in out
    assert "grant-write codex --space ks-shared" in out and "agents add codex" in out
    assert "NOT verified" in out and "--enable-write" in out
    # the whole codex output is valid TOML (every explanatory line is a comment): it can be appended as is
    entry = tomllib.loads(out)["mcp_servers"]["zero-mem"]
    assert entry["command"] == os.path.abspath(sys.executable) and "--enable-write" in entry["args"]
    code, out, _ = run("mcp-config", "--agent", "claude-code")
    assert "claude mcp add zero-mem" in out and '"mcpServers"' in out
    code, out, _ = run("mcp-config", "--agent", "hermes")
    assert '"mcpServers"' in out and "generic" in out.lower()


@pytest.mark.parametrize("argv", [
    ["mcp-config"],
    ["mcp-config", "--agent", "gemini"],
    ["mcp-config", "--agent", "codex", "--profile", "bad profile!"],
    ["mcp-config", "--agent", "codex", "--name", "bad name"],
    ["mcp-config", "--agent", "codex", "--enable-write", "--allow-root", "/definitely/not/here"],
    ["mcp-config", "--agent", "codex", "--allow-root", "/tmp"],
])
def test_mcp_config_refuses_bad_input(home, argv):
    code, out, err = run(*argv)
    assert code == 2 and out == "" and "Traceback" not in err


def test_the_printed_registration_really_starts_a_server_for_every_agent(home):
    """Run EXACTLY the command/args/env each agent's snippet carries (no client involved)."""
    for agent in AGENTS:
        reg = registration(agent)
        with McpProc(reg["command"], reg["args"], reg["env"], cwd=home) as srv:
            info = srv.initialize()
            assert info["serverInfo"]["identity"] == "pinned"
            assert "memory_recall" in srv.tool_names()
            assert srv.env("memory_context")["status"] == "EMPTY"


def test_mcp_config_is_listed_in_help_without_tripping_the_release_layer_gate(home):
    code, out, _ = run("--help")
    assert code == 0 and "mcp-config" in out and "serve" in out
    for banned in ("status ", "rebuild", " start"):
        assert banned not in out.replace("memory-status", "")
