from __future__ import annotations

import pytest

from zero_mem import CoreConfig, LocalSidecar, PublicClient, SidecarError
from zero_mem.api import CapabilityResult


class _ReadService:
    def __init__(self, status: str, reason: str) -> None:
        self.status = status
        self.reason = reason

    def _result(self, capability: str) -> CapabilityResult:
        return CapabilityResult(capability, self.status, self.reason)

    def search(self, _request):
        return self._result("zero_mem.search")

    def get_trace(self, _request):
        return self._result("zero_mem.get_trace")

    def get_task_state(self, _request):
        return self._result("zero_mem.get_task_state")

    def get_decisions(self, _request):
        return self._result("zero_mem.get_decisions")


def test_local_sidecar_canonical_read_delegation_preserves_statuses() -> None:
    for status, reason in (("READY", "READ_OK"), ("EMPTY", "READ_EMPTY"), ("DENIED", "READ_DENIED"), ("STALE", "READ_STALE"), ("TIMEOUT", "READ_TIMEOUT"), ("UNAVAILABLE", "READ_UNAVAILABLE")):
        client = PublicClient.open(CoreConfig(), read_service=_ReadService(status, reason))
        with pytest.warns(DeprecationWarning):
            sidecar = LocalSidecar(client)
        sidecar.start()
        result = sidecar.dispatch({"identity": "profile-a", "capability": "search", "text": "x"})
        assert result["status"] == status
        assert result["reason_code"] == reason
        sidecar.stop()


def test_local_sidecar_canonical_read_rejects_identity_mismatch() -> None:
    client = PublicClient.open(CoreConfig(), read_service=_ReadService("READY", "READ_OK"))
    with pytest.warns(DeprecationWarning):
        sidecar = LocalSidecar(client)
    sidecar.start()
    with pytest.raises(SidecarError, match="IDENTITY_REQUIRED"):
        sidecar.dispatch({"capability": "search", "text": "x"})
    sidecar.stop()


def test_local_sidecar_canonical_read_is_bounded() -> None:
    client = PublicClient.open(CoreConfig(), read_service=_ReadService("READY", "READ_OK"))
    with pytest.warns(DeprecationWarning):
        sidecar = LocalSidecar(client, config=__import__("zero_mem").SidecarConfig(max_payload_bytes=32))
    sidecar.start()
    with pytest.raises(SidecarError, match="PAYLOAD_TOO_LARGE"):
        sidecar.dispatch({"identity": "profile-a", "capability": "search", "text": "x" * 100})
    sidecar.stop()


def test_local_sidecar_lifecycle_and_capabilities() -> None:
    with pytest.warns(DeprecationWarning, match=r"src\.integration\.sidecar\.ZeroMemSidecar"):
        sidecar = LocalSidecar(PublicClient.open(CoreConfig(enabled=False)))
    with pytest.raises(SidecarError, match="UNAVAILABLE"):
        sidecar.dispatch({"identity": "agent", "capability": "health"})
    assert sidecar.start()["status"] == "READY"
    result = sidecar.dispatch({"identity": "agent", "capability": "capabilities"})
    assert result["ok"] is True
    assert "observe" in result["result"]["capabilities"]
    assert sidecar.stop()["status"] == "STOPPED"


def test_local_sidecar_rejects_identity_and_oversized_payload() -> None:
    with pytest.warns(DeprecationWarning):
        sidecar = LocalSidecar(PublicClient.open(CoreConfig(enabled=False)), config=__import__("zero_mem").SidecarConfig(max_payload_bytes=16))
    sidecar.start()
    with pytest.raises(SidecarError, match="IDENTITY_REQUIRED"):
        sidecar.dispatch({"capability": "health"})
    with pytest.raises(SidecarError, match="PAYLOAD_TOO_LARGE"):
        sidecar.dispatch({"identity": "agent", "capability": "health", "payload": "x" * 100})
