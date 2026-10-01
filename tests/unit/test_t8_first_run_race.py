"""T8 - first-run setup is race-safe in ``Layout.ensure()`` itself, so EVERY entry point survives simultaneous cold starts.

T6b found that ``Layout.ensure()`` on a data root nobody initialised fails for most of N simultaneous processes
(``LayoutError: setup failed``) and worked around it for the MCP server only (``memory_bootstrap.ensure_layout``).
The lock now lives in ``Layout.ensure()`` / ``zero-mem setup``: library, CLI and MCP all go through it.
"""
from __future__ import annotations

import multiprocessing
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.unit.t6b_helpers import REPO_ROOT, isolated_env

PROCESSES = 6
ROUNDS = 5


# ----------------------------------------------------------------------------------- explicit root, in process
def _worker(mode: str, root: str, i: int, barrier, out) -> None:
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from zero_mem.memory import Memory
        from zero_mem.memory_layout import Layout

        barrier.wait(60)
        if mode == "layout":
            Layout.resolve(Path(root)).ensure()
        elif mode == "memory_open":
            with Memory.open(f"agent{i}", data_root=Path(root)) as memory:
                assert memory.add(f"first note {i}").ok
        out.put("ok")
    except BaseException as exc:  # noqa: BLE001 - reported to the parent
        out.put(f"{type(exc).__name__}: {exc}")


@pytest.mark.parametrize("mode", ["layout", "memory_open"])
@pytest.mark.parametrize("round_", range(ROUNDS))
def test_simultaneous_cold_starts_through_the_library_all_succeed(tmp_path, mode, round_):
    ctx = multiprocessing.get_context("spawn")
    barrier, out = ctx.Barrier(PROCESSES), ctx.Queue()
    root = tmp_path / "fresh"
    procs = [ctx.Process(target=_worker, args=(mode, str(root), i, barrier, out)) for i in range(PROCESSES)]
    for p in procs:
        p.start()
    results = [out.get(timeout=180) for _ in procs]
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0
    assert results == ["ok"] * PROCESSES, results
    from zero_mem.memory_layout import Layout

    layout = Layout.resolve(root)
    conn = sqlite3.connect(layout.derived_db)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT MAX(version) FROM zm_migrations").fetchone()[0] >= 13
    finally:
        conn.close()
    assert layout.memory_stream.is_file() and (layout.corpus_root / "corpus_sources.jsonl").is_file()
    if mode == "memory_open":
        from zero_mem.memory import Memory

        for i in range(PROCESSES):
            with Memory.open(f"agent{i}", data_root=root) as memory:
                assert memory.recall("first note").status == "ok"


# ----------------------------------------------------------------------------------- default root, real processes
_GO_SCRIPT = r"""
import os, sys, time
sys.path.insert(0, sys.argv[1])
go = sys.argv[2]
from zero_mem import cli
while not os.path.exists(go):
    time.sleep(0.002)
sys.exit(cli.main(sys.argv[3:]))
"""


def _spawn_cli(tmp_path: Path, argvs: list) -> list:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ZM_M6_", "ZERO_MEM_")) and k != "PYTHONPATH"}
    env.update(isolated_env(tmp_path))
    go = tmp_path / "go"
    procs = [subprocess.Popen([sys.executable, "-c", _GO_SCRIPT, str(REPO_ROOT), str(go), *argv], cwd=str(tmp_path),
                              env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for argv in argvs]
    time.sleep(1.5)  # every process has imported the CLI and spins on the go file
    go.touch()
    done = []
    for proc in procs:
        out, err = proc.communicate(timeout=180)
        done.append((proc.returncode, out, err))
    return done


@pytest.mark.parametrize("round_", range(ROUNDS))
def test_simultaneous_cold_cli_commands_on_the_default_root_all_succeed(tmp_path, round_):
    """``zero-mem add`` / ``agents add`` / ``setup`` racing on a data root nobody initialised (the standard location)."""
    argvs = [["add", "--profile", f"agent{i}", f"first note {i}"] for i in range(3)]
    argvs += [["agents", "add", f"agent{i}"] for i in range(3, 5)] + [["setup"]]
    assert len(argvs) == PROCESSES
    results = _spawn_cli(tmp_path, argvs)
    for argv, (code, out, err) in zip(argvs, results):
        assert code == 0 and "Traceback" not in err, (argv, code, out, err)


@pytest.mark.parametrize("round_", range(ROUNDS))
def test_simultaneous_cold_servers_on_the_default_root_all_start(tmp_path, round_):
    """Six ``zero-mem serve`` processes (the MCP entry point) racing on a fresh data root."""
    code = r"""
import os, sys, time
sys.path.insert(0, sys.argv[1])
from zero_mem.memory_layout import Layout
from zero_mem.memory import Memory
go = sys.argv[2]
while not os.path.exists(go):
    time.sleep(0.002)
from src.integration.m6w import build_tool_set
tools = build_tool_set(profile_id=sys.argv[3], enable_write=True)
r = tools.call("memory_add", {"text": "note from " + sys.argv[3], "memory_type": "fact", "scope": "private"})
sys.exit(0 if r["structuredContent"]["status"] == "SUCCESS" else 3)
"""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ZM_M6_", "ZERO_MEM_")) and k != "PYTHONPATH"}
    env.update(isolated_env(tmp_path))
    go = tmp_path / "go"
    procs = [subprocess.Popen([sys.executable, "-c", code, str(REPO_ROOT), str(go), f"agent{i}"], cwd=str(tmp_path),
                              env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for i in range(PROCESSES)]
    time.sleep(1.5)
    go.touch()
    for proc in procs:
        out, err = proc.communicate(timeout=180)
        assert proc.returncode == 0 and "Traceback" not in err, (proc.returncode, out, err)


# ----------------------------------------------------------------------------------- behaviour stays identical
def test_ensure_layout_is_a_thin_alias_of_layout_ensure(tmp_path):
    from zero_mem.memory_bootstrap import ensure_layout
    from zero_mem.memory_layout import Layout

    layout = Layout.resolve(tmp_path / "zm")
    ensure_layout(layout)
    ensure_layout(layout, attempts=1)
    layout.ensure()
    assert (layout.data_root / ".layout.lock").is_file()
    assert layout.memory_stream.is_file() and layout.derived_db.is_file()


def test_the_lock_file_is_private_and_never_blocks_a_second_sequential_setup(tmp_path):
    import stat

    from zero_mem.memory_layout import Layout

    layout = Layout.resolve(tmp_path / "zm")
    layout.ensure()
    lock = layout.data_root / ".layout.lock"
    assert stat.S_IMODE(lock.stat().st_mode) & 0o077 == 0
    started = time.monotonic()
    for _ in range(3):
        layout.ensure()
    assert time.monotonic() - started < 10


def test_a_validation_error_still_creates_nothing_in_default_mode(tmp_path, monkeypatch):
    """Config is validated BEFORE any application path (and the lock file) is created, as ``zero-mem setup`` always did."""
    from zero_mem.memory_layout import Layout, LayoutError

    env = isolated_env(tmp_path)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("ZERO_MEM_CORPUS_ROOT", raising=False)
    config = Path(env["XDG_CONFIG_HOME"]) / "zero-mem"
    config.mkdir(parents=True)
    (config / "config.json").write_text("{not-json", encoding="utf-8")
    layout = Layout.resolve(None)
    started = time.monotonic()
    with pytest.raises(LayoutError) as caught:
        layout.ensure()
    assert time.monotonic() - started < 0.3  # a permanent error is not retried
    assert "configuration" in str(caught.value).lower() and str(tmp_path) not in str(caught.value)
    assert not layout.data_root.exists()


def test_a_failed_setup_is_retried_but_a_permanent_failure_still_raises(tmp_path, monkeypatch):
    from zero_mem import memory_layout
    from zero_mem.memory_layout import Layout, LayoutError

    layout = Layout.resolve(tmp_path / "zm")
    calls = {"n": 0}
    real = Layout._ensure_schema

    def flaky(self):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("database is locked")
        real(self)

    monkeypatch.setattr(Layout, "_ensure_schema", flaky)
    monkeypatch.setattr(memory_layout.time, "sleep", lambda _s: None)
    layout.ensure()
    assert calls["n"] == 3
    calls["n"] = -100
    with pytest.raises(LayoutError, match="setup failed"):
        layout.ensure(attempts=2)
