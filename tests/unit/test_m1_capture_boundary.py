from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.capture.adapter import normalize_event
from src.capture.event_types import EventType
from src.redaction import redact_payload
from src.storage.jsonl_capture import CaptureStoreConfig, JsonlCaptureStore, CaptureRejected


def event(content: dict, *, event_id: str = "e1", sequence: int = 0) -> dict:
    safe = redact_payload(content)
    return normalize_event(
        {"event_id": event_id, "sanitized_content": safe.content,
         "redaction_audit": safe.audit.to_dict(), "sanitized_content_hash": safe.content_hash},
        sequence=sequence, event_type=EventType.TOOL_OBSERVATION, source="test",
    )


def test_valid_append_and_one_record_per_line(tmp_path: Path) -> None:
    store = JsonlCaptureStore(CaptureStoreConfig(tmp_path))
    result = store.append(event({"value": "ok"}))
    assert result.status == "appended"
    lines = store.path.read_text().splitlines(keepends=True)
    assert len(lines) == 1 and lines[0].endswith("\n")
    assert json.loads(lines[0])["event_id"] == "e1"


def test_event_id_and_hash_duplicates_do_not_rewrite(tmp_path: Path) -> None:
    store = JsonlCaptureStore(CaptureStoreConfig(tmp_path))
    first = store.append(event({"value": "one"}, event_id="e1"))
    before = store.path.read_bytes()
    duplicate_id = store.append(event({"value": "two"}, event_id="e1"))
    duplicate_hash = store.append(event({"value": "one"}, event_id="e2"))
    assert first.status == "appended"
    assert duplicate_id.status == duplicate_hash.status == "duplicate"
    assert store.path.read_bytes() == before
    assert store.contains_event_id("e1")
    assert store.contains_content_hash(first.content_hash)


def test_sequence_recovery_and_timestamp_preservation(tmp_path: Path) -> None:
    cfg = CaptureStoreConfig(tmp_path)
    first = JsonlCaptureStore(cfg)
    first.append(event({"value": 1}, event_id="e1"))
    first.close()
    second = JsonlCaptureStore(cfg)
    result = second.append(event({"value": 2}, event_id="e2"))
    records = [json.loads(line) for line in second.path.read_text().splitlines()]
    assert result.sequence == 1
    assert [record["sequence"] for record in records] == [0, 1]
    assert records[0]["created_at"].endswith("Z")


def test_deterministic_serialization(tmp_path: Path) -> None:
    a = JsonlCaptureStore(CaptureStoreConfig(tmp_path / "a"))
    b = JsonlCaptureStore(CaptureStoreConfig(tmp_path / "b"))
    assert a.append(event({"b": 2, "a": 1}, event_id="x")).content_hash == b.append(event({"a": 1, "b": 2}, event_id="x")).content_hash


def test_partial_final_line_blocks_append_without_deletion(tmp_path: Path) -> None:
    cfg = CaptureStoreConfig(tmp_path)
    store = JsonlCaptureStore(cfg)
    store.append(event({"value": "ok"}))
    with store.path.open("ab") as fh:
        fh.write(b'{"partial": true}')
    store.close()
    with pytest.raises(CaptureRejected, match="partial"):
        JsonlCaptureStore(cfg)
    assert b'{"partial": true}' in store.path.read_bytes()


def test_malformed_historical_line_blocks_append(tmp_path: Path) -> None:
    cfg = CaptureStoreConfig(tmp_path)
    cfg.path.parent.mkdir(parents=True, exist_ok=True)
    cfg.path.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(CaptureRejected, match="malformed"):
        JsonlCaptureStore(cfg)


def test_restrictive_permissions_and_explicit_path(tmp_path: Path) -> None:
    store = JsonlCaptureStore(CaptureStoreConfig(tmp_path / "configured"))
    store.append(event({"value": "ok"}))
    assert store.path.parent == tmp_path / "configured"
    if os.name != "nt":
        assert store.path.stat().st_mode & 0o777 == 0o600
        assert store.path.parent.stat().st_mode & 0o777 == 0o700


def test_redaction_before_persistence_and_secret_absence(tmp_path: Path) -> None:
    store = JsonlCaptureStore(CaptureStoreConfig(tmp_path))
    secret = "SYNTHETIC_CAPTURE_SECRET"
    safe = redact_payload({"api_key": secret})
    record = event({"api_key": secret}, event_id="safe")
    store.append(record)
    assert secret not in store.path.read_text()
    with pytest.raises(CaptureRejected):
        store.append(normalize_event({"sanitized_content": {"api_key": secret}}, sequence=0, event_type=EventType.TOOL_OBSERVATION, source="test"))


def test_inspect_record_and_close(tmp_path: Path) -> None:
    store = JsonlCaptureStore(CaptureStoreConfig(tmp_path))
    store.append(event({"value": "ok"}))
    inspected = store.inspect_record("e1")
    assert inspected is not None and inspected["event_id"] == "e1"
    store.close()


def test_no_future_components_are_required(tmp_path: Path) -> None:
    store = JsonlCaptureStore(CaptureStoreConfig(tmp_path))
    assert not hasattr(store, "retry")
    assert not hasattr(store, "search")
    assert not hasattr(store, "inject")
