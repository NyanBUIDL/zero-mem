from __future__ import annotations

import sqlite3
from pathlib import Path

from zero_mem.recovery import FailureClass, diagnose


def test_diagnosis_classifies_partial_canonical_without_mutation(tmp_path: Path) -> None:
    canonical = tmp_path / "events.jsonl"
    derived = tmp_path / "memory.sqlite3"
    canonical.write_bytes(b'{"event_id":"e1"}\n{"event_id":"e2"')
    before = canonical.stat().st_mtime_ns
    result = diagnose(canonical_path=canonical, derived_path=derived)
    assert result.status is FailureClass.CANONICAL_MALFORMED
    assert canonical.stat().st_mtime_ns == before


def test_diagnosis_reports_derived_lag(tmp_path: Path) -> None:
    canonical = tmp_path / "events.jsonl"
    derived = tmp_path / "memory.sqlite3"
    canonical.write_text('{"event_id":"e1"}\n{"event_id":"e2"}\n')
    conn = sqlite3.connect(derived)
    conn.execute("CREATE TABLE memories (id TEXT)")
    conn.execute("INSERT INTO memories VALUES ('e1')")
    conn.commit()
    conn.close()
    result = diagnose(canonical_path=canonical, derived_path=derived)
    assert result.status is FailureClass.DERIVED_STALE
    assert result.canonical_records == 2
    assert result.derived_records == 1
