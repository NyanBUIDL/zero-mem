"""Importable (spawn-safe) worker functions for tests/unit/test_t17_review_findings.py."""
from __future__ import annotations

from pathlib import Path


def save_keys(path: str, worker: int, count: int, barrier, out) -> None:
    from zero_mem import learner

    try:
        target = Path(path)
        barrier.wait(60)
        for i in range(count):
            learner._save_state(target, [f"w{worker}#{i}"])
        out.put(("ok", worker))
    except BaseException as exc:  # noqa: BLE001
        out.put(("error", worker, f"{type(exc).__name__}: {exc}"))
