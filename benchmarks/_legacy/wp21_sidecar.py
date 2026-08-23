"""WP-21 local dispatcher benchmark."""
from __future__ import annotations

import time

from zero_mem import CoreConfig, LocalSidecar, PublicClient


def main() -> None:
    sidecar = LocalSidecar(PublicClient.open(CoreConfig(enabled=False)))
    sidecar.start()
    start = time.perf_counter()
    for _ in range(1000):
        sidecar.dispatch({"identity": "benchmark", "capability": "health"})
    elapsed = time.perf_counter() - start
    sidecar.stop()
    print({"requests": 1000, "seconds": round(elapsed, 6), "transport": "embedded-local"})


if __name__ == "__main__":
    main()
