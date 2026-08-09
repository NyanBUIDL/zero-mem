"""M7.2 contracts — typed, immutable router input/output.

Mirrors the repository's str-based Enum + frozen-dataclass contract conventions
(see src/integration/m6/contracts.py). The router input is intentionally NARROWER
than an authorization request (M5 AccessRequest): it carries only what is needed
to classify a memory need, never identity resolution or grant material.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import FrozenSet, Optional, Tuple

from src.integration.zero_mem_runtime import get_runtime


class MemoryRoute(str, enum.Enum):
    """Supported memory-need routes. Single canonical enum; no free-form strings."""

    NO_MEMORY = "no_memory"
    SESSION = "session_memory"
    PROJECT = "project_memory"
    USER = "user_memory"
    RESEARCH = "research_memory"
    GLOBAL = "global_memory"
    EXTERNAL_CURRENT = "external_current"

    @property
    def requires_memory(self) -> bool:
        return self is not MemoryRoute.NO_MEMORY


class ReasonCode(str, enum.Enum):
    """Stable machine-readable reason codes (never raw prose as sole contract)."""

    GENERIC_STANDALONE = "GENERIC_STANDALONE"
    EXPLICIT_SESSION_REFERENCE = "EXPLICIT_SESSION_REFERENCE"
    EXPLICIT_PROJECT_CONTEXT = "EXPLICIT_PROJECT_CONTEXT"
    EXPLICIT_USER_PREFERENCE = "EXPLICIT_USER_PREFERENCE"
    EXPLICIT_RESEARCH_SOURCE = "EXPLICIT_RESEARCH_SOURCE"
    EXPLICIT_MULTI_SCOPE = "EXPLICIT_MULTI_SCOPE"
    EXTERNAL_FRESHNESS_REQUIRED = "EXTERNAL_FRESHNESS_REQUIRED"
    EXPLICIT_ROUTE_HINT = "EXPLICIT_ROUTE_HINT"
    INSUFFICIENT_ROUTE_CONTEXT = "INSUFFICIENT_ROUTE_CONTEXT"


@dataclass(frozen=True)
class RouterRequest:
    """Narrow, typed router input. NOT an authorization request.

    The router must NOT infer identity. Ambient metadata (project_id,
    session_id, requesting_profile_id, target_profile_ids, knowledge_space_ids)
    is information only; presence alone does NOT force a memory route. Explicit
    intent flags and/or a trusted route hint express the caller's structured
    determination of memory need.
    """

    normalized_text: Optional[str] = None
    project_id: Optional[str] = None
    session_id: Optional[str] = None
    requesting_profile_id: Optional[str] = None
    target_profile_ids: Tuple[str, ...] = ()
    knowledge_space_ids: Tuple[str, ...] = ()
    # Explicit structured intent flags (caller-determined, trusted).
    explicit_project_intent: bool = False
    explicit_session_intent: bool = False
    explicit_research_intent: bool = False
    explicit_user_intent: bool = False
    explicit_global_intent: bool = False
    explicit_freshness_intent: bool = False
    # Trusted explicit route hint from the typed caller contract only.
    trusted_route_hint: Optional[MemoryRoute] = None

    def __post_init__(self) -> None:
        # Normalize tuples to avoid accidental mutable state.
        if not isinstance(self.target_profile_ids, tuple):
            object.__setattr__(self, "target_profile_ids", tuple(self.target_profile_ids))
        if not isinstance(self.knowledge_space_ids, tuple):
            object.__setattr__(self, "knowledge_space_ids", tuple(self.knowledge_space_ids))


@dataclass(frozen=True)
class MemoryRouteDecision:
    """Immutable route decision. Contains NO retrieved content, NO AccessDecision,
    NO grants, NO evidence. Transient runtime artifact (not persisted in M7.2)."""

    route: MemoryRoute
    memory_needed: bool
    reason_code: ReasonCode
    scope_hints: FrozenSet[str] = field(default_factory=frozenset)
    external_current: bool = False
    insufficient_route_context: bool = False

    def requires_memory(self) -> bool:
        return self.route.requires_memory

    def to_dict(self) -> dict:
        return {
            "route": self.route.value,
            "memory_needed": self.memory_needed,
            "reason_code": self.reason_code.value,
            "scope_hints": sorted(self.scope_hints),
            "external_current": self.external_current,
            "insufficient_route_context": self.insufficient_route_context,
        }


def is_zero_mem_zero_mem_runtime_enabled() -> bool:
    """Consult the shared M7.1 runtime authority (never re-parse env)."""
    return get_runtime().is_enabled()
