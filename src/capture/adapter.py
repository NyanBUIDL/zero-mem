"""Pure normalization and serialization for M1 event envelopes."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Sequence, Any, Mapping
from uuid import uuid4

from .event_types import (
    Confidence,
    EventType,
    LifecycleStatus,
    Retention,
    Sensitivity,
    VerificationStatus,
)
from .validation import validate_envelope


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash_content(content: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(content).encode("utf-8")).hexdigest()


def normalize_event(
    payload: Mapping[str, Any],
    *,
    sequence: int,
    event_type: EventType | str,
    source: str,
    profile_id: str | None = None,
    project_id: str | None = None,
    knowledge_space_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Copy and normalize a payload into a validated, deterministic envelope.

    V1.6.0 C1 (ADR-V160-01 sec3): knowledge_space_ids is an optional list of
    unique, non-empty space ids. The payload may also carry the key (then the
    payload value wins); duplicates are dropped preserving first-occurrence
    order. None omits the field (unscoped); [] is preserved as explicit
    empty (also unscoped per ADR sec2)."""
    if not isinstance(payload, Mapping):
        raise TypeError("event payload must be a mapping")
    copied = copy.deepcopy(dict(payload))
    event_value = event_type.value if isinstance(event_type, EventType) else event_type
    sanitized_content = copied.pop("sanitized_content", copied)
    envelope: dict[str, Any] = {
        "event_id": str(copied.pop("event_id", uuid4())),
        "trace_id": str(copied.pop("trace_id", uuid4())),
        "event_type": event_value,
        "source": source,
        "schema_version": 1,
        "created_at": utc_now(),
        "observed_at": utc_now(),
        "sequence": sequence,
        "session_id": copied.pop("session_id", None),
        "profile_id": profile_id,
        "project_id": project_id,
        "task_id": copied.pop("task_id", None),
        "turn_id": copied.pop("turn_id", None),
        "parent_trace_id": copied.pop("parent_trace_id", None),
        "relation_ids": tuple(copied.pop("relation_ids", ())),
        "lifecycle_status": copied.pop("lifecycle_status", LifecycleStatus.OBSERVED.value),
        "verification_status": copied.pop("verification_status", VerificationStatus.NONE.value),
        "confidence": copied.pop("confidence", Confidence.MEDIUM.value),
        "sensitivity": copied.pop("sensitivity", Sensitivity.PRIVATE.value),
        "retention": copied.pop("retention", Retention.PERSISTENT.value),
        "sanitized_content": sanitized_content,
        "sanitized_content_ref": copied.pop("sanitized_content_ref", None),
        "sanitized_content_hash": _hash_content(sanitized_content),
        "redaction_audit": copied.pop("redaction_audit", None),
    }
    # V1.6.0 C1: normalize knowledge_space_ids (payload key wins over param),
    # dedup preserving first-occurrence order; None omits, [] stays explicit.
    ks_raw = copied.pop("knowledge_space_ids", None)
    if ks_raw is None:
        ks_raw = knowledge_space_ids
    if ks_raw is not None:
        if not isinstance(ks_raw, (list, tuple)) or isinstance(ks_raw, (str, bytes)):
            raise ValueError("knowledge_space_ids must be a list of strings")
        seen_ks: set = set()
        ks_norm: list[str] = []
        for item in ks_raw:
            if not isinstance(item, str):
                raise ValueError("knowledge_space_ids must contain only strings")
            if item not in seen_ks:
                seen_ks.add(item)
                ks_norm.append(item)
        envelope["knowledge_space_ids"] = ks_norm
    if copied:
        envelope["sanitized_content"] = {"payload": sanitized_content, "extra": copied}
        envelope["sanitized_content_hash"] = _hash_content(envelope["sanitized_content"])
    validate_envelope(envelope)
    return envelope


def serialize_envelope(envelope: Mapping[str, Any]) -> str:
    """Serialize a validated envelope deterministically."""
    validate_envelope(envelope)
    return _canonical_json(envelope)


def deserialize_envelope(serialized: str) -> dict[str, Any]:
    value = json.loads(serialized)
    if not isinstance(value, dict):
        raise ValueError("serialized envelope must contain a JSON object")
    if "relation_ids" in value:
        value["relation_ids"] = tuple(value["relation_ids"])
    validate_envelope(value)
    return value
