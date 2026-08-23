"""WP-04 real canonical append benchmark; derived state is not canonical."""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

from src.capture.adapter import normalize_event
from src.capture.event_types import EventType
from src.redaction import redact_payload
from src.storage.jsonl_capture import CaptureStoreConfig, JsonlCaptureStore


def _event(index: int) -> dict:
    safe = redact_payload({"value": index})
    return normalize_event(
        {"event_id": f"bench-{index}", "sanitized_content": safe.content,
         "redaction_audit": safe.audit.to_dict(), "sanitized_content_hash": safe.content_hash},
        sequence=index, event_type=EventType.TOOL_OBSERVATION, source="benchmark",
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = JsonlCaptureStore(CaptureStoreConfig(Path(directory)))
        start = time.perf_counter()
        for index in range(100):
            store.append(_event(index))
        elapsed = time.perf_counter() - start
        print({"appends": 100, "seconds": round(elapsed, 6), "bytes": store.path.stat().st_size})


if __name__ == "__main__":
    main()
