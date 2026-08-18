"""Versioned, content-free operational status snapshot."""
from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .paths import derived_db, memory_stream

STATUS_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class StatusSnapshot:
    schema_version: int
    readiness: str
    canonical_bytes: int
    canonical_present: bool
    derived_present: bool
    fts5_available: bool
    last_error_code: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fts5_available() -> bool:
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE _zm_status_fts USING fts5(content)")
        conn.execute("DROP TABLE _zm_status_fts")
        conn.close()
        return True
    except sqlite3.Error:
        return False


def collect_status(*, canonical: Path | None = None, derived: Path | None = None) -> StatusSnapshot:
    canonical_path = canonical or memory_stream()
    derived_path = derived or derived_db()
    canonical_present = canonical_path.is_file() and not canonical_path.is_symlink()
    derived_present = derived_path.is_file() and not derived_path.is_symlink()
    fts5 = _fts5_available()
    error: str | None = None
    if not canonical_present:
        error = "CANONICAL_MISSING"
    elif not derived_present:
        error = "DERIVED_MISSING"
    elif not fts5:
        error = "FTS5_UNAVAILABLE"
    readiness = "READY" if error is None else "NOT_READY"
    return StatusSnapshot(STATUS_SCHEMA_VERSION, readiness, canonical_path.stat().st_size if canonical_present else 0, canonical_present, derived_present, fts5, error)


__all__ = ["STATUS_SCHEMA_VERSION", "StatusSnapshot", "collect_status"]
