"""Pure Increment 4.2 payload mapping boundary."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from src.redaction import RedactionRejected, redact_payload
from .bridge_config import (
    CONDITIONAL_FIXTURE_REQUIRED,
    DEFERRED_HOOKS,
    VERIFIED_SUPPORTED_HOOKS,
    event_class_for_hook,
)

_STATUS = Literal["mapped", "conditional_fixture_required", "deferred", "rejected"]


@dataclass(frozen=True)
class MappingResult:
    status: _STATUS
    hook: str
    event_class: str | None
    event_type: str | None
    source: str
    payload: Mapping[str, Any] | None
    diagnostic_code: str | None


def _safe_copy(value: Any, seen: set[int]) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("unsafe_payload")
        return value
    if isinstance(value, Mapping):
        marker = id(value)
        if marker in seen:
            raise ValueError("cyclic_payload")
        seen.add(marker)
        try:
            return {key: _safe_copy(item, seen) for key, item in value.items()}
        finally:
            seen.remove(marker)
    if isinstance(value, list):
        marker = id(value)
        if marker in seen:
            raise ValueError("cyclic_payload")
        seen.add(marker)
        try:
            return [_safe_copy(item, seen) for item in value]
        finally:
            seen.remove(marker)
    if isinstance(value, tuple):
        marker = id(value)
        if marker in seen:
            raise ValueError("cyclic_payload")
        seen.add(marker)
        try:
            return tuple(_safe_copy(item, seen) for item in value)
        finally:
            seen.remove(marker)
    raise ValueError("unsafe_payload")


def _fixed_failure(hook: str, code: str) -> MappingResult:
    return MappingResult("rejected", hook, event_class_for_hook(hook), None, f"hermes.{hook}", None, code)


def _event_type(hook: str) -> str:
    if hook in {"pre_tool_call"}:
        return "tool_observation"
    if hook in {"post_tool_call"}:
        return "tool_observation"
    if hook.startswith("kanban_"):
        return "system_event"
    return "system_event"


def map_hook_payload(
    hook: str,
    payload: Mapping[str, Any],
    *,
    project_id: str | None = None,
    profile_id: str | None = None,
) -> MappingResult:
    """Copy, structurally normalize, redact, then map one fixture payload.

    This function has no filesystem, Hermes runtime, network, LLM, or store
    dependency. It returns a sanitized mapping result only.
    """
    if hook in CONDITIONAL_FIXTURE_REQUIRED:
        return MappingResult("conditional_fixture_required", hook, event_class_for_hook(hook), None, f"hermes.{hook}", None, "conditional_fixture_required")
    if hook in DEFERRED_HOOKS or hook not in VERIFIED_SUPPORTED_HOOKS:
        return MappingResult("deferred", hook, None, None, f"hermes.{hook}", None, "deferred_event_class")
    if not isinstance(payload, Mapping):
        return _fixed_failure(hook, "invalid_payload")
    try:
        copied = _safe_copy(payload, set())
        sanitized = redact_payload(copied)
        clean = sanitized.content
        if not isinstance(clean, Mapping):
            return _fixed_failure(hook, "unsafe_payload")
        mapped: dict[str, Any] = {
            "event_id": clean.get("event_id") or f"unassigned:{hook}:{clean.get('turn_id') or 'none'}",
            "event_type": _event_type(hook),
            "event_class": event_class_for_hook(hook),
            "source": f"hermes.{hook}",
            "session_id": clean.get("session_id"),
            "profile_id": clean.get("profile_id", profile_id),
            "project_id": clean.get("project_id", project_id),
            "turn_id": clean.get("turn_id"),
            "task_id": clean.get("task_id"),
            "request_id": clean.get("request_id"),
            "trace_id": clean.get("trace_id"),
            "parent_trace_id": clean.get("parent_trace_id"),
            "relation_ids": clean.get("relation_ids", ()),
            "sanitized_content": clean,
            "redaction_audit": sanitized.audit.to_dict(),
            "sanitized_content_hash": sanitized.content_hash,
        }
        if hook.startswith("kanban_"):
            for field in ("board", "assignee", "run_id", "profile_name", "summary", "reason", "lifecycle_status"):
                mapped[field] = clean.get(field)
        elif hook in {"pre_tool_call", "post_tool_call"}:
            for field in ("tool_name", "args", "result", "status", "error", "duration"):
                mapped[field] = clean.get(field)
        else:
            for field in ("model", "platform", "lifecycle_event", "timestamp"):
                mapped[field] = clean.get(field)
        return MappingResult("mapped", hook, event_class_for_hook(hook), mapped["event_type"], mapped["source"], mapped, None)
    except RedactionRejected as exc:
        code = "cyclic_payload" if "cycle" in str(exc).lower() else "redaction_rejected"
        return _fixed_failure(hook, code)
    except ValueError as exc:
        code = str(exc) if str(exc) in {"cyclic_payload", "unsafe_payload"} else "unsafe_payload"
        return _fixed_failure(hook, code)
    except Exception:
        return _fixed_failure(hook, "mapping_failed")


__all__ = ["MappingResult", "map_hook_payload"]
