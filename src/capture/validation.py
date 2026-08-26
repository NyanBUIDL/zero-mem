"""Deterministic validation for the M1 event contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from .event_types import (
    Confidence,
    EventType,
    LifecycleStatus,
    MAX_KNOWLEDGE_SPACE_ID_LENGTH,
    MAX_KNOWLEDGE_SPACE_IDS,
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
    "deletion",
    # V1.6.0 C1 (ADR-V160-01 §3): optional multi-KS capture contract.
    "knowledge_space_ids",
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
    # Deletion block: when present on a deletion event, it must carry an explicit target.
    # A plain event with lifecycle_status=='deleted' (e.g. already-deleted-at-source) is valid
    # without a deletion block (Decision B: tombstones are the canonical deletion record, but a
    # 'deleted' lifecycle state alone is still ingestible). A deletion block on a non-deleted
    # event is rejected (no invented deletion).
    deletion = envelope.get("deletion")
    if deletion is not None:
        if envelope["lifecycle_status"] != LifecycleStatus.DELETED.value:
            raise ValueError("deletion block only allowed on lifecycle_status='deleted'")
        if not isinstance(deletion, Mapping) or not isinstance(deletion.get("target_event_id"), str) \
                or not deletion.get("target_event_id").strip():
            raise ValueError("deletion block requires target_event_id")
    # V1.6.0 C1 (ADR-V160-01 §3): optional knowledge_space_ids capture contract.
    # Strict: list of unique non-empty strings within bounds; rejects ambiguity
    # (duplicates) fail-closed. Absence (None) and explicit [] are both unscoped.
    ks = envelope.get("knowledge_space_ids")
    if ks is not None:
        if not isinstance(ks, (list, tuple)) or isinstance(ks, (str, bytes)):
            raise ValueError("knowledge_space_ids must be a list of strings")
        if len(ks) > MAX_KNOWLEDGE_SPACE_IDS:
            raise ValueError("knowledge_space_ids exceeds max count")
        seen: set = set()
        for item in ks:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("knowledge_space_ids must contain non-empty strings")
            if len(item) > MAX_KNOWLEDGE_SPACE_ID_LENGTH:
                raise ValueError("knowledge_space_id exceeds max length")
            if item in seen:
                raise ValueError("knowledge_space_ids must not contain duplicates")
            seen.add(item)
