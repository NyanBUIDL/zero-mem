from pathlib import Path

from src.integration.bridge_config import BridgeConfig
from zero_mem.config import EffectiveConfigurationError, configuration_contract, load_effective_config


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


def test_effective_configuration_precedence_and_redacted_diagnostics(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ZERO_MEM_ENABLED", "off")
    monkeypatch.setenv("ZERO_MEM_DATA_ROOT", str(tmp_path / "env"))
    config = load_effective_config(explicit={"enabled": True, "data_root": str(tmp_path / "explicit")})
    assert config.enabled is True
    assert config.data_root == (tmp_path / "explicit").resolve()
    assert config.diagnostics()["source"] == {"data_root": "explicit", "enabled": "explicit"}
    assert "secret" not in repr(config.diagnostics()).lower()


def test_unknown_effective_configuration_field_fails_closed() -> None:
    try:
        load_effective_config(explicit={"not_a_setting": True})
    except EffectiveConfigurationError as exc:
        assert "not_a_setting" in str(exc)
    else:
        raise AssertionError("unknown configuration fields must fail")


def test_effective_configuration_converges_integration_and_workspace_inputs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HERMES_PROJECT_ID", "project-a")
    monkeypatch.setenv("HERMES_PROFILE_ID", "profile-a")
    monkeypatch.setenv("ZERO_MEM_CAPTURE_ROOT", str(tmp_path / "capture"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("ZERO_MEM_OBSIDIAN_VAULT", str(tmp_path / "vault"))
    config = load_effective_config()
    assert config.project_id == "project-a"
    assert config.profile_id == "profile-a"
    assert config.capture_root == (tmp_path / "capture").resolve()
    assert config.hermes_home == (tmp_path / "hermes").resolve()
    assert config.obsidian_vault == (tmp_path / "vault").resolve()
    assert config.managed_dir_name == "Zero-Mem"


def test_configuration_contract_defines_reversible_unknown_and_schema_behavior() -> None:
    contract = configuration_contract()
    assert contract["precedence"] == ["explicit", "environment", "descriptor", "default"]
    assert contract["unknown_fields"] == "reject"
    assert contract["unsupported_schema"] == "reject_without_mutation"
