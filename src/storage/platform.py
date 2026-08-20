"""Internal cross-platform storage contract.

Only this module contains platform-specific filesystem and process-lock details.
Domain/storage callers receive stable, sanitized ``PlatformStorageError`` codes.
"""
from __future__ import annotations

import contextlib
import hashlib
import math
import os
import stat
import threading
import time
from dataclasses import dataclass
from enum import Enum
from numbers import Real
from pathlib import Path
from typing import Iterator, Literal

LockMode = Literal["shared", "exclusive"]
DEFAULT_TIMEOUT = 5.0


class PlatformErrorCode(str, Enum):
    LOCK_TIMEOUT = "LOCK_TIMEOUT"
    UNSAFE_PATH = "UNSAFE_PATH"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_FOUND = "NOT_FOUND"
    NOT_REGULAR = "NOT_REGULAR"
    IO_ERROR = "IO_ERROR"


class PlatformStorageError(OSError):
    """Sanitized, domain-facing platform storage failure."""

    def __init__(self, code: PlatformErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True)
class FileIdentity:
    device: int
    inode: int
    size: int
    mtime_ns: int
    digest: str


def _timeout(value: object, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"invalid_{name}")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"invalid_{name}")
    return result


def _check_absolute(path: Path) -> None:
    if not isinstance(path, Path) or not path.is_absolute():
        raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH)


def _posix_parent(path: Path) -> int:
    """Open absolute ancestors without following symlinks (POSIX backend)."""
    _check_absolute(path)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open("/", flags)
    try:
        for component in path.parts[1:-1]:
            next_fd = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except (OSError, ValueError):
        os.close(fd)
        raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH) from None


def _windows_safe(path: Path) -> None:
    _check_absolute(path)
    # Windows exposes reparse points through FILE_ATTRIBUTE_REPARSE_POINT.
    # Rejecting them is fail-closed when a handle-relative equivalent is not
    # available on the running interpreter.
    if os.name == "nt":
        current = path
        while True:
            try:
                attrs = os.lstat(current).st_file_attributes
            except FileNotFoundError:
                current = current.parent
                if current == current.parent:
                    break
                continue
            if attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH)
            if current == Path(current.anchor):
                break
            current = current.parent


def open_parent_dir(path: Path) -> int:
    if os.name == "nt":
        _windows_safe(path)
        raise PlatformStorageError(PlatformErrorCode.UNAVAILABLE)
    return _posix_parent(path)


def open_regular(path: Path, flags: int, *, create: bool = False, mode: int = 0o600) -> int:
    _check_absolute(path)
    if os.name == "nt":
        _windows_safe(path)
        try:
            return os.open(path, flags | (os.O_CREAT if create else 0), mode)
        except FileNotFoundError:
            raise PlatformStorageError(PlatformErrorCode.NOT_FOUND) from None
        except OSError:
            raise PlatformStorageError(PlatformErrorCode.IO_ERROR) from None
    parent = _posix_parent(path)
    try:
        safe_flags = flags | getattr(os, "O_NOFOLLOW", 0)
        if create:
            safe_flags |= os.O_CREAT
        try:
            fd = os.open(path.name, safe_flags, mode, dir_fd=parent)
        except FileNotFoundError:
            raise PlatformStorageError(PlatformErrorCode.NOT_FOUND) from None
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            os.close(fd)
            raise PlatformStorageError(PlatformErrorCode.NOT_REGULAR)
        return fd
    except PlatformStorageError:
        raise
    except OSError:
        raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH) from None
    finally:
        os.close(parent)


def read_bytes(path: Path) -> bytes:
    fd = open_regular(path, os.O_RDONLY)
    try:
        chunks: list[bytes] = []
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                return b"".join(chunks)
            chunks.append(block)
    finally:
        os.close(fd)


def file_identity(path: Path) -> FileIdentity:
    # Linux benchmark/recovery helpers may intentionally pass a process-owned
    # descriptor path.  It is already a kernel-owned handle identity, not an
    # attacker-controlled pathname traversal.
    if os.name != "nt" and len(path.parts) >= 4 and path.parts[1:4] == ("proc", "self", "fd"):
        try:
            fd = os.open(path, os.O_RDONLY)
        except OSError:
            raise PlatformStorageError(PlatformErrorCode.NOT_FOUND) from None
    else:
        fd = open_regular(path, os.O_RDONLY)
    try:
        info = os.fstat(fd)
        digest = hashlib.sha256()
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            digest.update(block)
        return FileIdentity(info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, digest.hexdigest())
    finally:
        os.close(fd)


@contextlib.contextmanager
def locked(path: Path, *, mode: LockMode = "exclusive", timeout: float | None = None, deadline: float | None = None) -> Iterator[None]:
    timeout_value = _timeout(timeout, "lock_timeout")
    deadline_value = _timeout(deadline, "lock_deadline")
    end = deadline_value if deadline_value is not None else time.monotonic() + (DEFAULT_TIMEOUT if timeout_value is None else timeout_value)
    if os.name == "nt":
        try:
            import msvcrt
        except ImportError:
            raise PlatformStorageError(PlatformErrorCode.UNAVAILABLE) from None
        fd = open_regular(path, os.O_CREAT | os.O_RDWR, create=True)
        try:
            while True:
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= end:
                        raise PlatformStorageError(PlatformErrorCode.LOCK_TIMEOUT) from None
                    time.sleep(0.001)
            yield
        finally:
            try:
                msvcrt.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            finally:
                os.close(fd)
        return
    try:
        import fcntl
    except ImportError:
        raise PlatformStorageError(PlatformErrorCode.UNAVAILABLE) from None
    fd = open_regular(path, os.O_CREAT | os.O_RDWR, create=True)
    operation = fcntl.LOCK_SH if mode == "shared" else fcntl.LOCK_EX
    try:
        while True:
            try:
                fcntl.flock(fd, operation | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= end:
                    raise PlatformStorageError(PlatformErrorCode.LOCK_TIMEOUT) from None
                time.sleep(0.001)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


@contextlib.contextmanager
def coordinated(canonical: Path, derived: Path, *, mode: LockMode = "exclusive", timeout: float | None = None, deadline: float | None = None) -> Iterator[None]:
    end = _timeout(deadline, "coordination_deadline")
    if end is None:
        duration = _timeout(timeout, "coordination_timeout")
        end = time.monotonic() + (DEFAULT_TIMEOUT if duration is None else duration)
    with locked(canonical.with_name(canonical.name + ".lock"), mode=mode, deadline=end):
        with locked(derived.with_name(derived.name + ".lock"), mode=mode, deadline=end):
            yield


def safe_unlink(path: Path) -> None:
    _check_absolute(path)
    if os.name == "nt":
        _windows_safe(path)
        try:
            os.unlink(path)
        except FileNotFoundError:
            return
        except OSError:
            raise PlatformStorageError(PlatformErrorCode.IO_ERROR) from None
        return
    parent = _posix_parent(path)
    try:
        try:
            info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH)
        os.unlink(path.name, dir_fd=parent)
    finally:
        os.close(parent)


def ensure_private_directory(path: Path) -> None:
    """Create/validate a directory tree without symlink/reparse nodes."""
    _check_absolute(path)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_dir():
            raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH)
    else:
        ensure_private_directory(path.parent)
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            if path.is_symlink() or not path.is_dir():
                raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH) from None
    _windows_safe(path)
    if os.name != "nt":
        os.chmod(path, 0o700)


def validate_directory(path: Path) -> None:
    _check_absolute(path)
    if path.is_symlink() or not path.is_dir():
        raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH)
    _windows_safe(path)


def atomic_promote(source: Path, destination: Path, *, expected_source: FileIdentity | None = None) -> None:
    """Promote a same-directory regular file with identity fencing."""
    _check_absolute(source)
    _check_absolute(destination)
    if source.parent != destination.parent:
        raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH)
    current = file_identity(source)
    if expected_source is not None and current != expected_source:
        raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH)
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH)
    try:
        os.replace(source, destination)
    except OSError:
        raise PlatformStorageError(PlatformErrorCode.IO_ERROR) from None


def safe_cleanup(path: Path) -> None:
    """Remove only a verified regular file; missing is already clean."""
    safe_unlink(path)


__all__ = ["FileIdentity", "PlatformErrorCode", "PlatformStorageError", "atomic_promote", "coordinated", "ensure_private_directory", "file_identity", "locked", "open_parent_dir", "open_regular", "read_bytes", "safe_cleanup", "safe_unlink", "validate_directory"]
