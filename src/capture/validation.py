"""Deterministic validation for the M1 event contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from .event_types import (
    Confidence,
    EventType,
    LifecycleStatus,
    Retention,
    Sensitivity,
    VerificationStatus,
)


REQUIRED_FIELDS = (
    "event_id",
    "trace_id",
    "event_type",
    "source",
    "schema_version",
    "created_at",
    "observed_at",
    "sequence",
    "lifecycle_status",
    "verification_status",
    "confidence",
    "sensitivity",
    "retention",
    "sanitized_content_hash",
)

OPTIONAL_FIELDS = (
    "session_id",
    "profile_id",
    "project_id",
    "task_id",
    "turn_id",
    "parent_trace_id",
    "relation_ids",
    "sanitized_content",
    "sanitized_content_ref",
    "redaction_audit",
)


def _require_text(envelope: Mapping[str, Any], field: str) -> None:
    if not isinstance(envelope.get(field), str) or not envelope[field].strip():
        raise ValueError(f"{field} must be a non-empty string")


def _parse_utc(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field} must be an RFC3339 UTC timestamp ending in Z")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field} must be an RFC3339 UTC timestamp") from exc


def _enum_value(value: Any, enum_type: type, field: str) -> None:
    if not isinstance(value, str) or value not in {item.value for item in enum_type}:
        raise ValueError(f"{field} has an invalid value")


def validate_envelope(envelope: Mapping[str, Any]) -> None:
    """Validate an already-sanitized envelope without mutating it or using an LLM."""
    if not isinstance(envelope, Mapping):
        raise TypeError("event envelope must be a mapping")
    missing = [field for field in REQUIRED_FIELDS if field not in envelope]
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")
    for field in ("event_id", "trace_id", "source", "sanitized_content_hash"):
        _require_text(envelope, field)
    if envelope["schema_version"] != 1:
        raise ValueError("unsupported schema_version")
    _enum_value(envelope["event_type"], EventType, "event_type")
    _enum_value(envelope["lifecycle_status"], LifecycleStatus, "lifecycle_status")
    _enum_value(envelope["verification_status"], VerificationStatus, "verification_status")
    _enum_value(envelope["confidence"], Confidence, "confidence")
    _enum_value(envelope["sensitivity"], Sensitivity, "sensitivity")
    _enum_value(envelope["retention"], Retention, "retention")
    _parse_utc(envelope["created_at"], "created_at")
    _parse_utc(envelope["observed_at"], "observed_at")
    if not isinstance(envelope["sequence"], int) or envelope["sequence"] < 0:
        raise ValueError("sequence must be a non-negative integer")
    if "relation_ids" in envelope and not isinstance(envelope["relation_ids"], (list, tuple)):
        raise ValueError("relation_ids must be a list or tuple when present")
    if "relation_ids" in envelope:
        if any(not isinstance(item, str) or not item.strip() for item in envelope["relation_ids"]):
            raise ValueError("relation_ids must contain non-empty strings")
    if "parent_trace_id" in envelope and envelope["parent_trace_id"] is not None:
        _require_text(envelope, "parent_trace_id")
    if envelope["event_type"] == EventType.VERIFIED_STATE.value:
        if envelope["verification_status"] in {
            VerificationStatus.NONE.value,
            VerificationStatus.DIRECT_TOOL_OUTPUT.value,
        }:
            raise ValueError("verified_state requires explicit verification or approval")
    if envelope["event_type"] == EventType.ASSISTANT_CLAIM.value:
        if envelope["verification_status"] != VerificationStatus.NONE.value:
            raise ValueError("assistant_claim cannot carry verified-state evidence")
        if envelope["lifecycle_status"] == LifecycleStatus.ACTIVE.value:
            raise ValueError("assistant_claim cannot be active")
