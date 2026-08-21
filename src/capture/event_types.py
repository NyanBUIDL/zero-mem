"""Stable M1 observation event contract.

This module is deliberately independent of Hermes runtime modules. It defines
only the normalized contract consumed by later capture/storage increments.
"""

from __future__ import annotations

from enum import Enum
from typing import Final


SCHEMA_VERSION: Final[int] = 1


class EventType(str, Enum):
    """Trace taxonomy values that M1 can represent."""

    USER_STATEMENT = "user_statement"
    ASSISTANT_CLAIM = "assistant_claim"
    TOOL_OBSERVATION = "tool_observation"
    SYSTEM_EVENT = "system_event"
    EXTERNAL_SOURCE = "external_source"
    INFERENCE = "inference"
    DECISION = "decision"
    VERIFIED_STATE = "verified_state"
    DERIVED_SUMMARY = "derived_summary"


class LifecycleStatus(str, Enum):
    RAW = "raw"
    OBSERVED = "observed"
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    CONFLICTED = "conflicted"
    ARCHIVED = "archived"
    DELETED = "deleted"


class VerificationStatus(str, Enum):
    NONE = "none"
    DIRECT_TOOL_OUTPUT = "direct_tool_output"
    USER_CONFIRMATION = "user_confirmation"
    DETERMINISTIC_VERIFICATION = "deterministic_verification"
    APPROVAL = "approval"


class Confidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class Sensitivity(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PRIVATE = "private"
    SECRET = "secret"


class Retention(str, Enum):
    TEMPORARY = "temporary"
    SESSION = "session"
    PERSISTENT = "persistent"
    NEVER_STORE = "never_store"


SUPPORTED_EVENT_CLASSES: Final[tuple[str, ...]] = (
    "session_lifecycle",
    "pre_tool_call",
    "post_tool_call",
    "llm_api_lifecycle",
    "subagent_lifecycle",
    "skill_lifecycle",
    "verified_task_or_kanban_lifecycle",
)

DEFERRED_EVENT_CLASSES: Final[tuple[str, ...]] = (
    "file_operations",
    "generic_task_transitions",
)

# The registry is immutable at the module boundary: callers receive tuples,
# not mutable lists that could silently alter the contract globally.
EVENT_CLASS_REGISTRY: Final[dict[str, tuple[str, ...]]] = {
    "supported": SUPPORTED_EVENT_CLASSES,
    "deferred": DEFERRED_EVENT_CLASSES,
}


def is_supported_event_class(event_class: str) -> bool:
    return event_class in SUPPORTED_EVENT_CLASSES


def is_deferred_event_class(event_class: str) -> bool:
    return event_class in DEFERRED_EVENT_CLASSES


__all__ = [
    "SCHEMA_VERSION",
    "EventType",
    "LifecycleStatus",
    "VerificationStatus",
    "Confidence",
    "Sensitivity",
    "Retention",
    "SUPPORTED_EVENT_CLASSES",
    "DEFERRED_EVENT_CLASSES",
    "EVENT_CLASS_REGISTRY",
    "is_supported_event_class",
    "is_deferred_event_class",
]
