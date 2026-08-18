from __future__ import annotations

from pathlib import Path

from src.integration.bridge_config import BridgeConfig
from zero_mem.config import load_effective_config


def test_setup_bridge_and_effective_config_share_normalized_roots(monkeypatch, tmp_path: Path) -> None:
    capture = tmp_path / "capture"
    monkeypatch.setenv("ZERO_MEM_CAPTURE_ROOT", str(capture))
    monkeypatch.setenv("HERMES_PROJECT_ID", "project")
    monkeypatch.setenv("HERMES_PROFILE_ID", "profile")
    effective = load_effective_config()
    bridge = BridgeConfig(
        enabled=True,
        project_id="project",
        profile_id="profile",
        capture_root=capture,
        hermes_home=tmp_path / "hermes",
    )
    assert bridge.capture_root == effective.capture_root
    assert bridge.project_id == effective.project_id
    assert bridge.profile_id == effective.profile_id


def test_two_effective_configs_are_independent(monkeypatch, tmp_path: Path) -> None:
    first = load_effective_config(explicit={"enabled": True, "data_root": str(tmp_path / "one")})
    second = load_effective_config(explicit={"enabled": False, "data_root": str(tmp_path / "two")})
    assert first.enabled is True and second.enabled is False
    assert first.data_root != second.data_root
