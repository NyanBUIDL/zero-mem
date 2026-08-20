from __future__ import annotations

import multiprocessing
import time
from pathlib import Path

import pytest

from src.storage.platform import PlatformErrorCode, PlatformStorageError, locked


def _hold(path: str, mode: str, ready, release) -> None:
    with locked(Path(path), mode=mode, timeout=2.0):
        ready.put("held")
        release.wait(3.0)


def _start(ctx, path: Path, mode: str):
    ready = ctx.Queue()
    release = ctx.Event()
    process = ctx.Process(target=_hold, args=(str(path), mode, ready, release))
    process.start()
    assert ready.get(timeout=3) == "held"
    return process, release


def test_shared_holders_are_compatible_but_exclusive_conflicts(tmp_path: Path) -> None:
    ctx = multiprocessing.get_context("spawn")
    path = tmp_path / "mode.lock"
    first, release = _start(ctx, path, "shared")
    with locked(path, mode="shared", timeout=0.2):
        with pytest.raises(PlatformStorageError) as caught:
            with locked(path, mode="exclusive", timeout=0.03):
                pass
        assert caught.value.code is PlatformErrorCode.LOCK_TIMEOUT
    release.set()
    first.join(timeout=3)
    assert first.exitcode == 0


def test_exclusive_conflicts_with_shared_and_exclusive(tmp_path: Path) -> None:
    ctx = multiprocessing.get_context("spawn")
    path = tmp_path / "mode.lock"
    first, release = _start(ctx, path, "exclusive")
    for mode in ("shared", "exclusive"):
        with pytest.raises(PlatformStorageError) as caught:
            with locked(path, mode=mode, timeout=0.03):
                pass
        assert caught.value.code is PlatformErrorCode.LOCK_TIMEOUT
    release.set()
    first.join(timeout=3)
    assert first.exitcode == 0
