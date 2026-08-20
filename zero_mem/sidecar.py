"""Transport-neutral local sidecar dispatcher with fail-closed boundaries."""
from __future__ import annotations

import json
import time
import warnings
from dataclasses import dataclass
from typing import Any

from .api import PublicClient

CONTRACT_VERSION = "1.1"
CAPABILITIES = ("observe", "sync", "health", "capabilities")
DEPRECATION_MESSAGE = (
    "zero_mem.sidecar.LocalSidecar is deprecated; use "
    "src.integration.sidecar.ZeroMemSidecar for the canonical bounded sidecar contract"
)


class SidecarError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class SidecarConfig:
    max_payload_bytes: int = 64 * 1024
    deadline_seconds: float = 5.0


class LocalSidecar:
    """Deprecated compatibility wrapper; canonical transport is ``ZeroMemSidecar``."""

    def __init__(self, client: PublicClient, *, config: SidecarConfig | None = None) -> None:
        warnings.warn(DEPRECATION_MESSAGE, DeprecationWarning, stacklevel=2)
        self._client = client
        self._config = config or SidecarConfig()
        if self._config.max_payload_bytes < 1 or self._config.deadline_seconds <= 0:
            raise SidecarError("CONFIG_INVALID")
        self._started = False

    def start(self) -> dict[str, Any]:
        if self._started:
            return self.health()
        self._started = True
        return self.health()

    def stop(self) -> dict[str, Any]:
        self._started = False
        return {"status": "STOPPED", "contract_version": CONTRACT_VERSION}

    def health(self) -> dict[str, Any]:
        return {"status": "READY" if self._started else "STOPPED", "contract_version": CONTRACT_VERSION, "transport": "embedded-local"}

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        if not self._started:
            raise SidecarError("UNAVAILABLE")
        if not isinstance(request, dict) or not isinstance(request.get("identity"), str) or not request["identity"]:
            raise SidecarError("IDENTITY_REQUIRED")
        try:
            size = len(json.dumps(request, ensure_ascii=False).encode("utf-8"))
        except (TypeError, ValueError):
            raise SidecarError("INVALID_REQUEST") from None
        if size > self._config.max_payload_bytes:
            raise SidecarError("PAYLOAD_TOO_LARGE")
        capability = request.get("capability")
        if capability not in CAPABILITIES:
            raise SidecarError("CAPABILITY_UNSUPPORTED")
        started = time.monotonic()
        if capability == "capabilities":
            result: Any = {"capabilities": list(CAPABILITIES), "contract_version": CONTRACT_VERSION}
        elif capability == "health":
            result = self.health()
        elif capability == "sync":
            result = self._client.sync()
        else:
            result = self._client.observe_message(request.get("payload"))
        if time.monotonic() - started > self._config.deadline_seconds:
            raise SidecarError("DEADLINE_EXCEEDED")
        return {"ok": True, "capability": capability, "result": result}


__all__ = ["CAPABILITIES", "CONTRACT_VERSION", "DEPRECATION_MESSAGE", "LocalSidecar", "SidecarConfig", "SidecarError"]
