from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

from src.capture.adapter import normalize_event
from src.capture.event_types import EventType
from src.redaction import redact_payload
from src.storage.jsonl_capture import CaptureStoreConfig, JsonlCaptureStore
from src.integration.zero_mem_runtime import new_runtime


def _event(index: int) -> dict:
    safe = redact_payload({"value": index})
    return normalize_event(
        {"event_id": f"proc-{index}", "sanitized_content": safe.content,
         "redaction_audit": safe.audit.to_dict(), "sanitized_content_hash": safe.content_hash},
        sequence=index, event_type=EventType.TOOL_OBSERVATION, source="wp12",
    )


def _writer(root: str, start: int, count: int = 50) -> None:
    store = JsonlCaptureStore(CaptureStoreConfig(Path(root)))
    for index in range(start, start + count):
        store.append(_event(index))
    store.close()


def test_two_processes_share_canonical_writer_without_loss(tmp_path: Path) -> None:
    # R124-07 / DEF-040: use the portable clean-interpreter path. Forking a
    # multi-threaded pytest process is unsafe on modern macOS and can inherit
    # stale lock/thread state into the child.
    ctx = multiprocessing.get_context("spawn")
    # Runtime ownership initializes the canonical root before worker processes
    # contend on it. Keep first-time lock-file creation out of the contention
    # probe so this test measures the supported shared-writer contract itself.
    bootstrap = JsonlCaptureStore(CaptureStoreConfig(tmp_path))
    bootstrap.close()
    processes = [ctx.Process(target=_writer, args=(str(tmp_path), start)) for start in (0, 50)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(10)
        assert process.exitcode == 0
    records = [json.loads(line) for line in (tmp_path / "events-v1.jsonl").read_text().splitlines()]
    assert len(records) == 100
    assert len({record["event_id"] for record in records}) == 100
    assert sorted(record["sequence"] for record in records) == list(range(100))


def test_second_runtime_does_not_replace_first_configuration(tmp_path: Path) -> None:
    first = JsonlCaptureStore(CaptureStoreConfig(tmp_path / "first"))
    second = JsonlCaptureStore(CaptureStoreConfig(tmp_path / "second"))
    first.append(_event(1))
    second.append(_event(2))
    assert first.path.parent != second.path.parent
    assert first.contains_event_id("proc-1")
    assert not first.contains_event_id("proc-2")
    first.close()
    second.close()


def test_explicit_runtime_handles_are_isolated_and_immutable() -> None:
    first = new_runtime(enabled=True)
    second = new_runtime(enabled=False)
    assert first.is_enabled() is True
    assert second.is_enabled() is False
    assert first != second
