"""Append-only JSONL capture store for M1 Increment 3."""
from __future__ import annotations

import json
import os
import threading
try:
    import fcntl
except ImportError:  # native Windows is outside the v1.1 support matrix
    fcntl = None  # type: ignore[assignment]
from pathlib import Path
from typing import Any, Mapping

from src.capture.validation import validate_envelope
from src.redaction import RedactionRejected
from .capture_boundary import AppendResult, CaptureRejected, CaptureStoreConfig


class JsonlCaptureStore:
    def __init__(self, config: CaptureStoreConfig) -> None:
        self.config = config
        self.path = config.path
        if fcntl is None:
            raise CaptureRejected("capture_rejected: process_lock_unavailable")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(self.path.parent, 0o700)
        self._lock = threading.RLock()
        self._process_lock_path = self.path.with_name(self.path.name + ".lock")
        self._process_lock = self._process_lock_path.open("a+b")
        if os.name != "nt":
            os.chmod(self._process_lock_path, 0o600)
        self._by_id: dict[str, dict[str, Any]] = {}
        self._by_hash: dict[str, dict[str, Any]] = {}
        self._next_sequence = 0
        self._loaded_size = 0
        with self._exclusive_process_lock():
            self._load()

    from contextlib import contextmanager

    @contextmanager
    def _exclusive_process_lock(self):
        fcntl.flock(self._process_lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(self._process_lock.fileno(), fcntl.LOCK_UN)

    def _load(self) -> None:
        self._by_id.clear()
        self._by_hash.clear()
        self._next_sequence = 0
        if not self.path.exists():
            self.path.touch(mode=0o600)
            if os.name != "nt":
                os.chmod(self.path, 0o600)
            self._loaded_size = 0
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
        self._loaded_size = len(data)

    def _refresh(self) -> None:
        """Load only records appended by another process since the last refresh."""
        size = self.path.stat().st_size
        if size < self._loaded_size:
            self._load()
            return
        if size == self._loaded_size:
            return
        with self.path.open("rb") as stream:
            stream.seek(self._loaded_size)
            data = stream.read()
        if data and not data.endswith(b"\n"):
            raise CaptureRejected("capture_rejected: partial_final_line")
        for line in data.splitlines():
            try:
                record = json.loads(line.decode("utf-8"))
                if not isinstance(record, dict):
                    raise ValueError
                validate_envelope(record)
            except Exception:
                raise CaptureRejected("capture_rejected: malformed_historical_line") from None
            self._by_id[record["event_id"]] = record
            self._by_hash[record["sanitized_content_hash"]] = record
            self._next_sequence = max(self._next_sequence, int(record["sequence"]) + 1)
        self._loaded_size = size

    @staticmethod
    def _serialize(event: Mapping[str, Any]) -> bytes:
        return (json.dumps(dict(event), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")

    def append(self, event: Mapping[str, Any]) -> AppendResult:
        with self._lock:
            with self._exclusive_process_lock():
                return self._append_locked(event)

    def _append_locked(self, event: Mapping[str, Any]) -> AppendResult:
        # Refresh under the inter-process lock so sequence and duplicate checks
        # observe commits made by sibling processes.
        self._refresh()
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
        self._loaded_size += len(blob)
        return AppendResult("appended", event_id, int(record["sequence"]), content_hash)

    def contains_event_id(self, event_id: str) -> bool:
        return event_id in self._by_id

    def contains_content_hash(self, content_hash: str) -> bool:
        return content_hash in self._by_hash

    def inspect_record(self, event_id: str) -> dict[str, Any] | None:
        record = self._by_id.get(event_id)
        return dict(record) if record else None

    def close(self) -> None:
        if not self._process_lock.closed:
            self._process_lock.close()
        return None

    def __enter__(self) -> "JsonlCaptureStore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


__all__ = ["JsonlCaptureStore", "CaptureStoreConfig", "CaptureRejected", "RedactionRejected"]
