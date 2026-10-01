"""Bounded retry for transient Windows file-sharing denials (DEF-090).

On Windows ``os.replace`` / ``open`` raise ``PermissionError`` (WinError 5
ERROR_ACCESS_DENIED, 32 ERROR_SHARING_VIOLATION, 33 ERROR_LOCK_VIOLATION) while
another process has the file open or is replacing it. Those are transient;
retry with a short increasing backoff (total < 1 s). Anything else
(ENOSPC, ENOENT, ...) is never retried or masked.
"""
from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")

_TRANSIENT_WINERRORS = frozenset({5, 32, 33})
_DELAYS_MS = (5, 10, 20, 40, 80, 80, 80, 80, 80)  # 10 attempts, 475 ms total


def _sleep(seconds: float) -> None:  # module-level so tests can patch it
    time.sleep(seconds)


def delays() -> tuple[float, ...]:
    return tuple(ms / 1000.0 for ms in _DELAYS_MS)


def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    return isinstance(exc, OSError) and getattr(exc, "winerror", None) in _TRANSIENT_WINERRORS


def retry_transient(op: Callable[[], T]) -> T:
    """Run ``op``; retry only transient sharing denials, re-raise the last one."""
    for delay in delays():
        try:
            return op()
        except OSError as exc:
            if not is_transient(exc):
                raise
        _sleep(delay)
    return op()
