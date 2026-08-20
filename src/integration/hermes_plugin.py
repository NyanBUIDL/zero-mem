"""Public project-local Hermes host factory for the existing observer boundary."""
from __future__ import annotations

from typing import Any

from .bridge_config import BridgeConfig
from .hermes_registration import RegistrationAdapter


def create_plugin(config: BridgeConfig, *, store: Any = None) -> RegistrationAdapter:
    """Compose the existing registration adapter for an external host.

    The host remains responsible for calling ``register`` and ``shutdown``.
    No Hermes import, global storage path, or competing runtime is introduced.
    """
    if not isinstance(config, BridgeConfig):
        raise TypeError("config must be BridgeConfig")
    return RegistrationAdapter(config, store=store)


__all__ = ["create_plugin"]
