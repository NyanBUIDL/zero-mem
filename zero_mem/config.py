"""Immutable effective configuration for one Zero-Mem runtime."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .paths import CONFIG_SCHEMA_VERSION, ConfigurationError, data_root, config_path


class EffectiveConfigurationError(ConfigurationError):
    """Sanitized configuration validation failure."""


@dataclass(frozen=True)
class EffectiveConfig:
    schema_version: int
    enabled: bool
    data_root: Path
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
    return EffectiveConfig(CONFIG_SCHEMA_VERSION, enabled, root.resolve(), source)


__all__ = ["EffectiveConfig", "EffectiveConfigurationError", "load_effective_config"]
