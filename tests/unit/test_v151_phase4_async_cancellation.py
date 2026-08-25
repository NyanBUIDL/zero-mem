"""V1.5.1 Phase 4 / DEF-026 — async deferred-cancellation contract.

RED-first tests for the AsyncClient timeout path. The semantic contract under
test: a caller that receives ``AsyncTimeoutError`` must not leave an unbounded
number of abandoned operations queued in the executor's internal work queue
(work that will still execute and still append to canonical storage after the
caller was told the operation timed out).

Per the Phase 4 plan, real in-worker cancellation is NOT authorized (no proven
per-request SQLite connection ownership). The minimal compliant behavior is a
bounded drain window: when the worker frees up, abandoned queued operations are
cancelled before they can start, so accumulation is bounded by what the single
worker can pick up per unit of progress, and post-deadline side effects stop.

Sync sidecar parity controls (already covered by test_wp30_sidecar.py) pin the
admission/close invariants this file relies on.
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from zero_mem import (
    AppendReceipt,
    AsyncClient,
    AsyncTimeoutError,
    CoreConfig,
)


class SlowWriter:
    """Writer slow enough to keep the single worker busy."""

    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.events = []
        self.closed = 0

    def append(self, event: object) -> AppendReceipt:
        time.sleep(self.delay)
        self.events.append(event)
        return AppendReceipt("appended", f"event-{len(self.events)}", len(self.events) - 1, True)

    def close(self) -> None:
        self.closed += 1


def _executor_queue_size(client: AsyncClient) -> int:
    queue = client._executor._work_queue
    qsize = getattr(queue, "qsize", None)
    if qsize is None:
        # SimpleQueue fallback: introspection only, never mutates.
        with getattr(queue, "_lock", threading.Lock()):
            return len(getattr(queue, "_queue", []))
    return qsize()


def test_def026_timeout_leaves_bounded_queued_work() -> None:
    """100 timed-out calls must not accumulate ~100 abandoned queued items."""

    async def scenario() -> None:
        client = AsyncClient.open(
            CoreConfig(),
            writer=SlowWriter(0.05),
            consistency_policy="append",
        )
        try:
            # Occupy the single worker.
            first = asyncio.ensure_future(client.observe_message({"n": 0}))
            await asyncio.sleep(0)

            statuses: dict[str, int] = {}
            for i in range(100):
                try:
                    await client.observe_message({"n": i + 1}, deadline=0.003)
                    statuses["ok"] = statuses.get("ok", 0) + 1
                except AsyncTimeoutError:
                    statuses["timeout"] = statuses.get("timeout", 0) + 1

            # Give done-callbacks/drain logic one scheduling beat.
            await asyncio.sleep(0.05)

            assert statuses["timeout"] >= 90  # probe sanity, mirrors B1 evidence
            queued = _executor_queue_size(client)
            # DEF-026 acceptance: bounded residual work, not one item per timeout.
            assert queued <= 16, (
                f"deferred cancellation accumulates unbounded work: {queued} items "
                "left queued after 100 timeouts"
            )
            await first
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_def026_abandoned_work_is_cancelled_before_start_when_worker_frees() -> None:
    """After the busy period ends, queued abandoned ops must be cancelled,
    not executed against canonical storage."""

    async def scenario() -> None:
        writer = SlowWriter(0.03)
        client = AsyncClient.open(CoreConfig(), writer=writer, consistency_policy="append")
        try:
            occupy = asyncio.ensure_future(client.session_start("occupy"))
            await asyncio.sleep(0)

            timed_out = 0
            for i in range(20):
                try:
                    await client.observe_message({"late": i}, deadline=0.002)
                except AsyncTimeoutError:
                    timed_out += 1

            # Let everything the executor already picked up finish, then settle.
            await asyncio.sleep(1.5)
            await occupy

            events_after = len(writer.events)
            # The occupy call plus whatever started before cancellation; anything
            # materially larger means abandoned work ran post-deadline.
            assert events_after <= 2, (
                f"post-deadline side effects observed: {events_after} events "
                f"written after {timed_out} timeouts (occupy + at most 1)"
            )
        finally:
            await client.aclose()

    asyncio.run(scenario())
