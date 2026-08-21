from __future__ import annotations

import pytest
from pathlib import Path

from zero_mem import API_VERSION, CoreConfig, PublicClient
from zero_mem.api import ClientClosedError, InvalidRequestError
from zero_mem.core import AppendReceipt


class Writer:
    def __init__(self) -> None:
        self.events = []
        self.synced = 0
        self.closed = 0

    def append(self, event: object) -> AppendReceipt:
        self.events.append(event)
        return AppendReceipt("appended", f"event-{len(self.events)}", len(self.events) - 1, True)

    def sync(self) -> None:
        self.synced += 1

    def close(self) -> None:
        self.closed += 1


def test_public_generic_lifecycle_and_idempotent_shutdown() -> None:
    writer = Writer()
    client = PublicClient.open(CoreConfig(project_id="p", profile_id="r"), writer=writer, consistency_policy="append")
    assert client.session_start("s1") == "SESSION_ACTIVE"
    assert client.observe_message({"text": "hello"}).status == "CAPTURED"
    assert client.observe_tool_call({"name": "tool"}).status == "CAPTURED"
    assert client.sync() == "SYNCED"
    assert client.health().api_version == API_VERSION
    assert client.shutdown() == "SHUTDOWN"
    assert client.shutdown() == "ALREADY_SHUTDOWN"
    assert len(writer.events) == 2 and writer.synced == 1 and writer.closed == 1


def test_four_capabilities_are_typed_and_unavailable_until_owned() -> None:
    client = PublicClient.open(CoreConfig(enabled=False))
    for method, name in ((client.search, "zero_mem.search"), (client.get_trace, "zero_mem.get_trace"),
                         (client.get_task_state, "zero_mem.get_task_state"), (client.get_decisions, "zero_mem.get_decisions")):
        result = method({})
        assert result.capability == name
        assert result.status == "CAPABILITY_UNAVAILABLE"
    client.shutdown()


def test_public_boundary_rejects_invalid_input_and_closed_use() -> None:
    client = PublicClient.open(CoreConfig(enabled=False))
    with pytest.raises(InvalidRequestError):
        client.session_start("")
    client.shutdown()
    with pytest.raises(ClientClosedError):
        client.health()


def test_public_api_module_has_no_internal_src_dependency() -> None:
    source = (Path(__file__).resolve().parents[2] / "zero_mem/api.py").read_text()
    assert "from src" not in source and "import src" not in source


def test_public_health_surfaced_truthfully_from_provider() -> None:
    # R124-03: when a truthful health provider is wired, PublicClient.health() must
    # surface the provider's real freshness/watermark state, NOT a hardcoded OK.
    class TruthfulProvider:
        def health(self):
            return {
                "status": "CLOSED",
                "mode": "off",
                "capture_enabled": False,
                "read_enabled": False,
                "injection_enabled": False,
                "writer_open": False,
                "canonical_store_identity": None,
                "read_store_identity": None,
                "last_canonical_sequence": 0,
                "last_projected_sequence": 0,
                "lag": 0,
                "projection_status": None,
                "last_projection_error": None,
                "readiness": "OFF",
                "reason_code": "BOUNDARY_DISABLED",
            }

        def sync_status(self):
            return "OFF"

    client = PublicClient.open(CoreConfig(enabled=False), health_provider=TruthfulProvider())
    health = client.health()
    assert health.status == "CLOSED"
    assert health.runtime_mode == "off"
    assert health.capture_enabled is False
    assert health.writer_open is False
    assert client.sync() == "OFF"
    client.shutdown()


def test_public_health_unconfigured_without_provider_is_not_ok() -> None:
    # R124-03: without a provider, an unconfigured client must not self-green to OK.
    client = PublicClient.open(CoreConfig(enabled=False))
    assert client.health().status == "UNCONFIGURED"
    client.shutdown()
