from __future__ import annotations

import asyncio
import time

import pytest

from zero_mem import AppendReceipt, AsyncClient, AsyncQueueFullError, CoreConfig


class SlowWriter:
    def __init__(self, delay: float = 0.02) -> None:
        self.delay = delay
        self.events = []
        self.closed = 0

    def append(self, event: object) -> AppendReceipt:
        time.sleep(self.delay)
        self.events.append(event)
        return AppendReceipt("appended", f"event-{len(self.events)}", len(self.events) - 1, True)

    def close(self) -> None:
        self.closed += 1


def test_async_facade_offloads_and_closes_idempotently() -> None:
    async def scenario() -> None:
        writer = SlowWriter()
        async with AsyncClient.open(CoreConfig(), writer=writer, consistency_policy="append") as client:
            await client.session_start("s")
            result = await client.observe_message({"text": "x"})
            assert result.status == "CAPTURED"
            assert (await client.health()).status == "OK"
        assert writer.closed == 1
        assert await client.aclose() == "ALREADY_SHUTDOWN"

    asyncio.run(scenario())


def test_async_queue_is_bounded_and_reports_overflow() -> None:
    async def scenario() -> None:
        writer = SlowWriter(0.05)
        client = AsyncClient.open(CoreConfig(), writer=writer, consistency_policy="append", queue_capacity=1)
        first = asyncio.create_task(client.observe_message({"n": 1}))
        await asyncio.sleep(0)
        with pytest.raises(AsyncQueueFullError):
            await client.observe_message({"n": 2}, deadline=0.001)
        await first
        await client.aclose()

    asyncio.run(scenario())


def test_event_loop_heartbeat_runs_during_blocking_write() -> None:
    async def scenario() -> None:
        client = AsyncClient.open(CoreConfig(), writer=SlowWriter(0.05), consistency_policy="append")
        ticks = 0
        async def heartbeat() -> None:
            nonlocal ticks
            for _ in range(5):
                await asyncio.sleep(0.005)
                ticks += 1
        await asyncio.gather(client.observe_message({"x": 1}), heartbeat())
        await client.aclose()
        assert ticks == 5

    asyncio.run(scenario())
