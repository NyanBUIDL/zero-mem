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
            results.append((res.status, res.reason if not res.detail else f"{res.reason}: {res.detail}", res.proposal_id))
        if same_text:
            res = mem.propose(same_text, "gotcha", scope="shared", evidence=[f"worker-{worker}"])
            results.append((res.status, res.reason if not res.detail else f"{res.reason}: {res.detail}", res.proposal_id))
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


def propose_slow(root: str, settings: str, profile: str, worker: int, count: int, delay: float, barrier, out) -> None:
    """T25: like propose_many but every canonical append sleeps ``delay`` inside the critical section (slow runner)."""
    import time

    from zero_mem import learning
    from zero_mem.memory import Memory

    real = learning.append_canonical_event

    def slow(stream, event):
        time.sleep(delay)
        return real(stream, event)

    learning.append_canonical_event = slow
    try:
        mem = Memory.open(profile, data_root=Path(root), settings_path=Path(settings))
        barrier.wait(60)
        results = []
        for i in range(count):
            res = mem.propose(f"slow worker {worker} proposal {i}", "rule", scope="shared")
            results.append((res.status, res.reason, res.proposal_id))
        mem.close()
        out.put(("ok", worker, results))
    except BaseException as exc:  # noqa: BLE001
        out.put(("error", worker, f"{type(exc).__name__}: {exc}"))


def hold_lock(path: str, seconds: float, ready, out) -> None:
    """T25: hold the exclusive platform lock on ``path`` for ``seconds`` (fault injection: a stalled lock holder)."""
    import time
    from pathlib import Path as _P

    from src.storage.platform import locked

    try:
        with locked(_P(path), mode="exclusive", timeout=5):
            ready.set()
            time.sleep(seconds)
        out.put(("ok", seconds))
    except BaseException as exc:  # noqa: BLE001
        ready.set()
        out.put(("error", f"{type(exc).__name__}: {exc}"))


def cold_start(root: str, settings: str, kind: str, worker: int, barrier, out) -> None:
    """T26: first-run race - ``root`` (and data/memory/traces) does not exist yet when the processes start."""
    from zero_mem.memory import Memory

    try:
        if kind == "propose":
            mem = Memory.open("claude-code", data_root=Path(root), settings_path=Path(settings))
            barrier.wait(60)
            res = mem.propose(f"cold start worker {worker} proposal", "rule", scope="shared")
            mem.close()
            out.put(("ok", worker, (res.status, res.reason if not res.detail else f"{res.reason}: {res.detail}")))
            return
        from zero_mem.learning import learning_lock
        from zero_mem.memory_layout import Layout
        from zero_mem.provisioning import append_canonical_event

        layout = Layout.resolve(Path(root))  # deliberately NOT ensure()d: the stream directory may not exist
        barrier.wait(60)
        with learning_lock(layout):
            pass
        append_canonical_event(layout.memory_stream.with_name(f"direct-{worker}.jsonl"), {"event_id": f"cold-{worker}", "event_type": "x"})
        out.put(("ok", worker, ("direct", "")))
    except BaseException as exc:  # noqa: BLE001
        out.put(("error", worker, f"{type(exc).__name__}: {exc}"))
