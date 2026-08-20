"""Append-only JSONL capture store for M1 Increment 3."""
from __future__ import annotations

import json
import os
import stat
import threading
from pathlib import Path
from typing import Any, Mapping

from src.capture.validation import validate_envelope
from src.redaction import RedactionRejected
from .capture_boundary import AppendResult, CaptureRejected, CaptureStoreConfig
from .coordination import locked
from .platform import PlatformErrorCode, PlatformStorageError, ensure_private_directory, open_regular


class JsonlCaptureStore:
    def __init__(self, config: CaptureStoreConfig) -> None:
        self.config = config
        self.path = config.path
        try:
            ensure_private_directory(self.path.parent)
        except PlatformStorageError:
            raise CaptureRejected("capture_rejected: unsafe_canonical_path") from None
        # Establish the complete ancestor chain through descriptor-relative
        # no-follow traversal before retaining the store.
        if os.name != "nt":
            os.chmod(self.path.parent, 0o700)
        self._lock = threading.RLock()
        self._process_lock_path = self.path.with_name(self.path.name + ".lock")
        try:
            lock_fd = open_regular(self._process_lock_path, os.O_RDWR, create=True)
        except PlatformStorageError as exc:
            raise CaptureRejected("capture_rejected: process_lock_unavailable") from None
        self._process_lock = os.fdopen(lock_fd, "a+b")
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
        with locked(self._process_lock_path, mode="exclusive", timeout=5.0):
            yield

    def _load(self) -> None:
        self._by_id.clear()
        self._by_hash.clear()
        self._next_sequence = 0
        fd = self._open_data(os.O_RDONLY)
        if fd is None:
            self._loaded_size = 0
            return
        try:
            data = self._read_fd(fd)
        finally:
            os.close(fd)
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
        fd = self._open_data(os.O_RDONLY)
        if fd is None:
            size = 0
        else:
            try:
                size = os.fstat(fd).st_size
            finally:
                os.close(fd)
        if size < self._loaded_size:
            self._load()
            return
        if size == self._loaded_size:
            return
        fd = self._open_data(os.O_RDONLY)
        if fd is None:
            raise CaptureRejected("capture_rejected: canonical_disappeared")
        try:
            os.lseek(fd, self._loaded_size, os.SEEK_SET)
            data = self._read_fd(fd)
        finally:
            os.close(fd)
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

    def _open_data(self, flags: int) -> int | None:
        try:
            return open_regular(self.path, flags, create=bool(flags & (os.O_WRONLY | os.O_RDWR)))
        except PlatformStorageError as exc:
            if exc.code is PlatformErrorCode.NOT_FOUND:
                return None
            raise CaptureRejected("capture_rejected: unsafe_canonical_path") from None

    @staticmethod
    def _read_fd(fd: int) -> bytes:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise CaptureRejected("capture_rejected: canonical_not_regular")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)

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
            fd = self._open_data(os.O_WRONLY | os.O_APPEND)
            if fd is None:
                raise OSError("canonical_missing")
            try:
                os.write(fd, blob)
                os.fsync(fd)
            finally:
                os.close(fd)
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
