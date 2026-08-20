"""Internal cross-platform storage contract.

Only this module contains platform-specific filesystem and process-lock details.
Domain/storage callers receive stable, sanitized ``PlatformStorageError`` codes.
"""
from __future__ import annotations

import contextlib
import ctypes
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
NO_FOLLOW = getattr(os, "O_NOFOLLOW", 0)
DIRECTORY_FLAG = getattr(os, "O_DIRECTORY", 0)


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


def _is_regular_stat(info: os.stat_result) -> bool:
    return stat.S_ISREG(info.st_mode) and not bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def is_regular_info(info: os.stat_result) -> bool:
    return _is_regular_stat(info)


def is_symlink_info(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode)


def validate_path(path: Path, *, allow_missing: bool = False) -> None:
    _check_absolute(path)
    for current in (path, *path.parents):
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH) from None
        if stat.S_ISLNK(info.st_mode):
            raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH)
        if current == path and not allow_missing and not _is_regular_stat(info):
            raise PlatformStorageError(PlatformErrorCode.NOT_REGULAR)
        if current == path and allow_missing and stat.S_ISDIR(info.st_mode):
            raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH)


def _identity_from_stat(info: os.stat_result, digest: str = "") -> FileIdentity:
    return FileIdentity(info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, digest)


def _windows_kernel32():
    try:
        return ctypes.WinDLL("kernel32", use_last_error=True)
    except (AttributeError, OSError):
        raise PlatformStorageError(PlatformErrorCode.UNAVAILABLE) from None


def _windows_handle_identity(fd: int) -> tuple[int, int]:
    """Return volume/file-index identity, or fail closed."""
    if os.name != "nt":
        raise PlatformStorageError(PlatformErrorCode.UNAVAILABLE)
    try:
        import msvcrt
        handle = msvcrt.get_osfhandle(fd)
        if handle == -1:
            raise PlatformStorageError(PlatformErrorCode.UNAVAILABLE)
        class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
            _pack_ = 4
            _fields_ = [
                ("attributes", ctypes.c_uint32),
                ("created_low", ctypes.c_uint32), ("created_high", ctypes.c_uint32),
                ("accessed_low", ctypes.c_uint32), ("accessed_high", ctypes.c_uint32),
                ("written_low", ctypes.c_uint32), ("written_high", ctypes.c_uint32),
                ("volume", ctypes.c_uint32),
                ("size_high", ctypes.c_uint32), ("size_low", ctypes.c_uint32),
                ("links", ctypes.c_uint32),
                ("file_index_high", ctypes.c_uint32), ("file_index_low", ctypes.c_uint32),
            ]
        kernel32 = _windows_kernel32()
        get_info = kernel32.GetFileInformationByHandle
        get_info.argtypes = [ctypes.c_void_p, ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION)]
        get_info.restype = ctypes.c_int
        info = _BY_HANDLE_FILE_INFORMATION()
        if not get_info(ctypes.c_void_p(handle), ctypes.byref(info)):
            raise PlatformStorageError(PlatformErrorCode.UNAVAILABLE)
        if info.attributes & 0x10 or info.attributes & 0x400:
            raise PlatformStorageError(PlatformErrorCode.NOT_REGULAR)
        return info.volume, (info.file_index_high << 32) | info.file_index_low
    except PlatformStorageError:
        raise
    except (ImportError, OSError, ValueError, TypeError):
        raise PlatformStorageError(PlatformErrorCode.UNAVAILABLE) from None


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
            except OSError:
                raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH) from None
            if attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH)
            if current == Path(current.anchor):
                break
            current = current.parent


def open_parent_dir(path: Path) -> int | Path:
    if os.name == "nt":
        _windows_safe(path)
        return path.parent
    return _posix_parent(path)


def _open_flags(access: str, *, append: bool = False, create: bool = False, exclusive: bool = False, nonblocking: bool = False) -> int:
    if access == "read":
        flags = os.O_RDONLY
    elif access == "write":
        flags = os.O_WRONLY
    elif access == "readwrite":
        flags = os.O_RDWR
    else:
        raise ValueError("invalid_access")
    if append:
        flags |= os.O_APPEND
    if create:
        flags |= os.O_CREAT
    if exclusive:
        flags |= os.O_EXCL
    if nonblocking and hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    return flags


def open_relative(parent: int | Path, name: str, *, access: str = "read", append: bool = False, create: bool = False, exclusive: bool = False, nonblocking: bool = False, mode: int = 0o600) -> int:
    flags = _open_flags(access, append=append, create=create, exclusive=exclusive, nonblocking=nonblocking)
    try:
        if isinstance(parent, Path):
            return open_regular(parent / name, flags, create=create or bool(flags & os.O_CREAT), exclusive=exclusive or bool(flags & os.O_EXCL), mode=mode)
        return os.open(name, flags | getattr(os, "O_NOFOLLOW", 0), mode, dir_fd=parent)
    except PlatformStorageError:
        raise
    except FileNotFoundError:
        raise PlatformStorageError(PlatformErrorCode.NOT_FOUND) from None
    except OSError:
        raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH) from None


def stat_relative(parent: int | Path, name: str) -> os.stat_result:
    try:
        if isinstance(parent, Path) and os.name == "nt":
            fd = open_regular(parent / name, os.O_RDONLY)
            try:
                return os.fstat(fd)
            finally:
                close_handle(fd)
        if isinstance(parent, Path):
            return os.stat(parent / name, follow_symlinks=False)
        return os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        raise PlatformStorageError(PlatformErrorCode.NOT_FOUND) from None
    except OSError:
        raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH) from None


def _windows_delete_path(path: Path) -> None:
    fd = open_regular(path, os.O_RDWR, delete=True)
    try:
        kernel32 = _windows_kernel32()
        class _FILE_DISPOSITION_INFO(ctypes.Structure):
            _fields_ = [("delete_file", ctypes.c_int)]
        disposition = _FILE_DISPOSITION_INFO(1)
        set_file_info = kernel32.SetFileInformationByHandle
        set_file_info.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
        set_file_info.restype = ctypes.c_int
        import msvcrt
        if not set_file_info(ctypes.c_void_p(msvcrt.get_osfhandle(fd)), 4, ctypes.byref(disposition), ctypes.sizeof(disposition)):
            raise PlatformStorageError(PlatformErrorCode.UNAVAILABLE)
    finally:
        close_handle(fd)


def _windows_rename_path(source: Path, destination: Path) -> None:
    fd = open_regular(source, os.O_RDWR, delete=True)
    try:
        _windows_replace_handle(fd, source, destination)
    finally:
        close_handle(fd)


def unlink_relative(parent: int | Path, name: str) -> None:
    try:
        if isinstance(parent, Path):
            if os.name == "nt":
                _windows_delete_path(parent / name)
            else:
                os.unlink(parent / name)
        else:
            os.unlink(name, dir_fd=parent)
    except FileNotFoundError:
        return
    except OSError:
        raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH) from None


def rename_relative(parent: int | Path, source: str, destination: str) -> None:
    try:
        if isinstance(parent, Path):
            if os.name == "nt":
                _windows_rename_path(parent / source, parent / destination)
            else:
                os.replace(parent / source, parent / destination)
        else:
            os.replace(source, destination, src_dir_fd=parent, dst_dir_fd=parent)
    except OSError:
        raise PlatformStorageError(PlatformErrorCode.IO_ERROR) from None


def list_relative(parent: int | Path) -> list[str]:
    try:
        return os.listdir(parent)
    except OSError:
        raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH) from None


def open_regular(path: Path, flags: int, *, create: bool = False, exclusive: bool = False, mode: int = 0o600, delete: bool = False, expected_identity: FileIdentity | None = None) -> int:
    _check_absolute(path)
    if os.name == "nt":
        _windows_safe(path)
        try:
            import msvcrt
            kernel32 = _windows_kernel32()
            create_file = kernel32.CreateFileW
            create_file.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
            create_file.restype = ctypes.c_void_p
            desired = 0
            if flags & os.O_RDWR:
                desired |= 0x80000000 | 0x40000000
            elif flags & os.O_WRONLY:
                desired |= 0x40000000
            else:
                desired |= 0x80000000
            if delete:
                desired |= 0x00010000
            share = 0x00000001 | 0x00000002 | 0x00000004
            disposition = 1 if exclusive else 4 if create else 3
            handle = create_file(str(path), desired, share, None, disposition, 0x00200000, None)
            if handle in (None, ctypes.c_void_p(-1).value):
                raise OSError
            fd_flags = os.O_RDWR if (flags & os.O_RDWR) else os.O_WRONLY if (flags & os.O_WRONLY) else os.O_RDONLY
            if flags & os.O_APPEND:
                fd_flags |= os.O_APPEND
            fd = msvcrt.open_osfhandle(handle, fd_flags)
            info = os.fstat(fd)
            if not _is_regular_stat(info):
                os.close(fd)
                raise PlatformStorageError(PlatformErrorCode.NOT_REGULAR)
            handle_identity = _windows_handle_identity(fd)
            if expected_identity is not None and (
                handle_identity != (expected_identity.device, expected_identity.inode)
                or info.st_size != expected_identity.size
                or info.st_mtime_ns != expected_identity.mtime_ns
                or (expected_identity.digest and _digest_handle(fd) != expected_identity.digest)
            ):
                os.close(fd)
                raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH)
            return fd
        except PlatformStorageError:
            raise
        except FileNotFoundError:
            raise PlatformStorageError(PlatformErrorCode.NOT_FOUND) from None
        except OSError:
            raise PlatformStorageError(PlatformErrorCode.UNAVAILABLE) from None
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
        if not _is_regular_stat(info):
            os.close(fd)
            raise PlatformStorageError(PlatformErrorCode.NOT_REGULAR)
        if expected_identity is not None and (
            (info.st_dev, info.st_ino) != (expected_identity.device, expected_identity.inode)
            or info.st_size != expected_identity.size
            or info.st_mtime_ns != expected_identity.mtime_ns
            or (expected_identity.digest and _digest_handle(fd) != expected_identity.digest)
        ):
            os.close(fd)
            raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH)
        return fd
    except PlatformStorageError:
        raise
    except OSError:
        raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH) from None
    finally:
        os.close(parent)


def paths_alias(first: Path, second: Path) -> bool:
    first_fd = second_fd = None
    try:
        try:
            first_fd = open_regular(first, os.O_RDONLY)
            second_fd = open_regular(second, os.O_RDONLY)
        except PlatformStorageError as exc:
            if exc.code is PlatformErrorCode.NOT_FOUND:
                return False
            raise
        if os.name == "nt":
            first_identity = _windows_handle_identity(first_fd)
            second_identity = _windows_handle_identity(second_fd)
        else:
            first_info = os.fstat(first_fd)
            second_info = os.fstat(second_fd)
            first_identity = (first_info.st_dev, first_info.st_ino)
            second_identity = (second_info.st_dev, second_info.st_ino)
        return first_identity == second_identity
    finally:
        if first_fd is not None:
            os.close(first_fd)
        if second_fd is not None:
            os.close(second_fd)


def read_bytes(path: Path) -> bytes:
    fd = open_regular(path, os.O_RDONLY)
    try:
        return read_all(fd)
    finally:
        close_handle(fd)


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
        return _identity_from_fd(fd)
    except PlatformStorageError:
        raise
    except OSError:
        raise PlatformStorageError(PlatformErrorCode.IO_ERROR) from None
    finally:
        close_handle(fd)


@contextlib.contextmanager
def locked(path: Path, *, mode: LockMode = "exclusive", timeout: float | None = None, deadline: float | None = None) -> Iterator[None]:
    if mode not in {"shared", "exclusive"}:
        raise ValueError("invalid_lock_mode")
    timeout_value = _timeout(timeout, "lock_timeout")
    deadline_value = _timeout(deadline, "lock_deadline")
    end = deadline_value if deadline_value is not None else time.monotonic() + (DEFAULT_TIMEOUT if timeout_value is None else timeout_value)
    if os.name == "nt":
        # LockFileEx is range-based and supports true shared locks when
        # LOCKFILE_EXCLUSIVE_LOCK is omitted.  msvcrt.locking cannot express
        # that distinction and is therefore intentionally not used.
        try:
            import msvcrt
            kernel32 = _windows_kernel32()
        except (ImportError, AttributeError):
            raise PlatformStorageError(PlatformErrorCode.UNAVAILABLE) from None
        class _OVERLAPPED(ctypes.Structure):
            _fields_ = [("internal", ctypes.c_void_p), ("internal_high", ctypes.c_void_p),
                        ("offset", ctypes.c_uint32), ("offset_high", ctypes.c_uint32),
                        ("event", ctypes.c_void_p)]
        lock_file = kernel32.LockFileEx
        lock_file.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(_OVERLAPPED)]
        lock_file.restype = ctypes.c_int
        unlock_file = kernel32.UnlockFileEx
        unlock_file.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(_OVERLAPPED)]
        unlock_file.restype = ctypes.c_int
        fd = open_regular(path, os.O_CREAT | os.O_RDWR, create=True)
        handle = msvcrt.get_osfhandle(fd)
        overlapped = _OVERLAPPED()
        flags = 0x00000001 | (0x00000002 if mode == "exclusive" else 0)
        acquired = False
        try:
            while True:
                ok = lock_file(
                    ctypes.c_void_p(handle), flags, 0, 0xFFFFFFFF, 0xFFFFFFFF,
                    ctypes.byref(overlapped),
                )
                if ok:
                    acquired = True
                    break
                if time.monotonic() >= end:
                    raise PlatformStorageError(PlatformErrorCode.LOCK_TIMEOUT) from None
                time.sleep(0.001)
            yield
        except PlatformStorageError:
            raise
        except OSError:
            raise PlatformStorageError(PlatformErrorCode.UNAVAILABLE) from None
        finally:
            if acquired:
                if not unlock_file(
                    ctypes.c_void_p(handle), 0, 0xFFFFFFFF, 0xFFFFFFFF,
                    ctypes.byref(overlapped),
                ):
                    raise PlatformStorageError(PlatformErrorCode.UNAVAILABLE)
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
            except OSError:
                raise PlatformStorageError(PlatformErrorCode.UNAVAILABLE) from None
        yield
    except PlatformStorageError:
        raise
    except OSError:
        raise PlatformStorageError(PlatformErrorCode.UNAVAILABLE) from None
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            raise PlatformStorageError(PlatformErrorCode.UNAVAILABLE) from None
        finally:
            close_handle(fd)


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
    try:
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
        set_mode(path, 0o700)
    except PlatformStorageError:
        raise
    except FileExistsError:
        raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH) from None
    except OSError:
        raise PlatformStorageError(PlatformErrorCode.IO_ERROR) from None


def validate_directory(path: Path) -> None:
    _check_absolute(path)
    if path.is_symlink() or not path.is_dir():
        raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH)
    _windows_safe(path)


def read_all(fd: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        try:
            block = os.read(fd, 1024 * 1024)
        except InterruptedError:
            continue
        except OSError:
            raise PlatformStorageError(PlatformErrorCode.IO_ERROR) from None
        if not block:
            return b"".join(chunks)
        chunks.append(block)


def read_from(fd: int, offset: int) -> bytes:
    try:
        os.lseek(fd, offset, os.SEEK_SET)
    except OSError:
        raise PlatformStorageError(PlatformErrorCode.IO_ERROR) from None
    return read_all(fd)


def handle_info(fd: int) -> os.stat_result:
    try:
        return os.fstat(fd)
    except OSError:
        raise PlatformStorageError(PlatformErrorCode.IO_ERROR) from None


def handle_size(fd: int) -> int:
    try:
        return os.fstat(fd).st_size
    except OSError:
        raise PlatformStorageError(PlatformErrorCode.IO_ERROR) from None


def write_all(fd: int, data: bytes) -> None:
    """Write every byte, tolerating EINTR and rejecting zero progress."""
    view = memoryview(data)
    offset = 0
    while offset < len(view):
        try:
            count = os.write(fd, view[offset:])
        except InterruptedError:
            continue
        except OSError:
            raise PlatformStorageError(PlatformErrorCode.IO_ERROR) from None
        if not isinstance(count, int) or count <= 0 or count > len(view) - offset:
            raise PlatformStorageError(PlatformErrorCode.IO_ERROR)
        offset += count


def fsync_handle(fd: int) -> None:
    try:
        os.fsync(fd)
    except OSError:
        raise PlatformStorageError(PlatformErrorCode.IO_ERROR) from None


def close_handle(fd: int | Path) -> None:
    if isinstance(fd, Path):
        return
    try:
        os.close(fd)
    except OSError:
        raise PlatformStorageError(PlatformErrorCode.IO_ERROR) from None


def set_mode(path: Path, mode: int) -> None:
    if os.name == "nt":
        return
    try:
        os.chmod(path, mode)
    except OSError:
        raise PlatformStorageError(PlatformErrorCode.IO_ERROR) from None


def _digest_handle(fd: int) -> str:
    try:
        position = os.lseek(fd, 0, os.SEEK_CUR)
        os.lseek(fd, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            digest.update(block)
        os.lseek(fd, position, os.SEEK_SET)
        return digest.hexdigest()
    except OSError:
        raise PlatformStorageError(PlatformErrorCode.IO_ERROR) from None


def _identity_from_fd(fd: int) -> FileIdentity:
    info = os.fstat(fd)
    digest_value = _digest_handle(fd)
    if os.name == "nt":
        device, inode = _windows_handle_identity(fd)
    else:
        device, inode = info.st_dev, info.st_ino
    return FileIdentity(device, inode, info.st_size, info.st_mtime_ns, digest_value)


def _windows_volume_root(path: Path) -> str:
    kernel32 = _windows_kernel32()
    get_volume = kernel32.GetVolumePathNameW
    get_volume.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    get_volume.restype = ctypes.c_int
    buffer = ctypes.create_unicode_buffer(32768)
    if not get_volume(str(path), buffer, len(buffer)):
        raise PlatformStorageError(PlatformErrorCode.UNAVAILABLE)
    return buffer.value.casefold()


def _windows_replace_handle(fd: int, source: Path, destination: Path) -> None:
    """Rename an already-open source handle atomically on Windows."""
    try:
        _windows_safe(destination)
        if _windows_volume_root(source) != _windows_volume_root(destination):
            raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH)
        import msvcrt
        kernel32 = _windows_kernel32()
        handle = msvcrt.get_osfhandle(fd)
        encoded = str(destination).encode("utf-16-le")
        pointer_size = ctypes.sizeof(ctypes.c_void_p)
        root_offset = pointer_size
        length_offset = root_offset + pointer_size
        name_offset = length_offset + ctypes.sizeof(ctypes.c_uint32)
        buffer = ctypes.create_string_buffer(name_offset + len(encoded) + 2)
        ctypes.c_uint32.from_buffer(buffer, 0).value = 0x00000001 | 0x00000002
        ctypes.c_void_p.from_buffer(buffer, root_offset).value = 0
        ctypes.c_uint32.from_buffer(buffer, length_offset).value = len(encoded)
        ctypes.memmove(ctypes.addressof(buffer) + name_offset, encoded, len(encoded))
        set_file_info = kernel32.SetFileInformationByHandle
        set_file_info.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
        set_file_info.restype = ctypes.c_int
        ok = set_file_info(
            ctypes.c_void_p(handle), 22, ctypes.byref(buffer), ctypes.sizeof(buffer)
        )
        if not ok:
            raise PlatformStorageError(PlatformErrorCode.UNAVAILABLE)
    except PlatformStorageError:
        raise
    except (ImportError, AttributeError, OSError, ValueError):
        raise PlatformStorageError(PlatformErrorCode.UNAVAILABLE) from None


def _destination_is_safe(path: Path) -> None:
    _check_absolute(path)
    try:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH)
    except PlatformStorageError:
        raise
    except OSError:
        raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH) from None


def atomic_promote(source: Path, destination: Path, *, expected_source: FileIdentity | None = None) -> None:
    """Atomically promote a validated object without re-opening source by name."""
    _check_absolute(source)
    _check_absolute(destination)
    if source.parent != destination.parent:
        raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH)
    _destination_is_safe(destination)
    fd = open_regular(source, os.O_RDWR, delete=True)
    temporary: Path | None = None
    try:
        current = _identity_from_fd(fd)
        if expected_source is not None and (
            (current.device, current.inode, current.size, current.mtime_ns)
            != (expected_source.device, expected_source.inode, expected_source.size, expected_source.mtime_ns)
            or (expected_source.digest and current.digest != expected_source.digest)
        ):
            raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH)
        opened = os.fstat(fd)
        if not _is_regular_stat(opened) or (opened.st_dev, opened.st_ino) != (current.device, current.inode):
            raise PlatformStorageError(PlatformErrorCode.UNSAFE_PATH)
        if os.name == "nt":
            _windows_replace_handle(fd, source, destination)
            temporary = None
            return
        temporary = destination.with_name(destination.name + ".promoting-" + str(os.getpid()) + "-" + str(threading.get_ident()))
        parent_fd = _posix_parent(destination)
        try:
            try:
                os.unlink(temporary.name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            if os.name == "posix" and hasattr(os, "link"):
                linkat = ctypes.CDLL(None, use_errno=True).linkat
                linkat.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
                linkat.restype = ctypes.c_int
                result = linkat(fd, b"", parent_fd, temporary.name.encode(), 0x1000)
                if result != 0:
                    raise OSError(ctypes.get_errno(), "linkat")
            else:
                raise PlatformStorageError(PlatformErrorCode.UNAVAILABLE)
            os.replace(temporary.name, destination.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            temporary = None
        finally:
            close_handle(parent_fd)
    except PlatformStorageError:
        raise
    except OSError:
        raise PlatformStorageError(PlatformErrorCode.IO_ERROR) from None
    finally:
        close_handle(fd)
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def safe_cleanup(path: Path) -> None:
    """Remove only a verified regular file; missing is already clean."""
    safe_unlink(path)


__all__ = [
    "DIRECTORY_FLAG", "FileIdentity", "NO_FOLLOW", "PlatformErrorCode", "PlatformStorageError",
    "atomic_promote", "close_handle", "coordinated", "ensure_private_directory", "file_identity",
    "fsync_handle", "handle_info", "handle_size", "is_regular_info", "is_symlink_info", "list_relative",
    "locked", "open_parent_dir", "open_relative", "open_regular", "paths_alias", "read_all", "read_bytes", "read_from",
    "rename_relative", "safe_cleanup", "safe_unlink", "set_mode", "stat_relative", "unlink_relative", "validate_directory",
    "validate_path", "write_all",
]
