"""T5 - several agent processes on one data root (the shared-memory topology)."""
from __future__ import annotations

import json
import multiprocessing
import sqlite3

import pytest

from tests.unit import _t5_workers as W
from tests.unit.t5_memory_helpers import Env


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    e.close()


def _spawn(targets_args, barrier_parties=None):
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(barrier_parties or len(targets_args))
    out = ctx.Queue()
    procs = [ctx.Process(target=t, args=(*a, barrier, out)) for t, a in targets_args]
    for p in procs:
        p.start()
    results = [out.get(timeout=180) for _ in procs]
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0
    return results


def test_four_processes_add_concurrently_with_no_loss_duplicate_or_crash(env):
    root = str(env.root)
    shared_text = "one logical source written by every process at the same moment"
    results = _spawn([(W.add_many, (root, f"agent-{w}", w, 12, shared_text)) for w in range(4)])
    assert all(r[0] == "ok" for r in results), results
    # 4 processes x 12 own facts + the shared text (profile-private per agent => one source per profile)
    lines = env.registry_lines()
    refs = [l["external_ref"] + "|" + l["profile_id"] for l in lines]
    assert len(refs) == len(set(refs)) == 4 * 12 + 4
    conn = sqlite3.connect(env.layout.derived_db)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM zm_corpus_sources").fetchone()[0] == 52
        assert conn.execute("SELECT COUNT(*) FROM zm_corpus_units").fetchone()[0] == 52
        assert conn.execute("SELECT COUNT(*) FROM zm_corpus_fts").fetchone()[0] == 52
    finally:
        conn.close()
    for line in env.registry_lines():
        assert line["blob_ref"] and (env.layout.corpus_root / "blobs" / line["blob_ref"][:2] / line["blob_ref"]).is_file()


def test_the_same_profile_in_four_processes_registers_a_shared_fact_exactly_once(env):
    root = str(env.root)
    shared_text = "identical text from four processes of the very same agent"
    results = _spawn([(W.add_many, (root, "claude-code", w, 0, shared_text)) for w in range(4)])
    assert all(r[0] == "ok" for r in results), results
    statuses = sorted(r[2][-1] for r in results)
    assert statuses == ["created", "unchanged", "unchanged", "unchanged"]
    assert len(env.registry_lines()) == 1 and env.units() == [shared_text]


def test_readers_never_see_errors_while_writers_add(env):
    ctx = multiprocessing.get_context("spawn")
    out_r = ctx.Queue()
    env.open("claude-code").add("seed fact about topic 1")
    readers = [ctx.Process(target=W.read_loop, args=(str(env.root), "claude-code", "topic", 4.0, out_r)) for _ in range(2)]
    for r in readers:
        r.start()
    results = _spawn([(W.add_many, (str(env.root), "claude-code", w, 10, f"shared {w}")) for w in range(3)])
    assert all(r[0] == "ok" for r in results), results
    reads = [out_r.get(timeout=120) for _ in readers]
    for r in readers:
        r.join(timeout=60)
    assert all(x[0] == "ok" for x in reads), reads
    assert sum(x[1] for x in reads) > 0 and sum(x[2] for x in reads) == 0, reads


def test_forget_racing_with_adds_leaves_a_consistent_store(env):
    m = env.open("claude-code")
    victim = m.add("victim fact about gazelles")
    results = _spawn([(W.forget_while_adding, (str(env.root), "claude-code", victim.source_id)),
                      (W.add_many, (str(env.root), "claude-code", 1, 8, "shared during forget"))])
    assert all(r[0] == "ok" for r in results), results
    assert m.recall("gazelles").status == "empty"
    assert m.recall("concurrently").status == "ok"
    st = m.status()
    assert st["needs_rebuild"] is False and st["sources"]["forgotten"] == 1
    lines = env.registry_lines()
    assert [json.loads(json.dumps(l))["lifecycle_status"] for l in lines if l["source_id"] == victim.source_id] == [
        "observed", "deleted"]
