"""Append-only JSONL capture store for M1 Increment 3."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Mapping

from src.capture.validation import validate_envelope
from src.redaction import RedactionRejected
from .capture_boundary import AppendResult, CaptureRejected, CaptureStoreConfig


class JsonlCaptureStore:
    def __init__(self, config: CaptureStoreConfig) -> None:
        self.config = config
        self.path = config.path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(self.path.parent, 0o700)
        self._lock = threading.RLock()
        self._by_id: dict[str, dict[str, Any]] = {}
        self._by_hash: dict[str, dict[str, Any]] = {}
        self._next_sequence = 0
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self.path.touch(mode=0o600)
            if os.name != "nt":
                os.chmod(self.path, 0o600)
            return
        data = self.path.read_bytes()
        if data and not data.endswith(b"\n"):
            raise CaptureRejected("capture_rejected: partial_final_line")
        for line_number, line in enumerate(data.splitlines(), start=1):
            try:
                record = json.loads(line.decode("utf-8"))
                if not isinstance(record, dict):
                    raise ValueError
                validate_envelope(record)
            except Exception as exc:
                raise CaptureRejected(f"capture_rejected: malformed_historical_line:{line_number}") from None
            event_id = record["event_id"]
            content_hash = record["sanitized_content_hash"]
            self._by_id[event_id] = record
            self._by_hash[content_hash] = record
            self._next_sequence = max(self._next_sequence, int(record["sequence"]) + 1)

    @staticmethod
    def _serialize(event: Mapping[str, Any]) -> bytes:
        return (json.dumps(dict(event), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")

    def append(self, event: Mapping[str, Any]) -> AppendResult:
        with self._lock:
            try:
                validate_envelope(event)
            except Exception:
                raise CaptureRejected("capture_rejected: invalid_or_unsanitized_event") from None
            if event.get("sensitivity") == "secret" or event.get("retention") == "never_store":
                raise CaptureRejected("capture_rejected: never_store_policy")
            if not event.get("redaction_audit"):
                raise CaptureRejected("capture_rejected: missing_redaction_audit")
            event_id = str(event["event_id"])
            content_hash = str(event["sanitized_content_hash"])
            if event_id in self._by_id:
                old = self._by_id[event_id]
                return AppendResult("duplicate", event_id, int(old["sequence"]), content_hash, "event_id")
            if content_hash in self._by_hash:
                old = self._by_hash[content_hash]
                return AppendResult("duplicate", event_id, int(old["sequence"]), content_hash, "content_hash")
            record = dict(event)
            record["sequence"] = self._next_sequence
            blob = self._serialize(record)
            try:
                with self.path.open("ab") as stream:
                    stream.write(blob)
                    stream.flush()
                    os.fsync(stream.fileno())
            except Exception:
                raise CaptureRejected("capture_rejected: append_failed") from None
            self._by_id[event_id] = record
            self._by_hash[content_hash] = record
            self._next_sequence += 1
            return AppendResult("appended", event_id, int(record["sequence"]), content_hash)

    def contains_event_id(self, event_id: str) -> bool:
        return event_id in self._by_id

    def contains_content_hash(self, content_hash: str) -> bool:
        return content_hash in self._by_hash

    def inspect_record(self, event_id: str) -> dict[str, Any] | None:
        record = self._by_id.get(event_id)
        return dict(record) if record else None

    def close(self) -> None:
        return None

    def __enter__(self) -> "JsonlCaptureStore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


__all__ = ["JsonlCaptureStore", "CaptureStoreConfig", "CaptureRejected", "RedactionRejected"]
