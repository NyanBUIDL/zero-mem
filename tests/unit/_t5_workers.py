"""Importable (spawn-safe) worker functions for tests/unit/test_t5_memory_concurrency.py."""
from __future__ import annotations

from pathlib import Path


def add_many(root: str, profile: str, worker: int, count: int, shared_text: str, barrier, out) -> None:
    """Each process: ``count`` private facts of its own plus the SAME shared-text fact (one logical source)."""
    from zero_mem.memory import Memory

    try:
        mem = Memory.open(profile, data_root=Path(root))
        barrier.wait(60)
        statuses = []
        for i in range(count):
            statuses.append(mem.add(f"worker {worker} fact {i} about topic {i % 4}").status)
        statuses.append(mem.add(shared_text).status)
        mem.close()
        out.put(("ok", worker, statuses))
    except BaseException as exc:  # noqa: BLE001 - report every failure to the parent
        out.put(("error", worker, f"{type(exc).__name__}: {exc}"))


def forget_while_adding(root: str, profile: str, source_id: str, barrier, out) -> None:
    from zero_mem.memory import Memory

    try:
        mem = Memory.open(profile, data_root=Path(root))
        barrier.wait(60)
        res = mem.forget(source_id)
        mem.add("added concurrently with a forget")
        mem.close()
        out.put(("ok", res.status))
    except BaseException as exc:  # noqa: BLE001
        out.put(("error", f"{type(exc).__name__}: {exc}"))


def read_loop(root: str, profile: str, query: str, seconds: float, out) -> None:
    import time

    from zero_mem.memory import Memory

    try:
        mem = Memory.open(profile, data_root=Path(root))
        deadline = time.time() + seconds
        reads = errors = 0
        while time.time() < deadline:
            res = mem.recall(query, limit=5)
            reads += 1
            if res.status not in ("ok", "empty"):
                errors += 1
        mem.close()
        out.put(("ok", reads, errors))
    except BaseException as exc:  # noqa: BLE001
        out.put(("error", f"{type(exc).__name__}: {exc}"))
