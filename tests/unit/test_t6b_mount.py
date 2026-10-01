"""T6b - mounting the memory tool set into the pinned stdio MCP server (``src.integration.m6.mcp_server``).

The read-only M6 tool list stays exactly as T6a pinned it; recall/context need ``--enable-memory`` and the write
tools need ``--enable-write`` (env ``ZM_M6_ENABLE_MEMORY`` / ``ZM_M6_ENABLE_WRITE``). Every start is pinned to one
profile, roots come from ``--allow-root`` / ``ZM_M6_ALLOW_ROOTS``, and a store path that disagrees with the data
root is refused. Real subprocesses throughout.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys

import pytest

from src.integration.m6 import mcp_server
from src.integration.m6.mcp_wrapper import tool_schemas
from src.integration.m6w import build_tool_set
from tests.unit.t5_memory_helpers import Env
from tests.unit.t6b_helpers import REPO_ROOT, McpProc, isolated_env

M6_TOOLS = sorted(t["name"] for t in tool_schemas())
MEMORY_READ = ["memory_recall", "memory_context"]
MEMORY_WRITE = ["memory_add", "memory_forget", "memory_ingest"]


@pytest.fixture
def home(tmp_path):
    """A provisioned zero-mem under tmp_path, plus the environment that points a server at it."""
    from zero_mem.memory_layout import Layout
    from zero_mem.provisioning import Provisioner

    root = tmp_path / "data"
    layout = Layout.resolve(root)
    layout.ensure()
    Provisioner(layout, operator="tester").add_agent("claude-code")
    return type("Home", (), {"layout": layout, "env": isolated_env(tmp_path), "tmp": tmp_path})


def server(home, *args, env=None, cwd=None):
    merged = {**home.env, **(env or {})}
    return McpProc(sys.executable, ["-m", "src.integration.m6.mcp_server", *args], merged, cwd=cwd or REPO_ROOT)


def run_once(home, *args, env=None):
    """Start the server with stdin closed; return (exit code, stderr)."""
    base = {k: v for k, v in __import__("os").environ.items() if not k.startswith(("ZM_M6_", "ZERO_MEM_"))}
    base.update(home.env)
    base.update(env or {})
    base["PYTHONPATH"] = str(REPO_ROOT)
    done = subprocess.run([sys.executable, "-m", "src.integration.m6.mcp_server", *args], stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, cwd=str(REPO_ROOT), env=base, timeout=60)
    return done.returncode, done.stderr


def names(proc):
    return sorted(proc.tool_names())


# ----------------------------------------------------------------------------------------------- tool list by switch
def test_the_default_server_is_still_the_eleven_read_only_tools(home):
    with server(home, "--store-path", str(home.layout.derived_db), "--profile-id", "claude-code") as srv:
        srv.initialize()
        assert names(srv) == M6_TOOLS and len(M6_TOOLS) == 11


def test_enable_memory_adds_only_the_two_read_tools(home):
    with server(home, "--store-path", str(home.layout.derived_db), "--profile-id", "claude-code",
                "--enable-memory") as srv:
        srv.initialize()
        assert names(srv) == sorted(M6_TOOLS + MEMORY_READ)
        out = srv.call("memory_add", {"text": "x", "memory_type": "fact", "scope": "private"})
        assert out["isError"] is True  # not mounted: the M6 dispatcher refuses it (nothing is written)
        assert out["structuredContent"]["status"] in ("UNSUPPORTED_TOOL", "INVALID_REQUEST")
    assert not (home.layout.corpus_root / "corpus_sources.jsonl").read_text()


def test_enable_write_adds_recall_context_and_the_three_write_tools(home):
    with server(home, "--store-path", str(home.layout.derived_db), "--profile-id", "claude-code",
                "--enable-write") as srv:
        srv.initialize()
        tools = srv.tools()
        assert sorted(t["name"] for t in tools) == sorted(M6_TOOLS + MEMORY_READ + MEMORY_WRITE)
        m6 = [t for t in tools if t["name"] in M6_TOOLS]
        assert sorted(m6, key=lambda t: t["name"]) == sorted(tool_schemas(include_identity=False), key=lambda t: t["name"])
        assert srv.env("memory_add", {"text": "a heron note", "memory_type": "fact", "scope": "private"})["status"] == "SUCCESS"
        assert srv.env("memory_recall", {"query": "heron"})["status"] == "SUCCESS"


def test_environment_switches_work_like_the_flags(home, tmp_path):
    allowed = tmp_path / "docs"
    allowed.mkdir()
    (allowed / "a.md").write_text("# A\n\nlapwing facts", encoding="utf-8")
    env = {"ZM_M6_PROFILE_ID": "claude-code", "ZM_M6_ENABLE_WRITE": "1", "ZM_M6_ALLOW_ROOTS": str(allowed)}
    with server(home, "--store-path", str(home.layout.derived_db), env=env) as srv:
        srv.initialize()
        assert "memory_ingest" in names(srv)
        out = srv.env("memory_ingest", {"path": str(allowed), "memory_type": "file", "scope": "private"})
        assert out["status"] == "SUCCESS" and out["counts"]["created"] == 1
    off = {"ZM_M6_PROFILE_ID": "claude-code", "ZM_M6_ENABLE_WRITE": "0", "ZM_M6_ENABLE_MEMORY": "false"}
    with server(home, "--store-path", str(home.layout.derived_db), env=off) as srv:
        srv.initialize()
        assert names(srv) == M6_TOOLS


def test_allow_root_flags_and_env_roots_are_combined(home, tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"
    for d in (one, two):
        d.mkdir()
        (d / f"{d.name}.md").write_text(f"# {d.name}\n\nfact about {d.name}ness", encoding="utf-8")
    with server(home, "--profile-id", "claude-code", "--enable-write", "--allow-root", str(one),
                env={"ZM_M6_ALLOW_ROOTS": str(two)}) as srv:
        srv.initialize()
        for d in (one, two):
            out = srv.env("memory_ingest", {"path": str(d), "memory_type": "file", "scope": "private"})
            assert out["status"] == "SUCCESS", out


def test_without_a_store_path_the_memory_server_uses_the_data_root_database(home):
    with server(home, "--profile-id", "claude-code", "--enable-memory") as srv:
        info = srv.initialize()
        assert info["serverInfo"]["identity"] == "pinned"
        assert srv.env("memory_recall", {"query": "anything"})["status"] == "EMPTY"
        legacy = srv.call("corpus_search", {"search_text": "anything"})["structuredContent"]
        assert legacy["status"] in ("EMPTY", "SUCCESS")  # the M6 read tools see the same database


# ----------------------------------------------------------------------------------------------- fail closed at start
@pytest.mark.parametrize("flag", ["--enable-write", "--enable-memory"])
def test_memory_tools_require_a_pinned_profile(home, flag):
    code, err = run_once(home, "--store-path", str(home.layout.derived_db), flag)
    assert code == 2 and "--profile-id" in err and "Traceback" not in err


def test_a_store_path_that_is_not_the_data_root_database_is_refused(home, tmp_path):
    other = tmp_path / "other.sqlite3"
    other.write_bytes(b"")
    code, err = run_once(home, "--store-path", str(other), "--profile-id", "claude-code", "--enable-write")
    assert code == 2 and "data root" in err and "Traceback" not in err


@pytest.mark.parametrize("bad", ["relative/dir", "/definitely/not/a/dir", "/"])
def test_bad_allow_roots_are_refused_at_start(home, bad):
    code, err = run_once(home, "--profile-id", "claude-code", "--enable-write", "--allow-root", bad)
    assert code == 2 and "allow-root" in err and "Traceback" not in err


def test_an_allow_root_that_is_a_file_is_refused(home, tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")
    code, err = run_once(home, "--profile-id", "claude-code", "--enable-write", "--allow-root", str(f))
    assert code == 2 and "allow-root" in err


def test_a_server_without_memory_switches_ignores_allow_roots_only_with_a_warning(home, tmp_path):
    code, err = run_once(home, "--store-path", str(home.layout.derived_db), "--profile-id", "claude-code",
                         "--allow-root", str(tmp_path))
    assert code == 0 and "ignored" in err


# ----------------------------------------------------------------------------------------------- the in-process hook
def _memory_ts(home):
    return build_tool_set(profile_id="claude-code", layout=home.layout, enable_write=True)


def test_mount_requires_the_same_pinned_identity_and_unique_names(home):
    ts = _memory_ts(home)
    try:
        mcp_server.set_identity(None, None)
        with pytest.raises(ValueError):
            mcp_server.mount_tool_set(ts)  # unpinned server
        mcp_server.set_identity("codex", None)
        with pytest.raises(ValueError):
            mcp_server.mount_tool_set(ts)  # a different pin
        mcp_server.set_identity("claude-code", None)
        mcp_server.mount_tool_set(ts)
        with pytest.raises(ValueError):
            mcp_server.mount_tool_set(ts)  # same names twice

        class Clash:
            profile_id = "claude-code"
            names = ("corpus_search",)

            def schemas(self):
                return []

            def handles(self, name):
                return name == "corpus_search"

        mcp_server.unmount_tool_sets()
        with pytest.raises(ValueError):
            mcp_server.mount_tool_set(Clash())  # may not shadow an M6 tool
    finally:
        mcp_server.unmount_tool_sets()
        mcp_server.set_identity(None, None)


def test_serve_mounts_for_the_loop_and_clears_afterwards(home):
    ts = _memory_ts(home)
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "memory_add", "arguments": {"text": "kiwi note", "memory_type": "fact", "scope": "private"}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "memory_recall", "arguments": {"query": "kiwi"}}},
    ]
    out = io.StringIO()
    mcp_server.serve(home.layout.derived_db, in_stream=io.StringIO("".join(json.dumps(x) + "\n" for x in lines)),
                     out_stream=out, profile_id="claude-code", tool_sets=[ts])
    replies = [json.loads(x) for x in out.getvalue().splitlines()]
    assert {t["name"] for t in replies[0]["result"]["tools"]} >= set(MEMORY_READ + MEMORY_WRITE)
    assert replies[1]["result"]["structuredContent"]["status"] == "SUCCESS"
    assert replies[2]["result"]["structuredContent"]["hits"][0]["text"] == "kiwi note"
    assert mcp_server.get_identity().pinned is False
    assert len(mcp_server._handle_rpc("tools/list", {}, 9)["result"]["tools"]) == 11


def test_the_hook_does_not_touch_the_read_only_surface(home):
    """The M6 modules keep their invariants: no write tool is registered there and ``tools.py`` is unchanged."""
    from src.integration.m6.tools import TOOL_REGISTRY, list_tool_names

    assert not any(n in TOOL_REGISTRY for n in MEMORY_READ + MEMORY_WRITE)
    assert len(list_tool_names()) == 11
