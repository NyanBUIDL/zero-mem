"""M6.2 runtime — TRUE READ-ONLY store + grant-connection access.

Holds only the configured derived SQLite path (set at startup, never hard-coded
per repo/user). Opens connections strictly read-only. No writes, no migrations,
no JSONL, no grant administration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import sqlite3


def open_readonly_store(store_path: Path):
    """Open the derived store as a TRUE READ-ONLY ReadonlyStore (mode=ro + query_only)."""
    from src.retrieval.db import open_readonly
    return open_readonly(store_path)


def open_grant_conn(store_path: Path) -> sqlite3.Connection:
    """Open a separate STRICTLY read-only connection for zm_access_grants reads."""
    uri = f"file:{store_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
    except sqlite3.OperationalError:
        pass  # query_only may be unsupported on some builds; mode=ro still blocks writes
    return conn


class M6Runtime:
    def __init__(self, store_path: Path) -> None:
        self._store_path = Path(store_path)

    @property
    def store_path(self) -> Path:
        return self._store_path

    def open_store(self):
        return open_readonly_store(self._store_path)

    def open_grants(self) -> sqlite3.Connection:
        return open_grant_conn(self._store_path)


# Module-level default runtime (configured at startup via m6.configure).
_default_runtime: Optional[M6Runtime] = None


def configure(store_path: Path) -> M6Runtime:
    global _default_runtime
    _default_runtime = M6Runtime(store_path)
    return _default_runtime


def get_runtime() -> M6Runtime:
    if _default_runtime is None:
        raise RuntimeError("M6 runtime not configured; call m6.configure(store_path)")
    return _default_runtime
