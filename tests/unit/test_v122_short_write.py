from __future__ import annotations

from pathlib import Path

import pytest

from src.storage import platform as platform_storage
from src.storage.capture_boundary import CaptureStoreConfig
from src.storage.jsonl_capture import CaptureRejected, JsonlCaptureStore
from tests.unit.test_m1_capture_boundary import event


def test_jsonl_capture_retries_repeated_short_writes_and_preserves_bytes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = JsonlCaptureStore(CaptureStoreConfig(tmp_path))
    real_write = platform_storage.os.write
    calls = 0

    def short_write(fd: int, data: bytes) -> int:
        nonlocal calls
        calls += 1
        return real_write(fd, data[: max(1, min(3, len(data)))])

    monkeypatch.setattr(platform_storage.os, "write", short_write)
    result = store.append(event({"value": "short"}, event_id="short"))
    monkeypatch.undo()
    assert result.status == "appended"
    assert calls > 1
    line = store.path.read_bytes()
    assert line.endswith(b"\n")
    assert line == store.path.read_bytes()


def test_jsonl_capture_zero_progress_never_reports_append(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = JsonlCaptureStore(CaptureStoreConfig(tmp_path))
    monkeypatch.setattr(platform_storage.os, "write", lambda _fd, _data: 0)
    with pytest.raises(CaptureRejected, match="append_failed"):
        store.append(event({"value": "zero"}, event_id="zero"))
    monkeypatch.undo()
    assert not store.contains_event_id("zero")
    assert store.path.read_bytes() in (b"",)
