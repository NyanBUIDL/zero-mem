"""First-run setup that survives several processes starting at the same moment.

``Layout.ensure()`` is idempotent but not safe to run concurrently on a data root nobody initialised: simultaneous
schema creation fails for most callers (``LayoutError: setup failed``). That is exactly what happens when a client
launches one MCP server per agent at once, so every long-lived entry point (``zero-mem serve``, the MCP memory tool
set) calls :func:`ensure_layout` instead: the setup runs under an exclusive cross-process lock on
``<data root>/.layout.lock`` (the lock file is created next to the data, in the private data directory), and a failed
attempt is retried a few times with a short jittered back-off, which also covers a sibling that is not holding the
lock (a concurrent ``zero-mem add`` on a fresh install).

Zero dependencies beyond the storage lock helper already used by the library; no network.
"""
from __future__ import annotations

import random
import time
from typing import Optional

from . import paths
from .memory_layout import Layout, LayoutError

LOCK_NAME = ".layout.lock"
LOCK_TIMEOUT = 60.0
ATTEMPTS = 4


def _ensure_locked(layout: Layout) -> None:
    from src.storage.coordination import locked

    try:
        paths.ensure_private_dir(layout.data_root, "data directory")  # the lock file lives in it
        with locked(layout.data_root / LOCK_NAME, mode="exclusive", timeout=LOCK_TIMEOUT):
            layout.ensure()
    except LayoutError:
        raise
    except Exception:  # noqa: BLE001 - sanitized, like Layout.ensure
        raise LayoutError("setup failed") from None


def ensure_layout(layout: Layout, *, attempts: int = ATTEMPTS) -> None:
    """Idempotently create private dirs, the canonical stream, the corpus root and the schema (race-safe)."""
    last: Optional[LayoutError] = None
    for attempt in range(max(1, attempts)):
        try:
            _ensure_locked(layout)
            return
        except LayoutError as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(0.05 * (2 ** attempt) + random.random() * 0.05)
    assert last is not None
    raise last


__all__ = ["ATTEMPTS", "LOCK_NAME", "ensure_layout"]
