"""Small WP-02 facade overhead benchmark; no product state is mutated."""
from __future__ import annotations

import time

from zero_mem.core import CoreConfig, ZeroMemClient


def main() -> None:
    client = ZeroMemClient(CoreConfig())
    start = time.perf_counter()
    for _ in range(10_000):
        client.capture({"kind": "noop"})
    elapsed = time.perf_counter() - start
    print({"calls": 10_000, "seconds": round(elapsed, 6), "status": "CAPABILITY_UNAVAILABLE"})


if __name__ == "__main__":
    main()
