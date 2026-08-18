from __future__ import annotations

from pathlib import Path

from src.integration.bridge_config import BridgeConfig
from src.integration.hermes_registration import RegistrationAdapter
from zero_mem.core import CoreConfig, ZeroMemClient


class Context:
    def __init__(self) -> None:
        self.hooks: dict[str, object] = {}

    def register_hook(self, name: str, callback: object) -> None:
        self.hooks[name] = callback


def test_hermes_registration_is_a_real_client_boundary(tmp_path: Path) -> None:
    config = BridgeConfig(
        enabled=True,
        project_id="project",
        profile_id="profile",
        capture_root=tmp_path / "capture",
        hermes_home=tmp_path / "hermes",
    )
    adapter = RegistrationAdapter(config)
    assert isinstance(adapter._client, ZeroMemClient)

    context = Context()
    registered = adapter.register(context)

    assert registered
    assert tuple(context.hooks) == registered


def test_public_client_can_be_used_without_hermes() -> None:
    client = ZeroMemClient(CoreConfig(project_id="project", profile_id="profile"))
    assert client.capture({"kind": "observation"}).reason_code == "CAPTURE_WRITER_UNCONFIGURED"
