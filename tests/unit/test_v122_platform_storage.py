from __future__ import annotations

import multiprocessing
import os
import time
from pathlib import Path

import pytest

from tests.unit._symlink_guard import require_symlinks

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
    require_symlinks()  # WP-05
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
    require_symlinks()  # WP-05
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(PlatformStorageError) as caught:
        ensure_private_directory(link)
    assert caught.value.code is PlatformErrorCode.UNSAFE_PATH


def test_ensure_private_directory_never_chmods_existing_ancestors(tmp_path: Path) -> None:
    """R124-07/R124-10 regression: creating a leaf under a pre-existing
    directory must NOT chmod the ancestor (e.g. ``/tmp``) to 0o700.

    The pre-fix implementation recursed into ``ensure_private_directory`` for
    every ancestor and chmodded each to 0o700, which fails with EPERM on CI
    runners (``/tmp`` is host-owned) and would corrupt the host if it
    succeeded. Only the leaf created/validated by this call is chmodded.
    """
    ancestor = tmp_path / "ancestor"
    ancestor.mkdir()
    if os.name != "nt":
        os.chmod(ancestor, 0o755)
    leaf = ancestor / "leaf"
    ensure_private_directory(leaf)
    assert leaf.is_dir()
    if os.name == "nt":
        return  # mode bits are not meaningful on Windows
    assert os.stat(ancestor).st_mode & 0o777 == 0o755, "existing ancestor mode must be preserved"
    assert os.stat(leaf).st_mode & 0o777 == 0o700, "leaf must be private"


def test_ensure_private_directory_creates_missing_intermediates(tmp_path: Path) -> None:
    """R124-07: a deep missing path is created with private leaves and
    validated ancestors, without requiring the caller to pre-create parents."""
    root = tmp_path / "a" / "b" / "c"
    ensure_private_directory(root)
    assert root.is_dir()
    assert (tmp_path / "a").is_dir()
