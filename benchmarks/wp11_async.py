"""WP-11 bounded async facade benchmark."""
from __future__ import annotations

import asyncio
import time

from zero_mem import AsyncClient, CoreConfig


class Writer:
    def append(self, event: object) -> None:
        return None


async def run() -> None:
    client = AsyncClient.open(CoreConfig(), writer=Writer(), consistency_policy="append", queue_capacity=16)
    start = time.perf_counter()
    await asyncio.gather(*(client.observe_message({"i": i}) for i in range(1000)))
    elapsed = time.perf_counter() - start
    await client.aclose()
    print({"async_observations": 1000, "seconds": round(elapsed, 6)})


if __name__ == "__main__":
    asyncio.run(run())
