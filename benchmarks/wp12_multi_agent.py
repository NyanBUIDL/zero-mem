"""WP-12 local multi-process writer benchmark."""
from __future__ import annotations

import multiprocessing
import tempfile
import time
from pathlib import Path

from tests.unit.test_wp12_multi_agent import _writer


def main() -> None:
    with tempfile.TemporaryDirectory() as root:
        ctx = multiprocessing.get_context("fork")
        start = time.perf_counter()
        workers = [ctx.Process(target=_writer, args=(root, index * 2500, 2500)) for index in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        elapsed = time.perf_counter() - start
        records = len((Path(root) / "events-v1.jsonl").read_text().splitlines())
        print({"writers": 4, "operations": records, "seconds": round(elapsed, 6), "all_exited_zero": all(w.exitcode == 0 for w in workers)})


if __name__ == "__main__":
    main()
