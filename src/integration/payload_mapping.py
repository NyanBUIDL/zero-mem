"""Pure Increment 4.2 payload mapping boundary."""
from __future__ import annotations

import copy
import hashlib
import json
import uuid
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

PUBLIC_SUPPORTED_HOOKS = (
    "public_user_message",
    "public_assistant_message",
    "public_tool_call",
)

_PUBLIC_EVENT_CLASSES = {
    "public_user_message": "message_observation",
    "public_assistant_message": "message_observation",
    "public_tool_call": "pre_tool_call",
}


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
    return MappingResult("rejected", hook, _event_class(hook), None, _source(hook), None, code)


def _event_class(hook: str) -> str | None:
    return _PUBLIC_EVENT_CLASSES.get(hook) or event_class_for_hook(hook)


def _source(hook: str) -> str:
    if hook.startswith("public_"):
        return "public." + hook.removeprefix("public_")
    return f"hermes.{hook}"


def _event_type(hook: str) -> str:
    if hook in {"pre_llm_call", "public_user_message"}:
        return "user_statement"
    if hook in {"post_llm_call", "public_assistant_message"}:
        return "assistant_claim"
    if hook in {"pre_tool_call", "public_tool_call"}:
        return "tool_observation"
    if hook in {"post_tool_call"}:
        return "tool_observation"
    if hook.startswith("kanban_"):
        return "system_event"
    return "system_event"


def _generated_event_id(hook: str, payload: Mapping[str, Any]) -> str:
    """Use host occurrence identity when sufficient; otherwise generate one.

    Content is deliberately not used as identity. Repeating the same message or
    tool output is a new occurrence unless Hermes supplies the same occurrence
    identifiers again during a retry.
    """
    explicit = payload.get("event_id")
    if isinstance(explicit, str) and explicit:
        return explicit

    stable: dict[str, Any] | None = None
    if hook in {"pre_llm_call", "post_llm_call", "public_user_message", "public_assistant_message"}:
        if payload.get("session_id") and payload.get("turn_id"):
            stable = {"session_id": payload["session_id"], "turn_id": payload["turn_id"]}
    elif hook in {"on_session_start", "on_session_end", "on_session_finalize", "on_session_reset"}:
        if payload.get("session_id"):
            stable = {"session_id": payload["session_id"]}
    elif hook in {"pre_tool_call", "post_tool_call", "public_tool_call"}:
        discriminator = payload.get("tool_call_id") or payload.get("request_id") or payload.get("trace_id")
        if discriminator:
            stable = {"session_id": payload.get("session_id"), "occurrence_id": discriminator}
    elif hook in {"subagent_start", "subagent_stop"}:
        discriminator = payload.get("child_subagent_id") or payload.get("child_session_id")
        if discriminator:
            stable = {"parent_session_id": payload.get("parent_session_id"), "child_id": discriminator}
    elif hook == "on_skill_lifecycle":
        if payload.get("session_id") and payload.get("skill_name") and payload.get("action"):
            stable = {
                "session_id": payload["session_id"],
                "skill_name": payload["skill_name"],
                "action": payload["action"],
                "use_count": payload.get("use_count"),
            }
    elif hook.startswith("kanban_") and payload.get("task_id"):
        stable = {"task_id": payload["task_id"], "run_id": payload.get("run_id")}

    if stable is None:
        return f"generated:{hook}:{uuid.uuid4().hex}"
    material = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{hook}\0{material}".encode("utf-8")).hexdigest()[:32]
    return f"observed:{hook}:{digest}"


def _bounded_content(hook: str, copied: Mapping[str, Any]) -> dict[str, Any]:
    """Drop repeated full-history snapshots while preserving the current event."""
    bounded = dict(copied)
    if hook in {"pre_llm_call", "post_llm_call"}:
        bounded.pop("conversation_history", None)
    if hook == "post_llm_call":
        bounded.pop("user_message", None)
    return bounded


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
        return MappingResult("conditional_fixture_required", hook, _event_class(hook), None, _source(hook), None, "conditional_fixture_required")
    if hook in DEFERRED_HOOKS or hook not in VERIFIED_SUPPORTED_HOOKS + PUBLIC_SUPPORTED_HOOKS:
        return MappingResult("deferred", hook, None, None, _source(hook), None, "deferred_event_class")
    if not isinstance(payload, Mapping):
        return _fixed_failure(hook, "invalid_payload")
    try:
        copied = _safe_copy(payload, set())
        if not isinstance(copied, Mapping):
            return _fixed_failure(hook, "unsafe_payload")
        copied = _bounded_content(hook, copied)
        sanitized = redact_payload(copied)
        clean = sanitized.content
        if not isinstance(clean, Mapping):
            return _fixed_failure(hook, "unsafe_payload")
        mapped: dict[str, Any] = {
            "event_id": _generated_event_id(hook, clean),
            "event_type": _event_type(hook),
            "event_class": _event_class(hook),
            "source": _source(hook),
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
            for field in ("tool_name", "tool_call_id", "args", "result", "status", "error", "duration"):
                mapped[field] = clean.get(field)
        elif hook in {"public_tool_call"}:
            for field in ("tool_name", "tool_call_id", "args", "result", "status", "error", "duration"):
                mapped[field] = clean.get(field)
        elif hook in {"pre_llm_call", "public_user_message"}:
            mapped["actor"] = "user"
            mapped["message"] = clean.get("user_message", clean.get("message", clean.get("text")))
        elif hook in {"post_llm_call", "public_assistant_message"}:
            mapped["actor"] = "assistant"
            mapped["message"] = clean.get("assistant_response", clean.get("message", clean.get("text")))
        elif hook in {"subagent_start", "subagent_stop"}:
            for field in (
                "parent_session_id", "parent_turn_id", "parent_subagent_id",
                "child_session_id", "child_subagent_id", "child_role", "child_goal",
                "child_summary", "child_status", "tool_call_history", "duration_ms",
            ):
                mapped[field] = clean.get(field)
        elif hook == "on_skill_lifecycle":
            for field in ("action", "skill_name", "provenance", "use_count", "reused", "reuse_after_patch"):
                mapped[field] = clean.get(field)
        else:
            for field in ("model", "platform", "lifecycle_event", "timestamp"):
                mapped[field] = clean.get(field)
        return MappingResult("mapped", hook, _event_class(hook), mapped["event_type"], mapped["source"], mapped, None)
    except RedactionRejected as exc:
        code = "cyclic_payload" if "cycle" in str(exc).lower() else "redaction_rejected"
        return _fixed_failure(hook, code)
    except ValueError as exc:
        code = str(exc) if str(exc) in {"cyclic_payload", "unsafe_payload"} else "unsafe_payload"
        return _fixed_failure(hook, code)
    except Exception:
        return _fixed_failure(hook, "mapping_failed")


__all__ = ["MappingResult", "PUBLIC_SUPPORTED_HOOKS", "map_hook_payload"]
