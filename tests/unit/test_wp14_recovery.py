from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from zero_mem.recovery import FailureClass, diagnose


def test_diagnosis_classifies_partial_canonical_without_mutation(tmp_path: Path) -> None:
    canonical = tmp_path / "events.jsonl"
    derived = tmp_path / "memory.sqlite3"
    canonical.write_bytes(b'{"event_id":"e1"}\n{"event_id":"e2"')
    before = canonical.stat().st_mtime_ns
    result = diagnose(canonical_path=canonical, derived_path=derived, source_id=canonical.name)
    assert result.status is FailureClass.CANONICAL_MALFORMED
    assert canonical.stat().st_mtime_ns == before


def test_diagnosis_reports_derived_lag(tmp_path: Path) -> None:
    canonical = tmp_path / "events.jsonl"
    derived = tmp_path / "memory.sqlite3"
    canonical.write_text('{"event_id":"e1"}\n{"event_id":"e2"}\n')
    conn = sqlite3.connect(derived)
    conn.execute("CREATE TABLE zm_meta (event_id TEXT, sequence INTEGER)")
    conn.execute("CREATE TABLE zm_migrations (version INTEGER, applied_at TEXT, note TEXT)")
    conn.execute("CREATE TABLE zm_ingest_checkpoint (jsonl_path TEXT, last_line_number INTEGER, last_event_id TEXT, last_sequence INTEGER, consumed_prefix_hash TEXT, updated_at TEXT)")
    conn.execute("INSERT INTO zm_meta VALUES ('e1', 0)")
    prefix = canonical.read_bytes().splitlines(keepends=True)[0]
    conn.execute("INSERT INTO zm_ingest_checkpoint VALUES ('events.jsonl', 1, 'e1', 0, ?, 'now')", (hashlib.sha256(prefix).hexdigest(),))
    conn.commit()
    conn.close()
    result = diagnose(canonical_path=canonical, derived_path=derived, source_id=canonical.name)
    assert result.status is FailureClass.DERIVED_STALE
    assert result.canonical_records == 2
    assert result.derived_records == 1
