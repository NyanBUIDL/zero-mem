"""Host-independent Zero-Mem client boundary.

This module deliberately contains no Hermes, transport, storage, retrieval, or
authorization implementation. Adapters provide explicit identity and an
injected writer; the client owns immutable runtime configuration and exposes a
small deterministic capture boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class EventWriter(Protocol):
    """Minimal append-only writer owned by the integrating application."""

    def append(self, event: object) -> None:
        """Append one already-sanitized event."""


@dataclass(frozen=True)
class CoreConfig:
    """Immutable client configuration; identity is never inferred."""

    enabled: bool = True
    project_id: str | None = None
    profile_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be bool")
        for name in ("project_id", "profile_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be a non-empty string or None")


@dataclass(frozen=True)
class CaptureResult:
    status: str
    reason_code: str | None = None


class ZeroMemClient:
    """Client-owned runtime boundary for generic and host adapters."""

    def __init__(
        self,
        config: CoreConfig,
        *,
        writer: EventWriter | None = None,
        consistency_policy: str | None = None,
    ) -> None:
        self.config = config
        self._writer = writer
        self._consistency_policy = consistency_policy
        if config.enabled and writer is not None and not consistency_policy:
            raise ValueError("consistency_policy is required when a writer is configured")

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def capture(self, event: object) -> CaptureResult:
        """Append through the explicit writer, or return a typed unavailable state."""
        if not self.config.enabled:
            return CaptureResult("CAPABILITY_UNAVAILABLE", "ZERO_MEM_DISABLED")
        if self._writer is None or not self._consistency_policy:
            return CaptureResult("CAPABILITY_UNAVAILABLE", "CAPTURE_WRITER_UNCONFIGURED")
        try:
            self._writer.append(event)
        except Exception:
            return CaptureResult("CAPABILITY_UNAVAILABLE", "CAPTURE_WRITE_FAILED")
        return CaptureResult("CAPTURED")


__all__ = ["CaptureResult", "CoreConfig", "EventWriter", "ZeroMemClient"]
