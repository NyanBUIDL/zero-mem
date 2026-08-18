"""WP-06 context/evidence selection overhead benchmark."""
from __future__ import annotations

import time

from src.integration.m7.injection_adapter import InjectionAdapter
from src.integration.zero_mem_runtime import configure


def main() -> None:
    configure(enabled=True)
    adapter = InjectionAdapter(requesting_profile_id="bench")
    start = time.perf_counter()
    for _ in range(10_000):
        adapter.process(user_message="hello")
    elapsed = time.perf_counter() - start
    print({"no_memory_context_calls": 10_000, "seconds": round(elapsed, 6)})


if __name__ == "__main__":
    main()
