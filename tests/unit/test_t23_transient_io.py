"""T23 / DEF-170 - transient OS errors on the canonical stream and its locks must never surface as 'error'."""
from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from src.storage import platform as P
from tests.unit.t5_memory_helpers import Env
from zero_mem import learning_settings as ls
from zero_mem.learning import ProposalLog
from zero_mem.provisioning import ProvisioningError, append_canonical_event


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "_retry_sleep", lambda _s: None, raising=False)
    e = Env(tmp_path)
    e.settings = tmp_path / "cfg" / "settings.toml"
    ls.set_value("learning.max_proposals_per_day", "1000", e.settings)
    yield e
    e.close()


def _mem(env, profile="claude-code"):
    from zero_mem.memory import Memory

    return Memory.open(profile, data_root=Path(env.root), settings_path=Path(env.settings))


def _fail_first(monkeypatch, module, name, exc_factory, times, match=lambda *a, **k: True):
    real = getattr(module, name)
    state = {"left": times}

    def wrapper(*a, **k):
        if state["left"] > 0 and match(*a, **k):
            state["left"] -= 1
            raise exc_factory()
        return real(*a, **k)

    monkeypatch.setattr(module, name, wrapper)
    return state


@pytest.mark.parametrize("code", [errno.EINTR, errno.EAGAIN, errno.EACCES])
def test_flock_transient_errors_are_retried(env, monkeypatch, code):
    fcntl = pytest.importorskip("fcntl")
    state = _fail_first(monkeypatch, fcntl, "flock", lambda: OSError(code, os.strerror(code)), 3)
    res = _mem(env).propose("a retried lock text", "rule", scope="shared")
    assert res.status == "proposed", (res.status, res.reason)
    assert state["left"] == 0


def test_lock_file_open_transient_denial_is_retried(env, monkeypatch):
    state = _fail_first(monkeypatch, os, "open", lambda: PermissionError(errno.EACCES, "denied"), 2,
                        match=lambda path, *a, **k: str(path).endswith(".lock"))
    res = _mem(env).propose("a retried lock-open text", "rule", scope="shared")
    assert res.status == "proposed", (res.status, res.reason)
    assert state["left"] == 0


@pytest.mark.parametrize("code", [errno.EINTR, errno.EAGAIN, errno.EACCES])
def test_stream_append_transient_errors_are_retried_without_duplicating(env, monkeypatch, code):
    stream = env.layout.memory_stream
    state = _fail_first(monkeypatch, os, "open", lambda: OSError(code, os.strerror(code)), 3,
                        match=lambda path, *a, **k: Path(str(path)) == stream)
    append_canonical_event(stream, {"event_id": "e-1", "event_type": "x"})
    assert state["left"] == 0
    assert stream.read_bytes().count(b"\n") == 1


def test_fsync_failure_after_write_is_not_retried(env, monkeypatch):
    stream = env.layout.memory_stream
    monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError(errno.EAGAIN, "again")))
    with pytest.raises(ProvisioningError) as err:
        append_canonical_event(stream, {"event_id": "e-1", "event_type": "x"})
    assert err.value.code == "stream_unwritable"
    assert stream.read_bytes().count(b"\n") == 1  # exactly one copy, never re-sent


def test_persistent_denial_is_bounded_and_typed(env, monkeypatch):
    stream = env.layout.memory_stream
    calls = []
    real = os.open

    def deny(path, *a, **k):
        if Path(str(path)) == stream:
            calls.append(1)
            raise PermissionError(errno.EACCES, "denied")
        return real(path, *a, **k)

    monkeypatch.setattr(os, "open", deny)
    with pytest.raises(ProvisioningError) as err:
        append_canonical_event(stream, {"event_id": "e-1", "event_type": "x"})
    assert err.value.code == "stream_unwritable" and 1 < len(calls) <= 12


def test_lock_wait_longer_than_five_seconds_default_still_succeeds(env, monkeypatch):
    """The provisioning/learning locks wait up to 30 s (not the 5 s platform default) and a timeout is typed stream_busy."""
    fcntl = pytest.importorskip("fcntl")
    clock = {"t": 0.0}
    monkeypatch.setattr(P.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(P.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + 1.0))
    real = fcntl.flock
    left = {"n": 10}  # 10 s of contention > the 5 s default

    def contended(fd, op):
        if left["n"] > 0 and op & fcntl.LOCK_NB:
            left["n"] -= 1
            raise BlockingIOError(errno.EAGAIN, "busy")
        return real(fd, op)

    monkeypatch.setattr(fcntl, "flock", contended)
    append_canonical_event(env.layout.memory_stream, {"event_id": "e-1", "event_type": "x"})
    left["n"] = 10**6
    with pytest.raises(ProvisioningError) as err:
        append_canonical_event(env.layout.memory_stream, {"event_id": "e-2", "event_type": "x"})
    assert err.value.code == "stream_busy"


def test_dedupe_ignores_a_torn_trailing_line_written_by_another_process(env):
    mem = _mem(env)
    assert mem.propose("same text for torn", "rule", scope="shared").status == "proposed"
    log = ProposalLog(env.layout.memory_stream).refresh()
    with open(env.layout.memory_stream, "ab") as fh:
        fh.write(b'{"event_type":"learning_proposal","partial')  # another process mid-append
    assert len(ProposalLog(env.layout.memory_stream).refresh().proposals) == 1
    assert len(log.refresh().proposals) == 1
