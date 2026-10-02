"""T25 / DEF-190 - canonical-stream lock waits are long, jittered and bounded; contention never surfaces as stream_busy."""
from __future__ import annotations

import multiprocessing
import os
import time
from pathlib import Path

import pytest

from src.storage import platform as P
from tests.unit import _t14_workers as W
from tests.unit.t5_memory_helpers import Env
from zero_mem import learning_settings as ls
from zero_mem.learning import ProposalLog
from zero_mem.provisioning import ProvisioningError, append_canonical_event


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    e.settings = tmp_path / "cfg" / "settings.toml"
    ls.set_value("learning.max_proposals_per_day", "1000", e.settings)
    yield e
    e.close()


def test_lock_wait_seconds_default_and_env(monkeypatch):
    monkeypatch.delenv(P.LOCK_WAIT_ENV, raising=False)
    assert P.lock_wait_seconds() == 30.0
    monkeypatch.setenv(P.LOCK_WAIT_ENV, "2.5")
    assert P.lock_wait_seconds() == 2.5
    for bad in ("abc", "-1", "0", "inf", "nan"):
        monkeypatch.setenv(P.LOCK_WAIT_ENV, bad)
        assert P.lock_wait_seconds() == 30.0


def test_backoff_is_jittered_exponential_and_bounded():
    backoff = P._Backoff()
    delays = [backoff.next(time.monotonic() + 100) for _ in range(12)]
    assert 0.0025 <= delays[0] <= 0.005
    assert all(d <= 0.25 for d in delays) and delays[-1] >= 0.125
    assert backoff.next(time.monotonic() + 0.01) <= 0.011  # never sleeps past the deadline


def test_waiter_survives_a_holder_longer_than_the_old_timeout(env):
    ctx = multiprocessing.get_context("spawn")
    ready, out = ctx.Event(), ctx.Queue()
    stream = env.layout.memory_stream
    holder = ctx.Process(target=W.hold_lock, args=(str(stream.with_name(stream.name + ".lock")), 6.5, ready, out))
    holder.start()
    try:
        assert ready.wait(60)
        started = time.monotonic()
        append_canonical_event(stream, {"event_id": "e-wait", "event_type": "x"})  # old bound: 5 s -> stream_busy
        assert time.monotonic() - started >= 5.0
    finally:
        holder.join(30)
    assert out.get(timeout=10)[0] == "ok"


def test_waiter_gets_typed_stream_busy_only_after_the_bound(env, monkeypatch):
    ctx = multiprocessing.get_context("spawn")
    ready, out = ctx.Event(), ctx.Queue()
    stream = env.layout.memory_stream
    holder = ctx.Process(target=W.hold_lock, args=(str(stream.with_name(stream.name + ".lock")), 4.0, ready, out))
    holder.start()
    try:
        assert ready.wait(60)
        monkeypatch.setenv(P.LOCK_WAIT_ENV, "1")
        started = time.monotonic()
        with pytest.raises(ProvisioningError) as err:
            append_canonical_event(stream, {"event_id": "e-busy", "event_type": "x"})
        assert err.value.code == "stream_busy" and 1.0 <= time.monotonic() - started < 3.5
    finally:
        holder.join(30)


@pytest.mark.parametrize("attempt", range(2))
def test_eight_processes_five_operations_each_never_see_stream_busy(env, monkeypatch, attempt):
    if not os.environ.get(P.LOCK_WAIT_ENV):  # CI may shrink it (and the loop below emulates a slow runner)
        monkeypatch.setenv(P.LOCK_WAIT_ENV, "60")
    root, settings = str(env.root), str(env.settings)
    ctx = multiprocessing.get_context("spawn")
    barrier, out = ctx.Barrier(8), ctx.Queue()
    procs = [ctx.Process(target=W.propose_slow, args=(root, settings, f"agent-{w}", w, 5, 0.01, barrier, out)) for w in range(8)]
    for p in procs:
        p.start()
    results = [out.get(timeout=240) for _ in procs]
    for p in procs:
        p.join(60)
        assert p.exitcode == 0
    assert all(r[0] == "ok" for r in results), results
    statuses = [(s, why) for r in results for s, why, _pid in r[2]]
    assert statuses == [("proposed", None)] * 40, statuses
    assert len(ProposalLog(env.layout.memory_stream).refresh().proposals) == 40
