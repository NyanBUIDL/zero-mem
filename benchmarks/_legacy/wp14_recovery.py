"""WP-14 read-only diagnosis overhead benchmark."""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

from zero_mem.recovery import diagnose


def main() -> None:
    with tempfile.TemporaryDirectory() as root:
        canonical = Path(root) / "events.jsonl"
        canonical.write_text("".join(f'{{"event_id":"e{i}"}}\n' for i in range(1000)))
        start = time.perf_counter()
        result = diagnose(canonical_path=canonical, derived_path=Path(root) / "missing.sqlite3")
        elapsed = time.perf_counter() - start
        print({"records": result.canonical_records, "status": result.status.value, "seconds": round(elapsed, 6)})


if __name__ == "__main__":
    main()
