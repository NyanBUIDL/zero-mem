"""WP-13 effective-configuration load benchmark."""
from __future__ import annotations

import time

from zero_mem.config import load_effective_config


def main() -> None:
    start = time.perf_counter()
    for _ in range(1000):
        load_effective_config()
    print({"loads": 1000, "seconds": round(time.perf_counter() - start, 6)})


if __name__ == "__main__":
    main()
