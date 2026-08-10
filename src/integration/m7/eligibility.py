"""M7.3 — deterministic evidence eligibility gates.

Pure functions over normalized item attributes. No LLM, no DB, no network.
Evaluates lifecycle, sensitivity ceiling, provenance completeness, verification,
memory type, and route relevance. Authorization is assumed already performed by
the M5 AuthorizedReadService; eligibility is a SECOND, independent gate that never
promotes unauthorized content and fails closed on missing provenance/sensitivity.

M4 authorized items carry no `sensitivity` field and use `effective_at`/`timestamp`
instead of `created_at`; they are already governed by M5, so the sensitivity gate
only fails-closed for M3 events (which DO carry sensitivity).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from src.capture.event_types import Sensitivity

# Lifecycle that must never become eligible evidence (current truth).
_INELIGIBLE_LIFECYCLE = {"deleted"}
# Lifecycle that is not current truth and must not be PRIMARY.
_NON_CURRENT_LIFECYCLE = {"superseded", "archived"}
# Lifecycle that may only be SUPPORTING (not elevated to verified fact).
_SUBORDINATE_LIFECYCLE = {"raw", "observed", "candidate"}

# Memory types that must not be silently promoted to verified fact.
_NON_PROMOTABLE_TYPE = {"assistant_claim", "inference", "user_statement"}

# Canonical sensitivity ordering, derived from the M1 contract (src/capture/
# event_types.py::Sensitivity). This is the ONLY sensitivity vocabulary in the
# system: public < internal < private < secret. Master spec 14.1 defines the
# default policy per class (public: searchable; internal: permitted profile only;
# private: access-policy gated; secret: never persisted, redact/reject at the
# capture boundary).
_SENSITIVITY_ORDER = {
    Sensitivity.PUBLIC.value: 0,
    Sensitivity.INTERNAL.value: 1,
    Sensitivity.PRIVATE.value: 2,
    Sensitivity.SECRET.value: 3,
}
# Unknown/malformed values rank above every real class so they always fail closed.
_UNKNOWN_SENSITIVITY_RANK = 99

# Default ceiling: everything except `secret` may be eligible once authorized.
# `secret` is never persisted (spec 14.2) and is additionally rejected here as
# defense in depth, regardless of the configured ceiling.
DEFAULT_SENSITIVITY_CEILING = Sensitivity.PRIVATE.value


def _attr(item: Any, *names: str, default: Any = None) -> Any:
    for n in names:
        if hasattr(item, n):
            return getattr(item, n)
    return default


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reason: str
    as_primary: bool = False

    @property
    def as_supporting(self) -> bool:
        return self.eligible and not self.as_primary


def _is_m3_event(item: Any) -> bool:
    """M3 views expose event_id/sensitivity; M4 views do not. Used to decide
    fail-closed sensitivity policy (M4 items are already authorized by M5)."""
    return hasattr(item, "event_id")


def _sensitivity_rank(level: Optional[str]) -> int:
    """Rank a canonical sensitivity value. Unknown/malformed => fail closed."""
    if not isinstance(level, str):
        return _UNKNOWN_SENSITIVITY_RANK  # None/non-string => fail closed
    return _SENSITIVITY_ORDER.get(level.strip().lower(), _UNKNOWN_SENSITIVITY_RANK)


def _exceeds_ceiling(sensitivity: Optional[str], ceiling: Optional[str]) -> bool:
    """True when `sensitivity` must be excluded for the given ceiling.

    Fails closed in every ambiguous direction:
      * unknown/malformed sensitivity is always excluded;
      * unknown/malformed ceiling excludes everything (never widens access);
      * `secret` is excluded unconditionally (spec 14.1/14.2: never persisted,
        so it must never surface as evidence even if a ceiling says otherwise).
    """
    item_rank = _sensitivity_rank(sensitivity)
    if item_rank == _UNKNOWN_SENSITIVITY_RANK:
        return True
    if item_rank >= _SENSITIVITY_ORDER[Sensitivity.SECRET.value]:
        return True
    ceiling_rank = _sensitivity_rank(ceiling)
    if ceiling_rank == _UNKNOWN_SENSITIVITY_RANK:
        return True
    return item_rank > ceiling_rank


def is_eligible(
    item: Any,
    route: str,
    *,
    sensitivity_ceiling: str = DEFAULT_SENSITIVITY_CEILING,
    allow_non_current_as_supporting: bool = True,
    resource_type: Optional[str] = None,
) -> EligibilityResult:
    """Deterministic eligibility decision for one authorized candidate.

    Returns (eligible, reason, as_primary). Fails closed on unknown sensitivity
    (M3 events) or incomplete provenance. M4 authorized items carry no sensitivity
    field and are governed by M5; they pass the sensitivity gate once authorized.
    """
    lifecycle = (_attr(item, "lifecycle_status", "lifecycle") or "active").lower()
    sensitivity = _attr(item, "sensitivity")
    evidence_id = _attr(item, "event_id", "requirement_id", "decision_id",
                        "verification_id", "artifact_id", "charter_id", "id")
    created_at = _attr(item, "created_at", "effective_at", "timestamp")
    source_event_id = _attr(item, "source_event_id")
    memory_type = _attr(item, "event_type", "memory_type") or resource_type

    # 1. lifecycle hard exclusions
    if lifecycle in _INELIGIBLE_LIFECYCLE:
        return EligibilityResult(False, f"lifecycle_excluded:{lifecycle}")
    # 2. sensitivity ceiling (authorization AND sensitivity both required for M3).
    #    M4 authorized items have no sensitivity field; M5 already governs access.
    if _is_m3_event(item) and _exceeds_ceiling(sensitivity, sensitivity_ceiling):
        return EligibilityResult(False, "sensitivity_ceiling_exceeded")
    # 3. provenance completeness (fail closed if minimum provenance missing)
    if not evidence_id or not (created_at or source_event_id):
        return EligibilityResult(False, "provenance_incomplete")

    # 4. role classification (deterministic)
    verification = (_attr(item, "verification_status", "verification") or "").lower()
    is_verified = verification in ("verified", "confirmed")
    is_active = lifecycle == "active"
    primary = (
        (is_active and is_verified)
        or memory_type in ("decision", "verified_state", "tool_observation")
        or lifecycle == "confirmed"
    )
    # Non-current lifecycle (superseded/archived) cannot be current PRIMARY truth.
    if lifecycle in _NON_CURRENT_LIFECYCLE:
        if not allow_non_current_as_supporting:
            return EligibilityResult(False, f"lifecycle_not_current:{lifecycle}")
        primary = False
    # Subordinate lifecycle/raw types are supporting only.
    if lifecycle in _SUBORDINATE_LIFECYCLE:
        primary = False
    # Non-promotable memory types (assistant_claim/inference/user_statement) are
    # supporting only; they must not become high-confidence primary evidence.
    if memory_type in _NON_PROMOTABLE_TYPE:
        primary = False

    return EligibilityResult(True, "eligible", as_primary=primary)
