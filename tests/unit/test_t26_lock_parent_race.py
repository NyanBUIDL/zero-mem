"""T26 / DEF-200 - a lock file whose parent directory is created concurrently (first-run bootstrap) must not fail."""
from __future__ import annotations

import multiprocessing
import os
import threading
import time
from pathlib import Path

import pytest

from src.storage import platform as P
from tests.unit import _t14_workers as W
from zero_mem import learning_settings as ls
from zero_mem import paths
from zero_mem.learning import ProposalLog, learning_lock
from zero_mem.memory_layout import Layout
from zero_mem.provisioning import ProvisioningError, append_canonical_event


def _inject_not_found(monkeypatch, times: int) -> dict:
    """The first ``times`` lock-file opens fail with NOT_FOUND (what the macOS runner saw), then the real open runs."""
    real, state = P.open_regular, {"left": times, "calls": 0}

    def flaky(path, flags, **kw):
        if str(path).endswith((".lock", ".lock.tmp")) or Path(path).name.endswith("lock"):
            state["calls"] += 1
            if state["left"] > 0:
                state["left"] -= 1
                raise P.PlatformStorageError(P.PlatformErrorCode.NOT_FOUND)
        return real(path, flags, **kw)

    monkeypatch.setattr(P, "open_regular", flaky)
    return state


def test_platform_lock_retries_not_found_then_succeeds(tmp_path, monkeypatch):
    state = _inject_not_found(monkeypatch, 3)
    with P.locked(tmp_path / "a.lock", timeout=5):
        pass
    assert state["left"] == 0


def test_platform_lock_gives_up_with_the_original_error_after_the_bounded_retries(tmp_path, monkeypatch):
    _inject_not_found(monkeypatch, 10_000)
    monkeypatch.setattr(P, "_retry_sleep", lambda _d: None)
    with pytest.raises(P.PlatformStorageError) as info:
        with P.locked(tmp_path / "a.lock", timeout=30):
            pass
    assert info.value.code is P.PlatformErrorCode.NOT_FOUND


def test_platform_lock_waits_for_a_parent_created_concurrently(tmp_path):
    parent = tmp_path / "late" / "dir"
    threading.Timer(0.08, lambda: parent.mkdir(parents=True)).start()
    started = time.monotonic()
    with P.locked(parent / "x.lock", timeout=5):
        pass
    assert time.monotonic() - started < 3


def test_lock_with_a_parent_that_is_a_regular_file_fails_fast_and_typed(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    started = time.monotonic()
    with pytest.raises(P.PlatformStorageError) as info:
        with P.locked(blocker / "x.lock", timeout=30):
            pass
    assert time.monotonic() - started < 2
    assert info.value.code in (P.PlatformErrorCode.UNSAFE_PATH, P.PlatformErrorCode.NOT_FOUND, P.PlatformErrorCode.UNAVAILABLE)


def test_learning_lock_and_append_fail_fast_when_the_directory_cannot_exist(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    layout = Layout.resolve(tmp_path / "zm")
    object.__setattr__(layout, "memory_stream", blocker / "stream.jsonl")
    started = time.monotonic()
    with pytest.raises(ProvisioningError):
        with learning_lock(layout):
            pass
    with pytest.raises(ProvisioningError):
        append_canonical_event(blocker / "stream.jsonl", {"event_id": "e", "event_type": "x"})
    assert time.monotonic() - started < 3


def test_learning_lock_and_append_create_a_missing_private_directory(tmp_path):
    layout = Layout.resolve(tmp_path / "zm")  # not ensure()d
    assert not layout.memory_stream.parent.exists()
    with learning_lock(layout):
        pass
    append_canonical_event(layout.memory_stream, {"event_id": "e1", "event_type": "x"})
    assert layout.memory_stream.read_bytes().endswith(b"\n")
    if os.name != "nt":
        assert (layout.memory_stream.parent.stat().st_mode & 0o077) == 0


def test_existing_directory_mode_is_not_touched(tmp_path):
    d = tmp_path / "shared"
    d.mkdir()
    if os.name != "nt":
        d.chmod(0o755)
    paths.ensure_lock_parent(d / "x.lock", "dir")
    if os.name != "nt":
        assert d.stat().st_mode & 0o777 == 0o755


def test_ensure_lock_parent_rejects_a_symlinked_parent(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(paths.SetupError):
        paths.ensure_lock_parent(link / "x.lock", "dir")


@pytest.mark.parametrize("site", ["learning_lock", "append", "learner_state", "settings", "workspaces", "invites"])
def test_every_lock_user_survives_transient_not_found(tmp_path, monkeypatch, site):
    state = _inject_not_found(monkeypatch, 3)
    if site == "learning_lock":
        with learning_lock(Layout.resolve(tmp_path / "zm")):
            pass
    elif site == "append":
        append_canonical_event(tmp_path / "zm" / "s.jsonl", {"event_id": "e", "event_type": "x"})
    elif site == "learner_state":
        from zero_mem import learner

        learner._save_state(tmp_path / "state" / "learn.json", ["k1"])
    elif site == "settings":
        ls.set_value("learning.max_proposals_per_day", "7", tmp_path / "cfg" / "settings.toml")
    elif site == "workspaces":
        from zero_mem import workspaces

        with workspaces._registry_lock(tmp_path / "cfg" / "workspaces.json"):
            pass
    else:
        from zero_mem.share.invite import InviteStore

        with InviteStore(tmp_path / "share")._locked():
            pass
    assert state["left"] == 0 and state["calls"] >= 4


def test_cold_start_six_processes_all_succeed(tmp_path):
    root, settings = str(tmp_path / "zm"), str(tmp_path / "cfg" / "settings.toml")
    ls.set_value("learning.max_proposals_per_day", "1000", Path(settings))
    kinds = ["propose", "direct", "propose", "direct", "propose", "propose"]
    ctx = multiprocessing.get_context("spawn")
    barrier, out = ctx.Barrier(len(kinds)), ctx.Queue()
    procs = [ctx.Process(target=W.cold_start, args=(root, settings, k, i, barrier, out)) for i, k in enumerate(kinds)]
    for p in procs:
        p.start()
    results = [out.get(timeout=180) for _ in procs]
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0
    assert all(r[0] == "ok" for r in results), results
    assert all(r[2][0] in ("proposed", "direct") for r in results), results
    layout = Layout.resolve(Path(root))
    assert len(ProposalLog(layout.memory_stream).refresh().proposals) == 4
