"""Read-only recovery diagnosis and stable failure classifications."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class FailureClass(str, Enum):
    CANONICAL_MISSING = "CANONICAL_MISSING"
    CANONICAL_MALFORMED = "CANONICAL_MALFORMED"
    DERIVED_MISSING = "DERIVED_MISSING"
    DERIVED_UNAVAILABLE = "DERIVED_UNAVAILABLE"
    DERIVED_STALE = "DERIVED_STALE"
    READY = "READY"


@dataclass(frozen=True)
class RecoveryDiagnosis:
    status: FailureClass
    canonical_records: int
    derived_records: int | None
    canonical_bytes: int
    message: str


def diagnose(*, canonical_path: Path, derived_path: Path) -> RecoveryDiagnosis:
    """Inspect canonical/derived state without modifying files."""
    if not canonical_path.is_file() or canonical_path.is_symlink():
        return RecoveryDiagnosis(FailureClass.CANONICAL_MISSING, 0, None, 0, "canonical stream missing")
    try:
        raw = canonical_path.read_bytes()
        if raw and not raw.endswith(b"\n"):
            return RecoveryDiagnosis(FailureClass.CANONICAL_MALFORMED, 0, None, len(raw), "canonical stream has partial final record")
        records = 0
        for line in raw.splitlines():
            value: Any = json.loads(line.decode("utf-8"))
            if not isinstance(value, dict) or not value.get("event_id"):
                raise ValueError
            records += 1
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return RecoveryDiagnosis(FailureClass.CANONICAL_MALFORMED, 0, None, 0, "canonical stream is malformed")
    if not derived_path.is_file() or derived_path.is_symlink():
        return RecoveryDiagnosis(FailureClass.DERIVED_MISSING, records, None, len(raw), "derived store missing; rebuild from canonical")
    try:
        conn = sqlite3.connect(f"file:{derived_path.as_posix()}?mode=ro", uri=True)
        row = conn.execute("SELECT COUNT(*) FROM memories").fetchone()
        derived_records = int(row[0]) if row else 0
        conn.close()
    except sqlite3.Error:
        return RecoveryDiagnosis(FailureClass.DERIVED_UNAVAILABLE, records, None, len(raw), "derived store unavailable; rebuild from canonical")
    if derived_records < records:
        return RecoveryDiagnosis(FailureClass.DERIVED_STALE, records, derived_records, len(raw), "derived store lags canonical stream")
    return RecoveryDiagnosis(FailureClass.READY, records, derived_records, len(raw), "canonical and derived state are available")


__all__ = ["FailureClass", "RecoveryDiagnosis", "diagnose"]
