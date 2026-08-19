from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from zero_mem.core import AppendReceipt, CoreConfig, ZeroMemClient
from zero_mem.recovery import FailureClass, diagnose


class ReceiptWriter:
    def __init__(self, receipt):
        self.receipt = receipt

    def append(self, event):
        return self.receipt


def test_capture_rejects_non_durable_append_receipt() -> None:
    writer = ReceiptWriter(
        AppendReceipt(
            status="failed",
            event_id="e1",
            sequence=None,
            canonical_durable=False,
            reason_code="append_failed",
        )
    )
    client = ZeroMemClient(CoreConfig(), writer=writer, consistency_policy="canonical")
    result = client.capture({"event_id": "e1"})
    assert result.status != "CAPTURED"
    assert result.reason_code == "append_failed"


def test_capture_rejects_malformed_durable_receipt() -> None:
    malformed = type("MalformedReceipt", (), {"status": "appended", "event_id": "e1", "sequence": 0})()
    writer = ReceiptWriter(malformed)
    client = ZeroMemClient(CoreConfig(), writer=writer, consistency_policy="canonical")
    result = client.capture({"event_id": "e1"})
    assert result.status != "CAPTURED"
    assert result.reason_code == "CANONICAL_APPEND_RECEIPT_MISSING"


def test_capture_rejects_forged_durable_append_receipt() -> None:
    writer = ReceiptWriter(AppendReceipt("appended", None, None, True, reason_code="secret-token"))
    client = ZeroMemClient(CoreConfig(), writer=writer, consistency_policy="canonical")
    result = client.capture({"event_id": "e1"})
    assert result.status != "CAPTURED"
    assert result.reason_code == "INVALID_CANONICAL_APPEND_RECEIPT"


def test_capture_sanitizes_untrusted_reason_code() -> None:
    writer = ReceiptWriter(AppendReceipt("failed", None, None, False, reason_code="secret-token"))
    client = ZeroMemClient(CoreConfig(), writer=writer, consistency_policy="canonical")
    result = client.capture({"event_id": "e1"})
    assert result.reason_code == "CANONICAL_APPEND_REJECTED"


def test_capture_accepts_only_durable_append_receipt() -> None:
    writer = ReceiptWriter(
        AppendReceipt(
            status="appended",
            event_id="e1",
            sequence=0,
            canonical_durable=True,
        )
    )
    client = ZeroMemClient(CoreConfig(), writer=writer, consistency_policy="canonical")
    assert client.capture({"event_id": "e1"}).status == "CAPTURED"


def test_recovery_uses_real_derived_schema_and_checkpoint(tmp_path: Path) -> None:
    canonical = tmp_path / "events.jsonl"
    canonical.write_text(
        json.dumps({"event_id": "e1", "sequence": 0}) + "\n"
        + json.dumps({"event_id": "e2", "sequence": 1}) + "\n",
        encoding="utf-8",
    )
    db = tmp_path / "derived store.sqlite3"
    store = SQLiteStore(SQLiteStoreConfig(path=db))
    store.ensure_schema()
    store._conn.execute(
        "INSERT INTO zm_ingest_checkpoint "
        "(jsonl_path,last_line_number,last_event_id,last_sequence,consumed_prefix_hash,updated_at) "
        "VALUES (?,?,?,?,?,?)",
        (canonical.name, 2, "e2", 1, hashlib.sha256(canonical.read_bytes()).hexdigest(), "now"),
    )
    store._conn.commit()
    store.close()

    result = diagnose(canonical_path=canonical, derived_path=db, source_id=canonical.name)
    assert result.status is FailureClass.DERIVED_STALE
    assert result.canonical_records == 2
    assert result.derived_records == 0


def test_recovery_classifies_corrupt_checkpoint_without_raising(tmp_path: Path) -> None:
    canonical = tmp_path / "events.jsonl"
    canonical.write_text(json.dumps({"event_id": "e1", "sequence": 0}) + "\n")
    db = tmp_path / "corrupt.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE zm_meta (event_id TEXT, sequence INTEGER)")
    conn.execute("CREATE TABLE zm_migrations (version INTEGER, applied_at TEXT, note TEXT)")
    conn.execute("CREATE TABLE zm_ingest_checkpoint (jsonl_path TEXT, last_line_number TEXT, last_event_id TEXT, last_sequence TEXT, consumed_prefix_hash TEXT, updated_at TEXT)")
    conn.execute("INSERT INTO zm_meta VALUES ('e1', 0)")
    conn.execute("INSERT INTO zm_ingest_checkpoint VALUES ('events.jsonl', 'bad', 'e1', 'bad', 'bad', 'now')")
    conn.commit()
    conn.close()
    result = diagnose(canonical_path=canonical, derived_path=db, source_id=canonical.name)
    assert result.status is FailureClass.DERIVED_CORRUPT


def test_recovery_does_not_query_obsolete_memories_table(tmp_path: Path) -> None:
    canonical = tmp_path / "events.jsonl"
    canonical.write_text(json.dumps({"event_id": "e1", "sequence": 0}) + "\n")
    db = tmp_path / "derived.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE zm_meta (event_id TEXT, sequence INTEGER)")
    conn.execute("CREATE TABLE zm_migrations (version INTEGER, applied_at TEXT, note TEXT)")
    conn.execute("CREATE TABLE zm_ingest_checkpoint (jsonl_path TEXT, last_line_number INTEGER, last_event_id TEXT, last_sequence INTEGER, consumed_prefix_hash TEXT, updated_at TEXT)")
    conn.execute("INSERT INTO zm_meta VALUES ('e1', 0)")
    conn.execute("INSERT INTO zm_ingest_checkpoint VALUES ('events.jsonl', 1, 'e1', 0, ?, 'now')", (hashlib.sha256(canonical.read_bytes()).hexdigest(),))
    conn.commit()
    conn.close()

    before = db.read_bytes()
    result = diagnose(canonical_path=canonical, derived_path=db, source_id=canonical.name)
    assert result.status is FailureClass.READY
    assert db.read_bytes() == before


def test_recovery_rejects_non_string_event_id(tmp_path: Path) -> None:
    canonical = tmp_path / "events.jsonl"
    canonical.write_text(json.dumps({"event_id": 7, "sequence": 0}) + "\n")
    result = diagnose(canonical_path=canonical, derived_path=tmp_path / "missing.sqlite3", source_id=canonical.name)
    assert result.status is FailureClass.CANONICAL_MALFORMED


def test_recovery_rejects_equal_count_wrong_derived_identity(tmp_path: Path) -> None:
    canonical = tmp_path / "events.jsonl"
    canonical.write_text(
        json.dumps({"event_id": "e1", "sequence": 0}) + "\n"
        + json.dumps({"event_id": "e2", "sequence": 1}) + "\n"
    )
    db = tmp_path / "derived.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE zm_meta (event_id TEXT, sequence INTEGER)")
    conn.execute("CREATE TABLE zm_migrations (version INTEGER, applied_at TEXT, note TEXT)")
    conn.execute("CREATE TABLE zm_ingest_checkpoint (jsonl_path TEXT, last_line_number INTEGER, last_event_id TEXT, last_sequence INTEGER, consumed_prefix_hash TEXT, updated_at TEXT)")
    conn.execute("INSERT INTO zm_meta VALUES ('wrong', 0)")
    conn.execute("INSERT INTO zm_meta VALUES ('other', 1)")
    conn.execute(
        "INSERT INTO zm_ingest_checkpoint "
        "(jsonl_path,last_line_number,last_event_id,last_sequence,consumed_prefix_hash,updated_at) "
        "VALUES (?,?,?,?,?,?)",
        (canonical.name, 2, "e2", 1, hashlib.sha256(canonical.read_bytes()).hexdigest(), "now"),
    )
    conn.commit()
    conn.close()
    result = diagnose(canonical_path=canonical, derived_path=db, source_id=canonical.name)
    assert result.status is FailureClass.DERIVED_CORRUPT
