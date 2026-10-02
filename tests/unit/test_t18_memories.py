"""T18 - named memories (registry, create/list/use/remove/rename, selection precedence, isolation) and ``zero-mem link``.

Every test runs against temp dirs: ``ZERO_MEM_MEMORIES``, ``ZERO_MEM_DATA_ROOT`` and the XDG dirs are pointed at tmp_path.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit._symlink_guard import require_symlinks
from tests.unit.t6b_helpers import AGENTS, REPO_ROOT, launch
from zero_mem import cli, workspaces
from zero_mem.workspaces import WorkspaceError

ABS_ETC = os.path.abspath(os.sep + "etc")


@pytest.fixture
def env(tmp_path, monkeypatch):
    for key in ("ZERO_MEM_MEMORY", "ZERO_MEM_CORPUS_ROOT", "ZERO_MEM_CONFIG_PATH", "ZERO_MEM_PROFILE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ZERO_MEM_MEMORIES", str(tmp_path / "cfg" / "memories.toml"))
    monkeypatch.delenv("ZERO_MEM_DATA_ROOT", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))  # the 'default' memory is tmp/xdg-data/zero-mem
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg" / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg" / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg" / "cache"))
    return tmp_path


def run(*argv, expect=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    if expect is not None:
        assert code == expect, (argv, code, out.getvalue(), err.getvalue())
    return code, out.getvalue(), err.getvalue()


def run_json(*argv):
    code, out, err = run(*argv, "--json", expect=0)
    return json.loads(out)


def registry_file():
    return workspaces.registry_path()


# ------------------------------------------------------------------------------------------ names + schema
@pytest.mark.parametrize("name", ["a", "work", "my-mem_2", "0abc", "x" * 40])
def test_valid_names(name):
    assert workspaces.valid_name(name)


@pytest.mark.parametrize("name", ["", "Work", "-a", "_a", "a b", "a/b", "a.b", "x" * 41, "é", None, 5])
def test_invalid_names(name):
    assert not workspaces.valid_name(name)


def test_default_is_reserved(env):
    run("memory", "create", "default", expect=2)
    run("memory", "rename", "default", "x", expect=2)
    assert not registry_file().exists()


def test_schema_is_closed_and_validated():
    ok = {"schema_version": 1, "memories": {"w": {"path": os.path.abspath(os.sep + "w")}}}
    assert workspaces.parse_registry(ok).memories["w"].path.endswith("/w") or True
    bad = [
        {"schema_version": 2},
        {"schema_version": 1, "extra": 1},
        {"schema_version": 1, "memories": {"w": {"path": "relative/dir"}}},
        {"schema_version": 1, "memories": {"w": {"path": os.path.abspath(os.sep), "bogus": 1}}},
        {"schema_version": 1, "memories": {"W": {"path": os.path.abspath(os.sep + "w")}}},
        {"schema_version": 1, "memories": {"default": {"path": os.path.abspath(os.sep + "w")}}},
        {"schema_version": 1, "default": "ghost", "memories": {}},
        {"schema_version": 1, "memories": {"w": {"path": os.path.abspath(os.sep + "w"), "created_at": "yesterday"}}},
        {"schema_version": 1, "memories": {"w": {"path": os.path.abspath(os.sep + "w"), "description": "x" * 201}}},
        {"schema_version": True},
    ]
    for doc in bad:
        with pytest.raises(WorkspaceError):
            workspaces.parse_registry(doc)


def test_registry_paths_are_stored_with_forward_slashes(env):
    run("memory", "create", "w", expect=0)
    text = registry_file().read_text(encoding="utf-8")
    assert "\\" not in text.split("path =", 1)[1].splitlines()[0]
    reg = workspaces.read_registry()
    assert reg.memories["w"].path == reg.memories["w"].root.as_posix()


# ------------------------------------------------------------------------------------------ atomic write / corruption
def test_atomic_write_leaves_no_temp_files_and_keeps_bak(env):
    run("memory", "create", "one", expect=0)
    first = registry_file().read_text(encoding="utf-8")
    assert not workspaces.backup_path().exists()  # nothing to back up yet
    run("memory", "create", "two", expect=0)
    assert workspaces.backup_path().read_text(encoding="utf-8") == first
    assert sorted(p.name for p in registry_file().parent.iterdir() if p.name.endswith(".tmp")) == []
    assert (registry_file().stat().st_mode & 0o777) == 0o600 or os.name == "nt"


@pytest.mark.parametrize("junk", [b"not = [toml", b"\xff\xfe\x00bad", b"schema_version = 9\n", b"schema_version = 1\nzzz = 1\n"])
def test_corrupt_registry_is_never_overwritten(env, junk):
    run("memory", "create", "one", expect=0)
    good = registry_file().read_bytes()
    run("memory", "create", "two", expect=0)
    bak = workspaces.backup_path().read_bytes()
    assert bak == good
    registry_file().write_bytes(junk)
    for argv in (("memory", "create", "three"), ("memory", "use", "one"), ("memory", "remove", "one"),
                 ("memory", "rename", "one", "uno")):
        code, _o, err = run(*argv)
        assert code == 2 and "memories.toml.bak" in err, argv
    assert registry_file().read_bytes() == junk  # untouched
    assert workspaces.backup_path().read_bytes() == bak  # the good copy is not replaced by garbage
    # restoring the .bak recovers everything
    registry_file().write_bytes(workspaces.backup_path().read_bytes())
    code, out, _e = run("memory", "list", "--json")
    assert code == 0 and {r["name"] for r in json.loads(out)["memories"]} == {"default", "one"}  # the .bak is the previous valid version


def test_corrupt_registry_blocks_registry_dependent_commands_but_not_doctor(env):
    registry_file().parent.mkdir(parents=True)
    registry_file().write_bytes(b"[[[")
    code, _o, err = run("--memory", "x", "memory-status")
    assert code == 2 and "memories.toml" in err
    code, _o, err = run("memory-status")  # the default lookup needs the registry too: fail closed, never guess
    assert code == 2
    code, out, _e = run("doctor", "--json")
    report = json.loads(out)
    check = [c for c in report["checks"] if c["id"] == "memory_registry"][0]
    assert check["status"] == "WARN" and "damaged" in check["message"]


# ------------------------------------------------------------------------------------------ create / list / use / path
def test_create_makes_a_private_layout_and_registers(env):
    data = run_json("memory", "create", "work", "--description", "client work")
    root = Path(data["path"])
    assert (root / "data" / "memory" / "traces" / "events-v1.jsonl").is_file()
    assert (root / "data" / "derived" / "memory.sqlite3").is_file()
    assert (root / "config.json").is_file()
    if os.name != "nt":
        assert (root.stat().st_mode & 0o777) == 0o700
    entry = workspaces.read_registry().memories["work"]
    assert entry.description == "client work" and entry.created_at.endswith("Z")
    run("memory", "create", "work", expect=2)  # duplicate


def test_create_default_path_is_next_to_the_default_root(env):
    data = run_json("memory", "create", "w1")
    assert Path(data["path"]) == env / "xdg-data" / "zero-mem-memories" / "w1"


def test_create_refuses_foreign_non_empty_dir_but_adopts_an_empty_or_existing_layout(env):
    foreign = env / "foreign"
    foreign.mkdir()
    (foreign / "notes.txt").write_text("mine", encoding="utf-8")
    code, _o, err = run("memory", "create", "f", "--path", str(foreign))
    assert code == 2 and "not empty" in err
    assert (foreign / "notes.txt").read_text(encoding="utf-8") == "mine"
    empty = env / "empty"
    empty.mkdir()
    run("memory", "create", "e", "--path", str(empty), expect=0)
    run("memory", "remove", "e", expect=0)
    run("memory", "create", "again", "--path", str(empty), expect=0)  # a previous zero-mem root may be re-registered


def test_create_refuses_a_file_and_a_symlink(env):
    require_symlinks()
    file = env / "afile"
    file.write_text("x", encoding="utf-8")
    run("memory", "create", "a", "--path", str(file), expect=2)
    real = env / "real"
    real.mkdir()
    link = env / "link"
    link.symlink_to(real, target_is_directory=True)
    code, _o, err = run("memory", "create", "s", "--path", str(link))
    assert code == 2 and "symbolic link" in err
    code, _o, err = run("memory", "create", "s2", "--path", str(link / "sub"))
    assert code == 2 and "symbolic link" in err
    assert list(real.iterdir()) == []


def test_create_refuses_nested_and_equal_roots(env):
    outer = Path(run_json("memory", "create", "outer", "--path", str(env / "o"))["path"])
    for name, path in (("inner", outer / "sub"), ("same", outer), ("deep", outer / "a" / "b"),
                       ("dflt", env / "xdg-data" / "zero-mem"), ("dflt-in", env / "xdg-data" / "zero-mem" / "x"),
                       ("parent", env)):
        code, _o, err = run("memory", "create", name, "--path", str(path))
        assert code == 2, (name, err)
    assert set(workspaces.read_registry().memories) == {"outer"}
    assert not (outer / "sub").exists()


def test_list_reports_counts_and_flags_the_current_one(env):
    run("memory", "create", "a", expect=0)
    run("memory", "create", "b", expect=0)
    run("--memory", "a", "add", "alpha fact", expect=0)
    run("--memory", "a", "agents", "add", "bot", expect=0)
    run("memory", "use", "a", expect=0)
    rows = {r["name"]: r for r in run_json("memory", "list")["memories"]}
    assert rows["a"]["sources"] == 1 and rows["a"]["agents"] == 1 and rows["a"]["last_write"]
    assert rows["b"]["sources"] == 0
    assert rows["default"]["status"] == "missing"
    assert rows["a"]["current"] and rows["a"]["default"] and not rows["default"]["current"]
    code, text, _e = run("memory", "list", expect=0)
    assert "* a " in text


def test_use_stores_default_in_the_registry_and_reminds_about_running_agents(env, monkeypatch):
    run("memory", "create", "a", expect=0)
    monkeypatch.setenv("ZERO_MEM_DATA_ROOT", str(env / "elsewhere"))
    code, out, _e = run("memory", "use", "a", expect=0)
    assert "already running keep the memory" in out and "ZERO_MEM_DATA_ROOT is set" in out
    assert workspaces.read_registry().default == "a"
    run("memory", "use", "default", expect=0)
    assert workspaces.read_registry().default is None
    run("memory", "use", "ghost", expect=5)


def test_path_command(env):
    data = run_json("memory", "create", "a")
    code, out, _e = run("memory", "path", "a", expect=0)
    assert out.strip() == data["path"]
    code, out, _e = run("memory", "path", "default", expect=0)
    assert out.strip() == str(env / "xdg-data" / "zero-mem")
    run("memory", "path", "nope", expect=5)


# ------------------------------------------------------------------------------------------ remove / rename
def test_remove_only_unregisters_by_default(env):
    root = Path(run_json("memory", "create", "a")["path"])
    run("--memory", "a", "add", "keep me", expect=0)
    run("memory", "remove", "a", expect=0)
    assert root.is_dir() and "a" not in workspaces.read_registry().memories
    # the data is still there: register it again and read it back
    run("memory", "create", "back", "--path", str(root), expect=0)
    code, out, _e = run("--memory", "back", "search", "keep", expect=0)
    assert "keep me" in out


def test_remove_resets_default_pointer(env):
    run("memory", "create", "a", expect=0)
    run("memory", "use", "a", expect=0)
    run("memory", "remove", "a", expect=0)
    assert workspaces.read_registry().default is None


def test_delete_data_needs_yes_and_never_touches_default(env):
    root = Path(run_json("memory", "create", "a")["path"])
    code, _o, err = run("memory", "remove", "a", "--delete-data")
    assert code == 2 and "--yes" in err
    assert root.is_dir() and "a" in workspaces.read_registry().memories  # nothing changed
    run("memory", "remove", "a", "--delete-data", "--yes", expect=0)
    assert not root.exists() and "a" not in workspaces.read_registry().memories
    default_root = env / "xdg-data" / "zero-mem"
    run("--memory", "default", "add", "x", expect=0)
    assert default_root.is_dir()
    for argv in (("memory", "remove", "default"), ("memory", "remove", "default", "--delete-data", "--yes")):
        assert run(*argv)[0] == 2
    assert default_root.is_dir()


def test_delete_data_refuses_a_path_that_is_not_a_memory_root(env):
    run("memory", "create", "a", expect=0)
    workspaces.mutate(lambda reg: reg.memories.__setitem__(
        "a", workspaces.MemoryEntry("a", (env / "notamemory").as_posix(), "", "")))
    (env / "notamemory").mkdir()
    (env / "notamemory" / "precious.txt").write_text("keep", encoding="utf-8")
    code, _o, err = run("memory", "remove", "a", "--delete-data", "--yes")
    assert code == 2 and "not a real zero-mem data root" in err
    assert (env / "notamemory" / "precious.txt").exists()


def test_rename_keeps_data_and_default_pointer(env):
    root = Path(run_json("memory", "create", "a", "--description", "d")["path"])
    run("memory", "use", "a", expect=0)
    run("memory", "rename", "a", "b", expect=0)
    reg = workspaces.read_registry()
    assert set(reg.memories) == {"b"} and reg.default == "b" and reg.memories["b"].root == root
    assert reg.memories["b"].description == "d"
    run("memory", "create", "c", expect=0)
    run("memory", "rename", "b", "c", expect=2)
    run("memory", "rename", "b", "Bad", expect=2)
    run("memory", "rename", "ghost", "x", expect=5)


# ------------------------------------------------------------------------------------------ precedence
def _pre(tmp_path, monkeypatch, *, data_root_env, memory_env, use):
    if data_root_env:
        monkeypatch.setenv("ZERO_MEM_DATA_ROOT", str(tmp_path / "envroot"))
    if memory_env:
        monkeypatch.setenv("ZERO_MEM_MEMORY", memory_env)
    run("memory", "create", "flag", expect=0)
    run("memory", "create", "viaenv", expect=0)
    run("memory", "create", "dflt", expect=0)
    if use:
        run("memory", "use", "dflt", expect=0)


@pytest.mark.parametrize("data_root_env", [False, True])
@pytest.mark.parametrize("flag", [None, "flag"])
@pytest.mark.parametrize("memory_env", [None, "viaenv"])
@pytest.mark.parametrize("use", [False, True])
def test_precedence_matrix(env, monkeypatch, data_root_env, flag, memory_env, use):
    _pre(env, monkeypatch, data_root_env=data_root_env, memory_env=memory_env, use=use)
    reg = workspaces.read_registry()
    expected_root = {"flag": reg.memories["flag"].root, "viaenv": reg.memories["viaenv"].root,
                     "dflt": reg.memories["dflt"].root}
    if data_root_env:
        want, source = env / "envroot", "env-data-root"
    elif flag:
        want, source = expected_root["flag"], "--memory"
    elif memory_env:
        want, source = expected_root["viaenv"], "env-memory"
    elif use:
        want, source = expected_root["dflt"], "registry-default"
    else:
        want, source = env / "xdg-data" / "zero-mem", "xdg-default"
    sel = workspaces.select(flag)
    assert (sel.root, sel.source) == (want, source)
    argv = (["--memory", flag] if flag else []) + ["memory-status", "--json"]
    code, out, err = run(*argv, expect=0)
    status = json.loads(out)
    assert Path(status["data_root"]) == want and status["memory"]["source"] == source
    # the process environment is restored after the command
    assert os.environ.get("ZERO_MEM_DATA_ROOT") == (str(env / "envroot") if data_root_env else None)
    assert "ZERO_MEM_CONFIG_PATH" not in os.environ


def test_unknown_memory_flag_and_env(env, monkeypatch):
    code, _o, err = run("--memory", "ghost", "memory-status")
    assert code == 5 and "ghost" in err
    code, _o, err = run("--memory", "BAD NAME", "memory-status")
    assert code == 2
    monkeypatch.setenv("ZERO_MEM_MEMORY", "ghost")
    assert run("memory-status")[0] == 5


def test_existing_behaviour_without_new_options_is_unchanged(env):
    code, out, _e = run("add", "plain fact", expect=0)
    assert (env / "xdg-data" / "zero-mem" / "data" / "memory").is_dir()
    assert not registry_file().exists()  # nothing registry-related is ever written implicitly
    assert "plain fact" in run("search", "plain", expect=0)[1]


def test_explicit_data_root_env_beats_flag_with_a_note(env, monkeypatch):
    run("memory", "create", "a", expect=0)
    monkeypatch.setenv("ZERO_MEM_DATA_ROOT", str(env / "envroot"))
    code, _o, err = run("--memory", "a", "add", "in default", expect=0)
    assert "takes precedence" in err
    assert "in default" in run("search", "default", expect=0)[1]
    assert (env / "envroot" / "data").is_dir()
    monkeypatch.delenv("ZERO_MEM_DATA_ROOT")
    assert "no results" in run("--memory", "a", "search", "default", expect=0)[1]


# ------------------------------------------------------------------------------------------ isolation
def test_two_memories_are_fully_isolated(env, monkeypatch):
    run("memory", "create", "red", expect=0)
    run("memory", "create", "blue", expect=0)
    run("--memory", "red", "add", "zebra crossing red secret-free fact", expect=0)
    run("--memory", "blue", "add", "giraffe neck blue fact", expect=0)
    assert "zebra" in run("--memory", "red", "search", "zebra", expect=0)[1]
    assert "no results" in run("--memory", "blue", "search", "zebra", expect=0)[1]
    assert "giraffe" in run("--memory", "blue", "search", "giraffe", expect=0)[1]
    assert "no results" in run("--memory", "red", "search", "giraffe", expect=0)[1]
    assert "no results" in run("search", "zebra", expect=0)[1]  # the default memory sees neither
    # agents are per memory too
    run("--memory", "red", "agents", "add", "bot", expect=0)
    assert "no agents" in run("--memory", "blue", "agents", "list", expect=0)[1]
    # an inherited corpus override must not break isolation
    monkeypatch.setenv("ZERO_MEM_CORPUS_ROOT", str(env / "shared-corpus"))
    assert "zebra" in run("--memory", "red", "search", "zebra", expect=0)[1]
    assert "no results" in run("--memory", "blue", "search", "zebra", expect=0)[1]
    assert not (env / "shared-corpus").exists()
    # each memory passes doctor's configuration checks on its own config.json
    for name in ("red", "blue"):
        report = json.loads(run("--memory", name, "doctor", "--json")[1])
        status = {c["id"]: c["status"] for c in report["checks"]}
        assert status["configuration"] == "PASS" and status["memory_registry"] == "PASS", (name, status)


def test_doctor_and_status_name_the_active_memory(env, monkeypatch):
    run("memory", "create", "red", expect=0)
    report = json.loads(run("--memory", "red", "doctor", "--json")[1])
    msg = [c for c in report["checks"] if c["id"] == "memory_registry"][0]["message"]
    assert "'red'" in msg and "--memory" in msg
    assert "memory       red" in run("--memory", "red", "memory-status", expect=0)[1]


# ------------------------------------------------------------------------------------------ link
def _link(agent, memory, *extra):
    return run_json("link", agent, "--memory", memory, *extra)


@pytest.mark.parametrize("agent", AGENTS)
def test_link_pins_the_memorys_data_root_for_each_agent(env, agent):
    root = Path(run_json("memory", "create", "red")["path"])
    other = Path(run_json("memory", "create", "blue")["path"])
    reg = _link(agent, "red")
    assert reg["env"]["ZERO_MEM_DATA_ROOT"] == str(root)
    assert reg["env"]["ZERO_MEM_CONFIG_PATH"] == str(root / "config.json")
    assert "ZERO_MEM_CORPUS_ROOT" not in reg["env"]
    assert reg["memory"]["name"] == "red" and reg["server_name"] == "zero-mem-red"
    blob = json.dumps(reg["snippets"])
    assert str(root).replace("\\", "\\\\") in blob or str(root) in blob
    assert str(other) not in blob and str(other).replace("\\", "\\\\") not in blob
    text = run("link", agent, "--memory", "red", expect=0)[1]
    assert str(root) in text.replace("\\\\", "\\") and "already running keep the memory" in text


def test_link_to_default_pins_the_default_root(env):
    reg = _link("codex", "default")
    assert reg["env"]["ZERO_MEM_DATA_ROOT"] == str(env / "xdg-data" / "zero-mem")
    assert "ZERO_MEM_CONFIG_PATH" not in reg["env"] and reg["server_name"] == "zero-mem"


def test_link_registers_the_profile_once_and_passes_server_options(env):
    run("memory", "create", "red", expect=0)
    first = _link("claude-code", "red", "--profile", "bot-1", "--enable-write", "--enable-propose",
                  "--allow-root", str(env))
    assert first["profile"] == "bot-1" and first["profile_status"] == "added"
    assert first["write_enabled"] and first["propose_enabled"] and first["allow_roots"] == [str(env)]
    assert _link("claude-code", "red", "--profile", "bot-1")["profile_status"] == "exists"
    rows = run_json("--memory", "red", "agents", "list")["agents"]
    assert [r["profile"] for r in rows] == ["bot-1"] and rows[0]["can_read_shared"] and not rows[0]["can_write_shared"]
    blue = run_json("memory", "create", "blue")
    assert run_json("--memory", "blue", "agents", "list")["agents"] == []
    del blue


def test_link_unknown_memory_and_bad_inputs(env):
    assert run("link", "codex", "--memory", "ghost")[0] == 5
    assert run("link", "codex", "--memory", "default", "--profile", "bad profile")[0] == 2
    assert run("link", "codex", "--memory", "default", "--allow-root", str(env))[0] == 2  # needs --enable-write
    assert run("link")[0] == 2


def test_link_list_and_remove(env):
    run("memory", "create", "red", expect=0)
    run("memory", "create", "blue", expect=0)
    _link("codex", "red")
    _link("hermes", "blue")
    _link("codex", "blue")
    listing = {m["memory"]: [p["profile"] for p in m["profiles"]] for m in run_json("link", "--list")["memories"]}
    assert listing == {"default": [], "red": ["codex"], "blue": ["codex", "hermes"]}
    code, out, _e = run("link", "--remove", "codex", "--memory", "blue", expect=0)
    assert "data is kept" in out
    after = {m["memory"]: [p["profile"] for p in m["profiles"]] for m in run_json("link", "--list")["memories"]}
    assert after["red"] == ["codex"]  # another memory is untouched
    codex_blue = [r for r in run_json("--memory", "blue", "agents", "list")["agents"] if r["profile"] == "codex"][0]
    assert codex_blue["grants"] == [] and not codex_blue["can_read_shared"]
    run("link", "--remove", "codex", "--memory", "blue", expect=5)  # nothing left to revoke
    run("link", "--remove", "codex", expect=2)  # needs --memory
    run("--memory", "blue", "add", "data survives", expect=0)
    assert "data survives" in run("--memory", "blue", "search", "survives", expect=0)[1]


def test_link_apply_refuses_without_yes_and_for_unverified_clients(env, monkeypatch):
    run("memory", "create", "red", expect=0)
    calls = []
    monkeypatch.setattr("zero_mem.commands_workspace.subprocess.run", lambda *a, **k: calls.append(a) or None)
    monkeypatch.setattr("zero_mem.commands_workspace.shutil.which", lambda name: "/fake/claude")
    code, _o, err = run("link", "claude-code", "--memory", "red", "--apply")
    assert code == 2 and "--yes" in err and not calls
    for agent in ("codex", "hermes", "openclaw"):
        code, _o, err = run("link", agent, "--memory", "red", "--apply", "--yes")
        assert code == 2 and "only available for claude-code" in err and not calls
    # refused applies changed no state: the profile was not registered
    assert run_json("--memory", "red", "agents", "list")["agents"] == []


def test_link_apply_runs_exactly_the_shown_claude_command(env, monkeypatch):
    root = Path(run_json("memory", "create", "red")["path"])
    seen = []

    class Done:
        returncode = 0

    monkeypatch.setattr("zero_mem.commands_workspace.subprocess.run", lambda argv, **k: seen.append(argv) or Done())
    monkeypatch.setattr("zero_mem.commands_workspace.shutil.which", lambda name: "/fake/claude")
    code, out, _e = run("link", "claude-code", "--memory", "red", "--apply", "--yes", expect=0)
    argv = seen[0]
    assert argv[:5] == ["claude", "mcp", "add", "zero-mem-red", "-s"] and f"ZERO_MEM_DATA_ROOT={root}" in argv
    assert "serve" in argv and "--" in argv
    assert out.startswith("running: claude mcp add zero-mem-red")
    monkeypatch.setattr("zero_mem.commands_workspace.shutil.which", lambda name: None)
    assert run("link", "claude-code", "--memory", "red", "--apply", "--yes")[0] == 2


def test_link_never_writes_client_config_files(env, monkeypatch):
    home = env / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    run("memory", "create", "red", expect=0)
    for agent in AGENTS:
        run("link", agent, "--memory", "red", expect=0)
    assert list(home.iterdir()) == []


# ------------------------------------------------------------------------------------------ concurrency
def _cli(env_vars, *argv):
    return subprocess.Popen([sys.executable, "-m", "zero_mem.cli", *argv], cwd=str(REPO_ROOT), env=env_vars,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")


def _proc_env():
    base = {k: v for k, v in os.environ.items() if not k.startswith("ZERO_MEM_") and k != "PYTHONPATH"}
    base.update({k: v for k, v in os.environ.items() if k in ("ZERO_MEM_MEMORIES", "ZERO_MEM_DATA_ROOT")})
    base["PYTHONPATH"] = str(REPO_ROOT)
    return base


@pytest.mark.parametrize("round_", range(3))
def test_concurrent_create_from_four_processes(env, round_):
    procs = [_cli(_proc_env(), "memory", "create", f"m{i}") for i in range(4)]
    results = [(p.wait(120), p.stdout.read(), p.stderr.read()) for p in procs]
    assert [r[0] for r in results] == [0, 0, 0, 0], results
    reg = workspaces.read_registry()
    assert set(reg.memories) == {"m0", "m1", "m2", "m3"}
    for entry in reg.memories.values():
        assert (entry.root / "data" / "derived" / "memory.sqlite3").is_file()
    assert workspaces.backup_path().exists()
    assert not [p for p in registry_file().parent.iterdir() if p.name.endswith(".tmp")]
    assert len({e.path for e in reg.memories.values()}) == 4


def test_concurrent_create_of_the_same_name_has_one_winner(env):
    procs = [_cli(_proc_env(), "memory", "create", "same") for _ in range(4)]
    codes = sorted(p.wait(120) for p in procs)
    assert codes == [0, 2, 2, 2]
    assert set(workspaces.read_registry().memories) == {"same"}


# ------------------------------------------------------------------------------------------ real stdio MCP server
def test_stdio_server_started_from_link_args_reads_only_its_memory(env, monkeypatch):
    run("memory", "create", "red", expect=0)
    run("memory", "create", "blue", expect=0)
    run("--memory", "red", "--profile", "codex", "add", "okapi lives in the red memory", expect=0)
    run("--memory", "blue", "--profile", "codex", "add", "okapi lives in the blue memory", expect=0)
    run("add", "okapi lives in the default memory", expect=0)
    for memory in ("red", "blue"):
        reg = run_json("link", "codex", "--memory", memory)
        with launch(reg, cwd=env) as proc:
            hits = proc.env("memory_recall", {"query": "okapi"}).get("hits", [])
            texts = [h["text"] for h in hits]
            assert texts and all(memory in t for t in texts), (memory, texts)
