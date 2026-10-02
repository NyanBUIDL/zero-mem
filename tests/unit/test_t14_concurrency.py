"""T14 - concurrent proposals from four processes: no crash, none lost, limits and duplicate collapse hold."""
from __future__ import annotations

import json
import multiprocessing

import pytest

from tests.unit import _t14_workers as W
from tests.unit.t5_memory_helpers import Env
from zero_mem import learning_settings as ls
from zero_mem.learning import ProposalLog, Reviewer


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    e.settings = tmp_path / "cfg" / "settings.toml"
    yield e
    e.close()


def _spawn(targets_args):
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(len(targets_args))
    out = ctx.Queue()
    procs = [ctx.Process(target=t, args=(*a, barrier, out)) for t, a in targets_args]
    for p in procs:
        p.start()
    results = [out.get(timeout=180) for _ in procs]
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0
    return results


def _stream_is_intact(env):
    raw = env.layout.memory_stream.read_bytes()
    assert raw == b"" or raw.endswith(b"\n")
    for line in raw.splitlines():
        json.loads(line)


@pytest.mark.parametrize("attempt", range(4))
def test_four_processes_propose_with_no_loss_or_crash(env, attempt):
    ls.set_value("learning.max_proposals_per_day", "1000", env.settings)
    root, settings = str(env.root), str(env.settings)
    same = "identical gotcha text proposed by every process"
    results = _spawn([(W.propose_many, (root, settings, f"agent-{w}", w, 10, same)) for w in range(4)])
    assert all(r[0] == "ok" for r in results), results
    assert all(status == "proposed" for r in results for status, _reason, _pid in r[2])  # distinct profiles: no merge
    log = ProposalLog(env.layout.memory_stream).refresh()
    assert len(log.proposals) == 4 * 11
    ids = [pid for r in results for _s, _r, pid in r[2]]
    assert len(ids) == len(set(ids)) == 44 and set(ids) == set(log.proposals)
    _stream_is_intact(env)
    assert env.registry_lines() == []  # nothing became a source


@pytest.mark.parametrize("attempt", range(3))
def test_the_same_profile_in_four_processes_collapses_duplicates_exactly(env, attempt):
    ls.set_value("learning.max_proposals_per_day", "1000", env.settings)
    root, settings = str(env.root), str(env.settings)
    same = "one logical gotcha written by four processes of the same agent"
    results = _spawn([(W.propose_many, (root, settings, "claude-code", w, 0, same)) for w in range(4)])
    assert all(r[0] == "ok" for r in results), results
    statuses = sorted(r[2][-1][0] for r in results)
    assert statuses == ["merged", "merged", "merged", "proposed"]
    (p,) = ProposalLog(env.layout.memory_stream).refresh().proposals.values()
    assert p.seen == 4 and sorted(p.evidence) == [f"worker-{w}" for w in range(4)]
    _stream_is_intact(env)


@pytest.mark.parametrize("attempt", range(3))
def test_the_daily_limit_is_exact_under_a_race(env, attempt):
    ls.set_value("learning.max_proposals_per_day", "5", env.settings)
    root, settings = str(env.root), str(env.settings)
    results = _spawn([(W.propose_many, (root, settings, "claude-code", w, 6, "")) for w in range(4)])
    assert all(r[0] == "ok" for r in results), results
    flat = [(s, why) for r in results for s, why, _pid in r[2]]
    assert sum(1 for s, _ in flat if s == "proposed") == 5
    assert all(why == "daily_limit" for s, why in flat if s == "rejected")
    assert len(ProposalLog(env.layout.memory_stream).refresh().proposals) == 5


def test_review_while_agents_propose_keeps_every_proposal_and_creates_one_source_per_approval(env):
    ls.set_value("learning.max_proposals_per_day", "1000", env.settings)
    root, settings = str(env.root), str(env.settings)
    work = [(W.propose_many, (root, settings, f"agent-{w}", w, 6, "")) for w in range(3)]
    work.append((W.review_while_proposing, (root, settings, "owner")))
    results = _spawn(work)
    assert all(r[0] == "ok" for r in results), results
    reviewer = Reviewer(env.layout, operator="owner", settings_path=env.settings)
    rows = reviewer.list("all")
    assert len(rows) == 18
    for row in reviewer.list("pending"):  # whatever the racing reviewer missed
        assert reviewer.approve(row["id"]).status == "approved"
    rows = reviewer.list("approved")
    assert len(rows) == 18
    sources = {r["source_id"] for r in rows}
    assert len(sources) == 18 and len(env.registry_lines()) == 18
    _stream_is_intact(env)
