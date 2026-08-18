"""WP-22 projection/rebuild smoke benchmark."""
from __future__ import annotations

import time

from src.m8.projection_store import ProjectionReport


def main() -> None:
    start = time.perf_counter()
    for _ in range(1000):
        ProjectionReport().to_dict()
    print({"projections": 1000, "seconds": round(time.perf_counter() - start, 6)})


if __name__ == "__main__":
    main()
