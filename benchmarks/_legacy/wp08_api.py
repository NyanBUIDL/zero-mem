"""WP-08 public facade overhead benchmark."""
from __future__ import annotations

import time

from zero_mem import CoreConfig, PublicClient


class Writer:
    def append(self, event: object) -> None:
        return None


def main() -> None:
    client = PublicClient.open(CoreConfig(), writer=Writer(), consistency_policy="append")
    start = time.perf_counter()
    for index in range(10_000):
        client.observe_message({"i": index})
    elapsed = time.perf_counter() - start
    client.shutdown()
    print({"no_memory_observations": 10_000, "seconds": round(elapsed, 6)})


if __name__ == "__main__":
    main()
