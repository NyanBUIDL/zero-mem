"""M4.2 projector contracts: typed operation envelopes + sanitized errors.

This module defines the EXPLICIT, structured operation envelope that the M4.2
projector consumes. It does NOT infer charter/requirement data from prose, free
text, timestamps, trace_id, or semantic similarity, and it does NOT invent
event names. The projector only projects an explicitly-structured operation.

Authoritative rules (from the approved M4 plan / master spec §7.1, §9.2):
- lifecycle_status is the CLOSED enum only:
  raw/observed/candidate/confirmed/active/superseded/conflicted/archived/deleted
- domain `state` (proposed/accepted/satisfied/blocked/rejected/...) lives in a
  separate generic column, never in lifecycle_status.
- logical identity (charter_id / requirement_id) is explicit; trace_id is NEVER
  used as identity.
- supersession is explicit only (supersedes / replaced_by).
- an assistant_claim-derived operation may not auto-promote to `active`.
- secrets are never exposed in errors/diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


# Closed lifecycle enum (master spec §7.1). Authoritative.
LIFECYCLE_ENUM: tuple[str, ...] = (
    "raw", "observed", "candidate", "confirmed",
    "active", "superseded", "conflicted", "archived", "deleted",
)

# Allowed operation kinds for the typed envelope.
class M4Op(str, Enum):
    CREATE = "create"
    UPDATE = "update"          # new version of an existing charter/requirement
    SUPERSEDE = "supersede"    # explicit supersession of a prior identity
    TRANSITION = "transition"  # lifecycle/state change of an existing identity
    DELETE = "delete"          # logical deletion (Decision B)


class M4Domain(str, Enum):
    CHARTER = "charter"
    REQUIREMENT = "requirement"


# ---- Sanitized errors (no raw SQL / payload / secret leakage) ----------------


class M4ProjectionError(Exception):
    """Base class for M4 projector failures. Messages are sanitized; they never
    contain raw SQL text, payloads, secrets, or uncontrolled exception strings."""

    kind: str = "m4_projection_error"

    def __init__(self, message: str) -> None:
        # Never embed the raw underlying exception or payload text.
        sanitized = (message or "").replace("\n", " ").strip()
        if len(sanitized) > 240:
            sanitized = sanitized[:240] + "...(truncated)"
        super().__init__(f"{self.kind}: {sanitized}")


class MissingIdentityError(M4ProjectionError):
    kind = "missing_identity"


class MissingRequiredFieldError(M4ProjectionError):
    kind = "missing_required_field"


class InvalidLifecycleError(M4ProjectionError):
    kind = "invalid_lifecycle_status"


class InvalidTransitionError(M4ProjectionError):
    kind = "invalid_transition"


class ConflictError(M4ProjectionError):
    kind = "conflict_preserved"


class PromotionBlockedError(M4ProjectionError):
    kind = "promotion_blocked"


# ---- Typed operation envelopes ----------------------------------------------


@dataclass
class CharterOp:
    """Explicit structured Charter operation. The projector consumes this verbatim.

    op: one of M4Op. create -> new charter (idempotent no-op if identical exists).
    update/supersede -> new version; prior version preserved (marked superseded).
    transition -> lifecycle/state change of an existing charter.
    delete -> logical deletion (lifecycle_status='deleted', history preserved).
    """

    op: str
    charter_id: str
    project_id: str
    version: Optional[int] = None
    name: Optional[str] = None
    goal: Optional[str] = None
    scope: Optional[str] = None
    non_goals: Optional[str] = None
    constraints: Optional[str] = None
    architecture_principles: Optional[str] = None
    success_criteria: Optional[str] = None
    lifecycle_status: str = "candidate"
    state: Optional[str] = None
    supersedes: Optional[str] = None
    verification_ref: Optional[str] = None
    # provenance
    source_event_id: Optional[str] = None
    trace_id: Optional[str] = None
    session_id: Optional[str] = None
    profile_id: Optional[str] = None
    created_at: Optional[str] = None
    derived_from_event_type: Optional[str] = None  # e.g. 'assistant_claim' (promotion guard)

    def validate(self) -> "CharterOp":
        if self.op not in {o.value for o in M4Op}:
            raise InvalidTransitionError(f"unknown op: {self.op}")
        if not (self.charter_id and self.charter_id.strip()):
            raise MissingIdentityError("charter_id required and explicit")
        if not (self.project_id and self.project_id.strip()):
            raise MissingRequiredFieldError("project_id required")
        if self.lifecycle_status not in LIFECYCLE_ENUM:
            raise InvalidLifecycleError(
                f"lifecycle_status must be one of the closed enum; got {self.lifecycle_status}"
            )
        # Promotion guard: an assistant_claim-derived op must not set active.
        if self.derived_from_event_type == "assistant_claim" and self.lifecycle_status == "active":
            raise PromotionBlockedError(
                "assistant_claim may not auto-promote a charter to active"
            )
        if self.op == M4Op.DELETE.value and self.lifecycle_status != "deleted":
            # normalize: a delete op targets deleted lifecycle
            self.lifecycle_status = "deleted"
        return self


@dataclass
class RequirementOp:
    """Explicit structured Requirement operation. The projector consumes this verbatim.

    requirement_id is explicit and stable. trace_id is NEVER used as identity.
    state is the generic domain status; lifecycle_status is the closed enum.
    supersedes / replaced_by carry explicit supersession.
    """

    op: str
    requirement_id: str
    project_id: str
    statement: Optional[str] = None
    lifecycle_status: str = "candidate"
    state: Optional[str] = None
    verification_status: str = "none"
    supersedes: Optional[str] = None
    replaced_by: Optional[str] = None
    linked_decision_ids: Optional[str] = None
    linked_artifact_ids: Optional[str] = None
    linked_verification_ids: Optional[str] = None
    # provenance
    source_event_id: Optional[str] = None
    trace_id: Optional[str] = None
    session_id: Optional[str] = None
    profile_id: Optional[str] = None
    created_at: Optional[str] = None
    derived_from_event_type: Optional[str] = None

    def validate(self) -> "RequirementOp":
        if self.op not in {o.value for o in M4Op}:
            raise InvalidTransitionError(f"unknown op: {self.op}")
        if not (self.requirement_id and self.requirement_id.strip()):
            raise MissingIdentityError("requirement_id required and explicit")
        if not (self.project_id and self.project_id.strip()):
            raise MissingRequiredFieldError("project_id required")
        if self.lifecycle_status not in LIFECYCLE_ENUM:
            raise InvalidLifecycleError(
                f"lifecycle_status must be one of the closed enum; got {self.lifecycle_status}"
            )
        # Promotion guard: an assistant_claim-derived op must not set active.
        if self.derived_from_event_type == "assistant_claim" and self.lifecycle_status == "active":
            raise PromotionBlockedError(
                "assistant_claim may not auto-promote a requirement to active"
            )
        if self.op == M4Op.DELETE.value and self.lifecycle_status != "deleted":
            self.lifecycle_status = "deleted"
        return self


__all__ = [
    "LIFECYCLE_ENUM",
    "M4Op",
    "M4Domain",
    "M4ProjectionError",
    "MissingIdentityError",
    "MissingRequiredFieldError",
    "InvalidLifecycleError",
    "InvalidTransitionError",
    "ConflictError",
    "PromotionBlockedError",
    "CharterOp",
    "RequirementOp",
]
