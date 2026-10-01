"""T6b - first-run setup must survive several agent servers starting at the same moment.

Found by the four-agent cold-start test: ``Layout.ensure()`` on a never-initialised data root fails for most of
N simultaneous processes (concurrent schema creation: ``LayoutError: setup failed``, i.e. ``zero-mem: unable to
initialize derived store``), so a client that launches all its agent servers at once loses some of them.
``zero_mem.memory_bootstrap.ensure_layout`` serializes the setup under a cross-process lock; the MCP tool set and
``zero-mem serve`` use it.
"""
from __future__ import annotations

import multiprocessing
import sqlite3
import sys
from pathlib import Path

import pytest

from tests.unit.t6b_helpers import REPO_ROOT, McpProc, isolated_env

PROCESSES = 6


def _ensure_worker(root: str, barrier, out) -> None:
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from zero_mem.memory_bootstrap import ensure_layout
        from zero_mem.memory_layout import Layout

        layout = Layout.resolve(Path(root))
        barrier.wait(60)
        ensure_layout(layout)
        out.put("ok")
    except BaseException as exc:  # noqa: BLE001 - reported to the parent
        out.put(f"{type(exc).__name__}: {exc}")


@pytest.mark.parametrize("round_", range(3))
def test_concurrent_first_run_setup_never_fails(tmp_path, round_):
    ctx = multiprocessing.get_context("spawn")
    barrier, out = ctx.Barrier(PROCESSES), ctx.Queue()
    root = tmp_path / "fresh"
    procs = [ctx.Process(target=_ensure_worker, args=(str(root), barrier, out)) for _ in range(PROCESSES)]
    for p in procs:
        p.start()
    results = [out.get(timeout=120) for _ in procs]
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


def test_ensure_layout_is_idempotent_and_keeps_existing_data(tmp_path):
    from zero_mem.memory import Memory
    from zero_mem.memory_bootstrap import ensure_layout
    from zero_mem.memory_layout import Layout

    layout = Layout.resolve(tmp_path / "zm")
    ensure_layout(layout)
    memory = Memory("claude-code", layout)
    assert memory.add("a note about egrets").ok
    ensure_layout(layout)
    ensure_layout(layout)
    assert memory.recall("egrets").status == "ok"
    memory.close()


@pytest.mark.parametrize("round_", range(3))
def test_agent_servers_launched_at_the_same_moment_on_a_new_data_root_all_start(tmp_path, round_):
    """The real thing: four ``zero-mem serve`` processes (one per agent) racing on a data root nobody initialised."""
    import threading

    env = isolated_env(tmp_path)
    barrier = threading.Barrier(4)
    results: dict = {}

    def start(agent: str) -> None:
        barrier.wait(60)
        try:
            with McpProc(sys.executable, ["-m", "zero_mem.cli", "serve", "--profile", agent, "--enable-write"], env,
                         cwd=tmp_path) as srv:
                srv.initialize()
                add = srv.env("memory_add", {"text": f"{agent} first note", "memory_type": "fact", "scope": "private"})
                results[agent] = (add["status"], "Traceback" in srv.close())
        except BaseException as exc:  # noqa: BLE001
            results[agent] = (repr(exc)[:300], True)

    threads = [threading.Thread(target=start, args=(a,)) for a in ("claude-code", "codex", "hermes", "openclaw")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=240)
    assert results == {a: ("SUCCESS", False) for a in ("claude-code", "codex", "hermes", "openclaw")}, results
