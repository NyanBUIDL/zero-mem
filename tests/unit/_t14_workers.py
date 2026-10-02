"""Importable (spawn-safe) worker functions for tests/unit/test_t14_concurrency.py."""
from __future__ import annotations

from pathlib import Path


def propose_many(root: str, settings: str, profile: str, worker: int, count: int, same_text: str, barrier, out) -> None:
    """``count`` distinct proposals of this worker plus the SAME text (collapses per profile)."""
    from zero_mem.memory import Memory

    try:
        mem = Memory.open(profile, data_root=Path(root), settings_path=Path(settings))
        barrier.wait(60)
        results = []
        for i in range(count):
            res = mem.propose(f"worker {worker} proposal {i} about topic {i % 3}", "rule", scope="shared")
            results.append((res.status, res.reason, res.proposal_id))
        if same_text:
            res = mem.propose(same_text, "gotcha", scope="shared", evidence=[f"worker-{worker}"])
            results.append((res.status, res.reason, res.proposal_id))
        mem.close()
        out.put(("ok", worker, results))
    except BaseException as exc:  # noqa: BLE001 - report every failure to the parent
        out.put(("error", worker, f"{type(exc).__name__}: {exc}"))


def review_while_proposing(root: str, settings: str, profile: str, barrier, out) -> None:
    """Owner approves everything pending while agents keep proposing."""
    from zero_mem.learning import Reviewer
    from zero_mem.memory_layout import Layout

    try:
        reviewer = Reviewer(Layout.resolve(Path(root)), operator="owner", settings_path=Path(settings))
        barrier.wait(60)
        approved = 0
        for _ in range(6):
            for row in reviewer.list("pending"):
                if reviewer.approve(row["id"]).status == "approved":
                    approved += 1
        out.put(("ok", "reviewer", approved))
    except BaseException as exc:  # noqa: BLE001
        out.put(("error", "reviewer", f"{type(exc).__name__}: {exc}"))
