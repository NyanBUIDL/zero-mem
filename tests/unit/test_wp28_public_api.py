from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from zero_mem import API_VERSION, AppendReceipt, CoreConfig, PublicClient
from zero_mem.api import AsyncClient, AsyncQueueFullError, InvalidRequestError


class FailingWriter:
    def __init__(self, *, fail_sync: bool = False, fail_close: bool = False) -> None:
        self.events: list[object] = []
        self.fail_sync = fail_sync
        self.fail_close = fail_close

    def append(self, event: object) -> AppendReceipt:
        self.events.append(event)
        return AppendReceipt("appended", "event-1", 0, True)

    def sync(self) -> None:
        if self.fail_sync:
            raise RuntimeError("secret-sync-error")

    def close(self) -> None:
        if self.fail_close:
            raise RuntimeError("secret-close-error")


def test_wp28_public_contract_matrix_and_unavailable_capabilities() -> None:
    client = PublicClient.open(CoreConfig(project_id="p", profile_id="r"), writer=FailingWriter(), consistency_policy="append")
    assert client.session_start("s") == "SESSION_ACTIVE"
    assert client.observe_message({"text": "x"}).status == "CAPTURED"
    assert client.observe_tool_call({"name": "t"}).status == "CAPTURED"
    assert client.sync() == "SYNCED"
    assert client.health().api_version == API_VERSION
    for method, capability in ((client.search, "zero_mem.search"), (client.get_trace, "zero_mem.get_trace"), (client.get_task_state, "zero_mem.get_task_state"), (client.get_decisions, "zero_mem.get_decisions")):
        result = method({})
        assert (result.capability, result.status, result.reason_code) == (capability, "CAPABILITY_UNAVAILABLE", "CAPABILITY_NOT_IMPLEMENTED")
    assert client.shutdown() == "SHUTDOWN"
    assert client.shutdown() == "ALREADY_SHUTDOWN"


def test_wp28_invalid_inputs_and_disabled_capture_fail_closed() -> None:
    client = PublicClient.open(CoreConfig(enabled=False))
    with pytest.raises(InvalidRequestError):
        client.session_start("")
    with pytest.raises(InvalidRequestError):
        client.observe_message(None)
    assert client.observe_message({"x": 1}).reason_code == "ZERO_MEM_DISABLED"
    client.shutdown()


def test_wp28_async_queue_and_deadline_are_bounded() -> None:
    async def scenario() -> None:
        client = AsyncClient.open(CoreConfig(enabled=False), queue_capacity=1)
        assert (await client.health()).api_version == API_VERSION
        assert (await client.session_start("s")).startswith("SESSION_")
        with pytest.raises(AsyncQueueFullError):
            await client.sync(deadline=0.0)
        await client.aclose()

    asyncio.run(scenario())


def test_wp28_public_module_stays_transport_and_storage_neutral() -> None:
    source = (Path(__file__).resolve().parents[2] / "zero_mem/api.py").read_text()
    assert "from src" not in source and "import src" not in source
    assert "sqlite" not in source.lower()
