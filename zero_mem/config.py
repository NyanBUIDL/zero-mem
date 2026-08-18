"""Immutable effective configuration for one Zero-Mem runtime."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .paths import CONFIG_SCHEMA_VERSION, ConfigurationError, data_root, config_path

SUPPORTED_ENVIRONMENT_INPUTS = (
    "ZERO_MEM_ENABLED",
    "ZERO_MEM_DATA_ROOT",
    "ZERO_MEM_CAPTURE_ROOT",
    "HERMES_PROJECT_ID",
    "HERMES_PROFILE_ID",
    "HERMES_HOME",
    "ZERO_MEM_OBSIDIAN_VAULT",
    "ZERO_MEM_OBSIDIAN_MANAGED_DIR",
)


class EffectiveConfigurationError(ConfigurationError):
    """Sanitized configuration validation failure."""


@dataclass(frozen=True)
class EffectiveConfig:
    schema_version: int
    enabled: bool
    data_root: Path
    project_id: str | None
    profile_id: str | None
    capture_root: Path
    hermes_home: Path | None
    obsidian_vault: Path | None
    managed_dir_name: str
    source: Mapping[str, str]

    def diagnostics(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "enabled": self.enabled,
            "data_root": str(self.data_root),
            "source": dict(sorted(self.source.items())),
        }


def _bool(value: object, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}:
        return True
    if isinstance(value, str) and value.strip().lower() in {"0", "false", "no", "off"}:
        return False
    raise EffectiveConfigurationError(f"invalid {field}")


def load_effective_config(*, explicit: Mapping[str, object] | None = None) -> EffectiveConfig:
    """Resolve explicit values, environment, descriptor, then platform defaults."""
    explicit = dict(explicit or {})
    descriptor: dict[str, object] = {}
    path = config_path()
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            raise EffectiveConfigurationError("configuration descriptor is malformed") from None
        if not isinstance(raw, dict):
            raise EffectiveConfigurationError("configuration descriptor must be an object")
        descriptor = raw
    allowed = {"enabled", "data_root"}
    unknown = set(explicit) - allowed
    if unknown:
        raise EffectiveConfigurationError(f"unknown configuration field: {sorted(unknown)[0]}")
    source: dict[str, str] = {}
    if "enabled" in explicit:
        enabled = _bool(explicit["enabled"], "enabled")
        source["enabled"] = "explicit"
    elif os.environ.get("ZERO_MEM_ENABLED") is not None:
        enabled = _bool(os.environ["ZERO_MEM_ENABLED"], "ZERO_MEM_ENABLED")
        source["enabled"] = "environment"
    else:
        enabled = True
        source["enabled"] = "default"
    if "data_root" in explicit:
        root = Path(str(explicit["data_root"])).expanduser()
        source["data_root"] = "explicit"
    elif os.environ.get("ZERO_MEM_DATA_ROOT") is not None:
        root = Path(os.environ["ZERO_MEM_DATA_ROOT"]).expanduser()
        source["data_root"] = "environment"
    else:
        root = data_root()
        source["data_root"] = "default"
    if not root.is_absolute():
        raise EffectiveConfigurationError("data_root must be absolute")
    if "schema_version" in descriptor and descriptor["schema_version"] != CONFIG_SCHEMA_VERSION:
        raise EffectiveConfigurationError("unsupported configuration schema")
    def optional_path(env_name: str) -> Path | None:
        value = os.environ.get(env_name)
        if not value:
            return None
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            raise EffectiveConfigurationError(f"{env_name} must be absolute")
        return candidate.resolve()

    def optional_id(env_name: str) -> str | None:
        value = os.environ.get(env_name)
        if value is None:
            return None
        value = value.strip()
        return value or None

    managed_dir_name = os.environ.get("ZERO_MEM_OBSIDIAN_MANAGED_DIR", "Zero-Mem").strip()
    if not managed_dir_name or "/" in managed_dir_name or "\\" in managed_dir_name:
        raise EffectiveConfigurationError("invalid ZERO_MEM_OBSIDIAN_MANAGED_DIR")
    capture_root = optional_path("ZERO_MEM_CAPTURE_ROOT") or (root / "data" / "traces")
    return EffectiveConfig(
        CONFIG_SCHEMA_VERSION,
        enabled,
        root.resolve(),
        optional_id("HERMES_PROJECT_ID"),
        optional_id("HERMES_PROFILE_ID"),
        capture_root,
        optional_path("HERMES_HOME"),
        optional_path("ZERO_MEM_OBSIDIAN_VAULT"),
        managed_dir_name,
        source,
    )


def configuration_contract() -> dict[str, object]:
    """Return the non-secret compatibility contract for configuration inputs."""
    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "precedence": ["explicit", "environment", "descriptor", "default"],
        "supported_environment_inputs": list(SUPPORTED_ENVIRONMENT_INPUTS),
        "unknown_fields": "reject",
        "unsupported_schema": "reject_without_mutation",
        "secrets": "not_supported_in_configuration_contract",
    }


__all__ = ["EffectiveConfig", "EffectiveConfigurationError", "SUPPORTED_ENVIRONMENT_INPUTS", "configuration_contract", "load_effective_config"]
