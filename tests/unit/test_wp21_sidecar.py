from __future__ import annotations

import pytest

from zero_mem import CoreConfig, LocalSidecar, PublicClient, SidecarError


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
