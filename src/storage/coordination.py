"""Small Linux file-lock coordination domain for canonical/derived storage."""
from __future__ import annotations

import contextlib
import math
import os
import stat
import threading
import time
from pathlib import Path
from numbers import Real
from typing import Iterator, Literal

try:
    import fcntl
except ImportError:  # pragma: no cover - v1.2 support is Linux-qualified
    fcntl = None  # type: ignore[assignment]

LockMode = Literal["shared", "exclusive"]
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
DEFAULT_COORDINATION_TIMEOUT = 5.0


def _validate_timeout(value: object, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"invalid_{name}")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"invalid_{name}")
    return number


def open_parent_dir(path: Path) -> int:
    """Open every absolute ancestor with O_NOFOLLOW and return the parent fd."""
    if fcntl is None or not path.is_absolute():
        raise OSError("coordination_unavailable")
    fd = os.open("/", _DIR_FLAGS)
    try:
        for component in path.parts[1:-1]:
            next_fd = os.open(component, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except Exception:
        os.close(fd)
        raise


def _validate_lock_path(path: Path) -> None:
    if not path.is_absolute() or fcntl is None:
        raise OSError("coordination_unavailable")
    parent_fd = open_parent_dir(path)
    try:
        try:
            info = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise OSError("coordination_lock_unsafe")
    finally:
        os.close(parent_fd)


def _open_lock(path: Path) -> int:
    _validate_lock_path(path)
    parent_fd = open_parent_dir(path)
    try:
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path.name, flags, 0o600, dir_fd=parent_fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            os.close(fd)
            raise OSError("coordination_lock_unsafe")
        os.fchmod(fd, 0o600)
        return fd
    finally:
        os.close(parent_fd)


def read_regular_bytes(path: Path) -> bytes:
    """Read a regular file through a no-follow descriptor and verified identity."""
    parent_fd = open_parent_dir(path)
    try:
        fd = os.open(path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise OSError("path_not_regular")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


def regular_identity(path: Path) -> tuple[int, int]:
    """Return device/inode after secure open, including process-owned fd paths."""
    if len(path.parts) >= 5 and path.parts[1:4] == ("proc", "self", "fd"):
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise OSError("path_not_regular")
            return info.st_dev, info.st_ino
        finally:
            os.close(fd)
    parent_fd = open_parent_dir(path)
    try:
        fd = os.open(path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise OSError("path_not_regular")
            return info.st_dev, info.st_ino
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


@contextlib.contextmanager
def locked(path: Path, *, mode: LockMode = "exclusive", timeout: float | None = None, deadline: float | None = None) -> Iterator[None]:
    timeout = _validate_timeout(timeout, "lock_timeout")
    deadline = _validate_timeout(deadline, "lock_deadline")
    if fcntl is None:
        raise OSError("coordination_unavailable")
    operation = fcntl.LOCK_SH if mode == "shared" else fcntl.LOCK_EX
    fd = _open_lock(path)
    deadline = deadline if deadline is not None else time.monotonic() + (DEFAULT_COORDINATION_TIMEOUT if timeout is None else timeout)
    try:
        for _attempt in range(10_000_000):
            try:
                fcntl.flock(fd, operation | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("coordination_lock_timeout")
                threading.Event().wait(0.001)
        else:
            raise TimeoutError("coordination_lock_timeout")
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


@contextlib.contextmanager
def coordinated(canonical: Path, derived: Path, *, mode: LockMode = "exclusive", timeout: float | None = None, deadline: float | None = None) -> Iterator[None]:
    timeout = _validate_timeout(timeout, "coordination_timeout")
    deadline = _validate_timeout(deadline, "coordination_deadline")
    canonical_lock = canonical.with_name(canonical.name + ".lock")
    derived_lock = derived.with_name(derived.name + ".lock")
    operation_deadline = deadline if deadline is not None else time.monotonic() + (DEFAULT_COORDINATION_TIMEOUT if timeout is None else timeout)
    with locked(canonical_lock, mode=mode, deadline=operation_deadline):
        with locked(derived_lock, mode=mode, deadline=operation_deadline):
            yield


__all__ = ["coordinated", "locked", "open_parent_dir", "read_regular_bytes", "regular_identity", "DEFAULT_COORDINATION_TIMEOUT"]
