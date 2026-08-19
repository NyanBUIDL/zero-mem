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

    def append(self, event: object) -> "AppendReceipt":
        """Append one already-sanitized event and return durability evidence."""
        ...


@dataclass(frozen=True)
class AppendReceipt:
    """Durability evidence returned by a canonical append operation."""

    status: str
    event_id: str | None
    sequence: int | None
    canonical_durable: bool
    duplicate_class: str | None = None
    reason_code: str | None = None


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
            raw_receipt = self._writer.append(event)
        except Exception:
            return CaptureResult("CAPABILITY_UNAVAILABLE", "CAPTURE_WRITE_FAILED")
        receipt = _normalize_append_receipt(raw_receipt)
        if not receipt.canonical_durable:
            return CaptureResult(
                "CAPABILITY_UNAVAILABLE",
                receipt.reason_code or "CANONICAL_APPEND_NOT_DURABLE",
            )
        return CaptureResult("CAPTURED", receipt.reason_code)


def _normalize_append_receipt(raw: object) -> AppendReceipt:
    """Normalize and validate storage evidence without importing storage modules."""
    missing = object()
    status = getattr(raw, "status", missing)
    event_id = getattr(raw, "event_id", missing)
    sequence = getattr(raw, "sequence", missing)
    duplicate_class = getattr(raw, "duplicate_class", missing)
    reported_durable = getattr(raw, "canonical_durable", missing)
    supplied_reason = getattr(raw, "reason_code", missing)
    if any(value is missing for value in (status, event_id, sequence, duplicate_class, reported_durable, supplied_reason)):
        return AppendReceipt("failed", None, None, False, reason_code="CANONICAL_APPEND_RECEIPT_MISSING")
    if status is None or not isinstance(status, str):
        return AppendReceipt("failed", None, None, False, reason_code="CANONICAL_APPEND_RECEIPT_MISSING")
    duplicate_class = duplicate_class if isinstance(duplicate_class, str) else None
    supplied_reason = supplied_reason if isinstance(supplied_reason, str) else (None if supplied_reason is None else "CANONICAL_APPEND_REJECTED")
    status = str(status)
    durable = status in {"appended", "duplicate"} and reported_durable is True and isinstance(event_id, str) and bool(event_id) and isinstance(sequence, int) and not isinstance(sequence, bool) and sequence >= 0
    if reported_durable is not None and reported_durable is not True:
        durable = False
    if status in {"appended", "duplicate"} and not durable:
        return AppendReceipt("failed", event_id if isinstance(event_id, str) else None, sequence if isinstance(sequence, int) and not isinstance(sequence, bool) else None, False, duplicate_class=duplicate_class, reason_code="INVALID_CANONICAL_APPEND_RECEIPT")
    reason_code = "CANONICAL_DUPLICATE" if status == "duplicate" else supplied_reason
    if reason_code is not None and (not isinstance(reason_code, str) or reason_code not in {"append_failed", "CAPTURE_WRITE_FAILED", "CANONICAL_APPEND_NOT_DURABLE", "CANONICAL_APPEND_RECEIPT_MISSING", "INVALID_CANONICAL_APPEND_RECEIPT", "CANONICAL_APPEND_REJECTED", "CANONICAL_DUPLICATE"}):
        reason_code = "CANONICAL_APPEND_REJECTED"
    return AppendReceipt(status, event_id if isinstance(event_id, str) else None, sequence if isinstance(sequence, int) and not isinstance(sequence, bool) else None, durable, duplicate_class=duplicate_class, reason_code=reason_code)


__all__ = ["AppendReceipt", "CaptureResult", "CoreConfig", "EventWriter", "ZeroMemClient"]
