"""WP-15 status snapshot overhead benchmark."""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

from zero_mem.status import collect_status


def main() -> None:
    with tempfile.TemporaryDirectory() as root:
        canonical = Path(root) / "events.jsonl"
        canonical.write_bytes(b"x" * 10_000_000)
        start = time.perf_counter()
        result = collect_status(canonical=canonical, derived=Path(root) / "missing.sqlite3")
        elapsed = time.perf_counter() - start
        print({"schema": result.schema_version, "canonical_bytes": result.canonical_bytes, "seconds": round(elapsed, 6)})


if __name__ == "__main__":
    main()
