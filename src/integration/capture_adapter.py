"""Increment 4.3 sanitized mapping to contract/store adapter."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from src.capture.adapter import utc_now
from src.capture.event_types import EventType
from src.capture.validation import validate_envelope
from src.redaction import RedactionRejected, redact_payload
from src.storage.capture_boundary import AppendResult, CaptureRejected
from .payload_mapping import MappingResult


@dataclass(frozen=True)
class AdapterResult:
    code: str
    event_id: str | None = None
    trace_id: str | None = None
    event_class: str | None = None
    sequence: int | None = None
    duplicate_class: str | None = None
    safe_metadata: Mapping[str, Any] | None = None


def _fail(code: str, mapped: MappingResult | None) -> AdapterResult:
    return AdapterResult(
        code=code,
        event_id=_safe_id(mapped.payload if mapped and mapped.payload else None, "event_id"),
        trace_id=_safe_id(mapped.payload if mapped and mapped.payload else None, "trace_id"),
        event_class=mapped.event_class if mapped else None,
    )


def _safe_id(payload: Mapping[str, Any] | None, field: str) -> str | None:
    value = payload.get(field) if payload else None
    return value if isinstance(value, str) and value else None


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _contains_never_store(value: Any) -> bool:
    if isinstance(value, Mapping):
        if value.get("sensitivity") == "secret" or value.get("retention") == "never_store":
            return True
        return any(_contains_never_store(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_never_store(item) for item in value)
    return False


def _envelope(mapped: MappingResult, sanitized: Any) -> dict[str, Any]:
    if not isinstance(sanitized, Mapping):
        raise ValueError("invalid sanitized payload")
    source = mapped.source
    event_type = mapped.event_type or EventType.SYSTEM_EVENT.value
    payload = dict(sanitized)
    event_id = payload.get("event_id")
    trace_id = payload.get("trace_id")
    if not isinstance(event_id, str) or not event_id:
        event_id = f"mapped:{mapped.hook}:{payload.get('turn_id') or 'none'}"
    if not isinstance(trace_id, str) or not trace_id:
        trace_id = f"trace:{event_id}"
    created = payload.get("created_at") if isinstance(payload.get("created_at"), str) else utc_now()
    observed = payload.get("observed_at") if isinstance(payload.get("observed_at"), str) else utc_now()
    envelope = {
        "event_id": event_id,
        "trace_id": trace_id,
        "event_type": event_type,
        "source": source,
        "schema_version": 1,
        "created_at": created,
        "observed_at": observed,
        "sequence": 0,
        "session_id": payload.get("session_id"),
        "profile_id": payload.get("profile_id"),
        "project_id": payload.get("project_id"),
        "task_id": payload.get("task_id"),
        "turn_id": payload.get("turn_id"),
        "parent_trace_id": payload.get("parent_trace_id"),
        "relation_ids": list(payload.get("relation_ids", ())),
        "lifecycle_status": payload.get("lifecycle_status", "observed"),
        "verification_status": payload.get("verification_status", "none"),
        "confidence": payload.get("confidence", "medium"),
        "sensitivity": payload.get("sensitivity", "private"),
        "retention": payload.get("retention", "persistent"),
        "sanitized_content": sanitized,
        "sanitized_content_ref": payload.get("sanitized_content_ref"),
        "sanitized_content_hash": _canonical_hash(sanitized),
        "redaction_audit": payload.get("redaction_audit"),
    }
    # V1.6.0 C1 (ADR-V160-01 sec3): carry knowledge_space_ids into the
    # top-level envelope (legacy singular knowledge_space_id -> list).
    # V1.6.0 C1 follow-up (review): strict typing + ADR sec2 legacy fallback.
    ks = payload.get("knowledge_space_ids")
    legacy = payload.get("knowledge_space_id")
    # Fall back to legacy singular when the multi list is ABSENT or EMPTY
    # (ADR sec2: list rong + legacy set -> dung legacy). Malformed multi
    # (e.g. a bare string) is NOT treated as absent - it raises below.
    if ks is None or (isinstance(ks, list) and len(ks) == 0):
        if isinstance(legacy, str) and legacy.strip():
            ks = [legacy]
    if ks is not None:
        if not isinstance(ks, list) or isinstance(ks, (str, bytes)):
            raise ValueError("knowledge_space_ids must be a list of strings")
        for item in ks:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("knowledge_space_ids must contain non-empty strings")
        envelope["knowledge_space_ids"] = list(ks)
    validate_envelope(envelope)
    return envelope


def adapt_mapped_event(mapped: MappingResult | None, *, store: Any) -> AdapterResult:
    """Redact, validate, and append one already-mapped event exactly once."""
    if not isinstance(mapped, MappingResult):
        return _fail("mapping_rejected", None)
    if mapped.status == "conditional_fixture_required":
        return _fail("conditional_fixture_required", mapped)
    if mapped.status != "mapped" or not isinstance(mapped.payload, Mapping):
        return _fail("unsupported_hook", mapped)
    try:
        copied = copy.deepcopy(dict(mapped.payload))
        if copied.get("sensitivity") == "secret" or copied.get("retention") == "never_store":
            return _fail("redaction_rejected", mapped)
        sanitized = redact_payload(copied)
        if _contains_never_store(sanitized.content):
            return _fail("redaction_rejected", mapped)
        envelope = _envelope(mapped, sanitized.content)
        result = store.append(envelope)
        if not isinstance(result, AppendResult):
            return _fail("capture_failed", mapped)
        if result.status == "duplicate":
            code = "duplicate_event_id" if result.duplicate_class == "event_id" else "duplicate_content_hash"
            return AdapterResult(code, result.event_id, envelope["trace_id"], mapped.event_class, result.sequence, result.duplicate_class, {"schema_version": 1})
        return AdapterResult("appended", result.event_id, envelope["trace_id"], mapped.event_class, result.sequence, None, {"schema_version": 1, "event_id": result.event_id, "trace_id": envelope["trace_id"]})
    except RedactionRejected:
        return _fail("redaction_rejected", mapped)
    except CaptureRejected:
        return _fail("capture_failed", mapped)
    except (ValueError, TypeError):
        return _fail("envelope_validation_failed", mapped)
    except Exception:
        return _fail("capture_failed", mapped)


__all__ = ["AdapterResult", "adapt_mapped_event"]
