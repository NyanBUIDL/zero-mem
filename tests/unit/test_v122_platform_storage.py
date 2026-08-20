from __future__ import annotations

import multiprocessing
import os
import time
from pathlib import Path

import pytest

from src.storage.platform import (
    PlatformErrorCode,
    PlatformStorageError,
    atomic_promote,
    ensure_private_directory,
    file_identity,
    locked,
    open_regular,
    read_bytes,
    safe_cleanup,
)


def _hold_mode_lock(path: str, mode: str, ready, release) -> None:
    with locked(Path(path), mode=mode, timeout=2.0):
        ready.put("held")
        release.wait(3.0)


def _abandoned_lock_child(lock_path: str, signal) -> None:
    with locked(Path(lock_path), timeout=1.0):
        signal.put("held")


def _hold_lock(path: str, ready: multiprocessing.Queue, release: multiprocessing.Event) -> None:
    with locked(Path(path), timeout=2.0):
        ready.put("held")
        release.wait(3.0)


def test_concurrent_process_lock_and_timeout(tmp_path: Path) -> None:
    path = tmp_path / "coord.lock"
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Queue()
    release = ctx.Event()
    process = ctx.Process(target=_hold_lock, args=(str(path), ready, release))
    process.start()
    assert ready.get(timeout=3) == "held"
    with pytest.raises(PlatformStorageError) as caught:
        with locked(path, timeout=0.03):
            pass
    assert caught.value.code is PlatformErrorCode.LOCK_TIMEOUT
    release.set()
    process.join(timeout=3)
    assert process.exitcode == 0


def test_abandoned_lock_is_released_by_process_exit(tmp_path: Path) -> None:
    path = tmp_path / "abandoned.lock"
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Queue()
    process = ctx.Process(target=_abandoned_lock_child, args=(str(path), ready))
    process.start()
    assert ready.get(timeout=3) == "held"
    process.join(timeout=3)
    with locked(path, timeout=1.0):
        assert True


def test_symlink_cleanup_and_read_are_fail_closed(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"secret")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(PlatformStorageError) as caught:
        read_bytes(link)
    assert caught.value.code in {PlatformErrorCode.UNSAFE_PATH, PlatformErrorCode.NOT_FOUND}
    with pytest.raises(PlatformStorageError):
        safe_cleanup(link)
    assert target.read_bytes() == b"secret"


def test_identity_fence_and_atomic_promotion(tmp_path: Path) -> None:
    source = tmp_path / "building.sqlite"
    destination = tmp_path / "derived.sqlite"
    source.write_bytes(b"v1")
    identity = file_identity(source)
    source.write_bytes(b"v2")
    with pytest.raises(PlatformStorageError) as caught:
        atomic_promote(source, destination, expected_source=identity)
    assert caught.value.code is PlatformErrorCode.UNSAFE_PATH
    atomic_promote(source, destination)
    assert destination.read_bytes() == b"v2"


def test_open_regular_expected_identity_is_enforced(tmp_path: Path) -> None:
    path = tmp_path / "identity.txt"
    path.write_bytes(b"before")
    expected = file_identity(path)
    path.write_bytes(b"after")
    with pytest.raises(PlatformStorageError) as caught:
        fd = open_regular(path, os.O_RDONLY, expected_identity=expected)
        os.close(fd)
    assert caught.value.code is PlatformErrorCode.UNSAFE_PATH


def test_private_directory_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(PlatformStorageError) as caught:
        ensure_private_directory(link)
    assert caught.value.code is PlatformErrorCode.UNSAFE_PATH
