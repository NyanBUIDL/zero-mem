"""Increment 4.1 bridge configuration and event registries.

No Hermes hooks are registered here. This module is deliberately pure and
contains only explicit configuration, immutable registries, and sanitized
metrics.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Mapping


VERIFIED_SUPPORTED_HOOKS: Final[tuple[str, ...]] = (
    "on_session_start",
    "on_session_end",
    "on_session_finalize",
    "on_session_reset",
    "pre_tool_call",
    "post_tool_call",
    "pre_llm_call",
    "post_llm_call",
    "on_skill_lifecycle",
    "subagent_start",
    "subagent_stop",
    "kanban_task_claimed",
    "kanban_task_completed",
    "kanban_task_blocked",
)

CONDITIONAL_FIXTURE_REQUIRED: Final[tuple[str, ...]] = (
    "pre_api_request",
    "post_api_request",
    "api_request_error",
)

DEFERRED_HOOKS: Final[tuple[str, ...]] = (
    "file_operations",
    "generic_task_transitions",
    "transform_terminal_output",
    "transform_tool_result",
    "transform_llm_output",
    "pre_verify",
    "pre_gateway_dispatch",
    "pre_approval_request",
    "post_approval_response",
)

HOOK_REGISTRY: Final[dict[str, tuple[str, ...]]] = {
    "verified_supported": VERIFIED_SUPPORTED_HOOKS,
    "conditional_fixture_required": CONDITIONAL_FIXTURE_REQUIRED,
    "deferred": DEFERRED_HOOKS,
}

_EVENT_CLASSES: Final[dict[str, str]] = {
    "on_session_start": "session_lifecycle",
    "on_session_end": "session_lifecycle",
    "on_session_finalize": "session_lifecycle",
    "on_session_reset": "session_lifecycle",
    "pre_tool_call": "pre_tool_call",
    "post_tool_call": "post_tool_call",
    "pre_llm_call": "llm_api_lifecycle",
    "post_llm_call": "llm_api_lifecycle",
    "pre_api_request": "llm_api_lifecycle",
    "post_api_request": "llm_api_lifecycle",
    "api_request_error": "llm_api_lifecycle",
    "subagent_start": "subagent_lifecycle",
    "subagent_stop": "subagent_lifecycle",
    "on_skill_lifecycle": "skill_lifecycle",
    "kanban_task_claimed": "verified_task_or_kanban_lifecycle",
    "kanban_task_completed": "verified_task_or_kanban_lifecycle",
    "kanban_task_blocked": "verified_task_or_kanban_lifecycle",
}


def _assert_registry() -> None:
    groups = list(HOOK_REGISTRY.values())
    flattened = [hook for group in groups for hook in group]
    if len(flattened) != len(set(flattened)):
        raise RuntimeError("duplicate bridge hook registry entry")
    if set(_EVENT_CLASSES) & set(DEFERRED_HOOKS):
        raise RuntimeError("deferred hook is mapped as operational")


_assert_registry()


def _resolve_identity(explicit: str | None, env_name: str) -> str | None:
    if explicit is not None:
        value = explicit.strip()
        return value or None
    value = os.environ.get(env_name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _safe_root(root: Path) -> Path:
    # Relative defaults are repository/application-local paths; explicit absolute
    # paths under the real home remain rejected to avoid accidental user-data
    # writes. Tilde expansion is treated as explicit and remains rejected.
    explicit_home_path = root.is_absolute() or str(root).startswith("~")
    resolved = root.expanduser().resolve()
    if explicit_home_path and (resolved == Path.home() or Path.home() in resolved.parents):
        raise ValueError("capture_root must not be inside the real home directory")
    return resolved


@dataclass(frozen=True)
class BridgeConfig:
    """Explicit, disabled-by-default project bridge configuration."""

    enabled: bool = False
    project_id: str | None = None
    profile_id: str | None = None
    capture_root: Path = field(default_factory=lambda: Path("data/traces"))
    hermes_home: Path | None = None
    use_environment_identity: bool = True
    # M7.1 master Zero-Mem runtime switch (the ONE user-facing master boolean).
    # Absent/missing defaults to True (backward-compatible with M0-M6 behavior).
    # The per-bridge ``enabled`` flag remains a separate, narrower opt-in that
    # controls whether this project's bridge wires hooks/tools at all; the master
    # switch controls whether Zero-Mem participates globally.
    zero_mem_enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be bool")
        if not isinstance(self.zero_mem_enabled, bool):
            raise TypeError("zero_mem_enabled must be bool")
        root = _safe_root(Path(self.capture_root))
        object.__setattr__(self, "capture_root", root)
        if self.hermes_home is not None:
            object.__setattr__(self, "hermes_home", Path(self.hermes_home).expanduser().resolve())
        if self.use_environment_identity:
            project = _resolve_identity(self.project_id, "HERMES_PROJECT_ID")
            profile = _resolve_identity(self.profile_id, "HERMES_PROFILE_ID")
        else:
            project = _resolve_identity(self.project_id, "__ZERO_MEM_DISABLED_PROJECT_ID")
            profile = _resolve_identity(self.profile_id, "__ZERO_MEM_DISABLED_PROFILE_ID")
        object.__setattr__(self, "project_id", project)
        object.__setattr__(self, "profile_id", profile)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "project_id": self.project_id,
            "profile_id": self.profile_id,
            "capture_root": str(self.capture_root),
            "hermes_home": str(self.hermes_home) if self.hermes_home else None,
            "use_environment_identity": self.use_environment_identity,
            "zero_mem_enabled": self.zero_mem_enabled,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


def event_class_for_hook(hook: str) -> str | None:
    return _EVENT_CLASSES.get(hook)


def registry_snapshot() -> dict[str, tuple[str, ...]]:
    return {key: tuple(value) for key, value in HOOK_REGISTRY.items()}


@dataclass
class BridgeMetrics:
    """Content-free aggregate metrics for later bridge callbacks."""

    counts: dict[tuple[str, str], int] = field(default_factory=dict)

    def record(self, hook: str, category: str) -> None:
        if hook not in HOOK_REGISTRY["verified_supported"] + HOOK_REGISTRY["conditional_fixture_required"] + HOOK_REGISTRY["deferred"]:
            raise ValueError("unknown hook")
        if not category or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for ch in category):
            raise ValueError("invalid metric category")
        key = (hook, category)
        self.counts[key] = self.counts.get(key, 0) + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "counts": [
                {"hook": hook, "category": category, "count": count}
                for (hook, category), count in sorted(self.counts.items())
            ]
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


__all__ = [
    "BridgeConfig",
    "BridgeMetrics",
    "CONDITIONAL_FIXTURE_REQUIRED",
    "DEFERRED_HOOKS",
    "HOOK_REGISTRY",
    "VERIFIED_SUPPORTED_HOOKS",
    "event_class_for_hook",
    "registry_snapshot",
]

# Increment 4.1 deliberately does not import Hermes or register hooks.
# Unknown objects are not stringified by this configuration layer.
# Metrics contain only hook/category/count triples.
# Identity resolution is explicit or approved environment-based only.
# No cwd, repository, prompt, Git, or Hermes-state inference occurs.
# The real home directory is rejected as a capture root.
# Temporary homes remain caller-provided and isolated.
# Later increments own mapping, redaction, and persistence calls.
# End of file.
