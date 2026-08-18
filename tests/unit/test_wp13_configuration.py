from pathlib import Path

from src.integration.bridge_config import BridgeConfig


def test_relative_default_capture_root_is_validated_without_real_home_rejection() -> None:
    config = BridgeConfig(enabled=False)
    assert config.capture_root == (Path.cwd() / "data" / "traces").resolve()


def test_explicit_home_capture_root_remains_rejected() -> None:
    try:
        BridgeConfig(enabled=False, capture_root=Path.home() / "zero-mem")
    except ValueError as exc:
        assert "capture_root" in str(exc)
    else:
        raise AssertionError("explicit real-home capture root must be rejected")
