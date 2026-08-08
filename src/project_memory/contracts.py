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
    DECISION = "decision"
    STATE = "state"
    VERIFICATION = "verification"
    ARTIFACT = "artifact"


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


@dataclass
class DecisionOp:
    """Explicit structured Decision operation. The projector consumes this verbatim.

    decision_id is the explicit stable record identity. trace_id is NEVER used as
    identity. decision_key is the explicit logical decision domain used for active
    uniqueness; it is NULL when absent (multiple NULL-key decisions coexist and do
    not falsely collide). state is the generic domain status (proposed/accepted/
    rejected/...); lifecycle_status is the closed enum. supersedes_id / replaced_by
    carry explicit supersession. The projector never infers identity from prose,
    timestamps, trace_id, embeddings, or LLM output.
    """

    op: str
    decision_id: str
    project_id: str
    scope: Optional[str] = None
    decision_key: Optional[str] = None
    statement: Optional[str] = None
    rationale_ref: Optional[str] = None
    alternatives: Optional[str] = None
    lifecycle_status: str = "candidate"
    state: Optional[str] = None
    supersedes_id: Optional[str] = None
    replaced_by: Optional[str] = None
    effective_at: Optional[str] = None
    linked_requirement_ids: Optional[str] = None
    linked_artifact_ids: Optional[str] = None
    linked_verification_ids: Optional[str] = None
    # provenance
    source_event_id: Optional[str] = None
    trace_id: Optional[str] = None
    session_id: Optional[str] = None
    profile_id: Optional[str] = None
    created_at: Optional[str] = None
    derived_from_event_type: Optional[str] = None

    def validate(self) -> "DecisionOp":
        if self.op not in {o.value for o in M4Op}:
            raise InvalidTransitionError(f"unknown op: {self.op}")
        if not (self.decision_id and self.decision_id.strip()):
            raise MissingIdentityError("decision_id required and explicit")
        if not (self.project_id and self.project_id.strip()):
            raise MissingRequiredFieldError("project_id required")
        if self.lifecycle_status not in LIFECYCLE_ENUM:
            raise InvalidLifecycleError(
                f"lifecycle_status must be one of the closed enum; got {self.lifecycle_status}"
            )
        # Promotion guard: an assistant_claim-derived op must not set active.
        if self.derived_from_event_type == "assistant_claim" and self.lifecycle_status == "active":
            raise PromotionBlockedError(
                "assistant_claim may not auto-promote a decision to active"
            )
        # Self-supersession is invalid (would create a cyclic/self link).
        if self.op == M4Op.SUPERSEDE.value and self.supersedes_id == self.decision_id:
            raise InvalidTransitionError("self-supersession rejected")
        if self.op == M4Op.DELETE.value and self.lifecycle_status != "deleted":
            self.lifecycle_status = "deleted"
        return self


@dataclass
class StateOp:
    """Explicit structured Current Project State operation. The projector consumes this verbatim.

    state_key is the explicit logical slot; it is NULL when absent (record
    preserved, no uniqueness, surfaced as missing-key). scope defaults to
    'project:<project_id>' only when state_key is present. state_value /
    state_ref are sanitized references, not free-text blobs. lifecycle_status is
    the closed enum; 'active' marks the current value. Active selected by
    lifecycle_status, never by timestamp. trace_id is NEVER used as state_key.
    """

    op: str
    project_id: str
    state_key: Optional[str] = None
    scope: Optional[str] = None
    state_value: Optional[str] = None
    state_ref: Optional[str] = None
    lifecycle_status: str = "active"
    verification_status: str = "none"
    effective_at: Optional[str] = None
    supersedes: Optional[str] = None
    source_event_id: Optional[str] = None
    trace_id: Optional[str] = None
    session_id: Optional[str] = None
    profile_id: Optional[str] = None
    created_at: Optional[str] = None
    derived_from_event_type: Optional[str] = None

    def validate(self) -> "StateOp":
        if self.op not in {o.value for o in M4Op}:
            raise InvalidTransitionError(f"unknown op: {self.op}")
        if not (self.project_id and self.project_id.strip()):
            raise MissingRequiredFieldError("project_id required")
        if self.state_key is not None and not self.state_key.strip():
            # treat empty key as absent (NULL)
            self.state_key = None
        if self.state_key is None and self.op == M4Op.SUPERSEDE.value:
            # supersession requires an explicit logical key to link prior state
            raise MissingIdentityError("state supersession requires an explicit state_key")
        if self.lifecycle_status not in LIFECYCLE_ENUM:
            raise InvalidLifecycleError(
                f"lifecycle_status must be one of the closed enum; got {self.lifecycle_status}"
            )
        # Promotion guard: an assistant_claim-derived op must not set active.
        if self.derived_from_event_type == "assistant_claim" and self.lifecycle_status == "active":
            raise PromotionBlockedError(
                "assistant_claim may not auto-promote project state to active"
            )
        # Scope default: project:<project_id> when a state_key is present.
        if self.scope is None and self.state_key is not None:
            self.scope = f"project:{self.project_id}"
        if self.op == M4Op.DELETE.value and self.lifecycle_status != "deleted":
            self.lifecycle_status = "deleted"
        return self


# Verification / project-artifact constants (M4.5) ------------------------------
#
# subject_type vocabulary is the CLOSED, approved set from the corrected M4 plan
# (line 216): requirement | decision | state | artifact | task | implementation |
# milestone. The master spec draft mentioned `project_state`, but the corrected
# plan uses `state`; the plan is authoritative, so `state` is accepted and
# `project_state` is rejected (not in vocabulary). M4.5 must not manufacture new
# subject types.
VERIFICATION_SUBJECT_TYPES: tuple[str, ...] = (
    "requirement", "decision", "state", "artifact",
    "task", "implementation", "milestone",
)

# Reuse the approved verification-status model (src/capture/event_types.
# VerificationStatus). M4.5 introduces NO new verification enum. No `verified` /
# `unverified` / `disputed` / `conflict` values exist in the approved model;
# contradictory verifications are preserved as distinct rows with their explicit
# status (never auto-marked `conflict`).
VERIFICATION_STATUS_ENUM: tuple[str, ...] = (
    "none", "direct_tool_output", "user_confirmation",
    "deterministic_verification", "approval",
)

# Patterns that indicate an UNRESTRICTED / unsafe reference. M4.5 stores only
# safe references (e.g. relative "reports/x.md"), never raw command output,
# stack traces, arbitrary absolute paths, or secret-bearing payloads.
_UNSAFE_REF_MARKERS = (
    "/home/", "/tmp/", "/var/", "C:\\Users", "c:/users",
    "file://", "Traceback", "stack trace", "traceback",
)


def is_safe_reference(value: Optional[str]) -> bool:
    """Return True iff value is safe to store as a reference.

    A value is UNSAFE if it is None (allowed -> returns True, meaning "no ref"),
    empty, or contains unrestricted-path / secret-bearing / raw-output markers.
    Multi-line blobs and absolute/relative-traversal paths are rejected (raw
    transcripts and local filesystem pointers are not references).
    """
    if value is None:
        return True
    s = value.strip()
    if not s:
        return True
    if "\n" in s or "\r" in s:
        # raw multi-line output (command transcript / stack trace) is not a ref
        return False
    low = s.lower()
    if s.startswith("/") or ".." in s.split("/") or ".." in s.split("\\"):
        # absolute path or parent-traversal is never a safe reference
        return False
    return not any(marker in low for marker in _UNSAFE_REF_MARKERS)


@dataclass
class VerificationOp:
    """Explicit structured Verification Record operation. The projector consumes
    this verbatim.

    verification_id is the explicit stable record identity; trace_id is NEVER
    used as identity. subject_type is the approved closed vocabulary; subject_id
    is explicit. verification_status reuses the approved VerificationStatus model
    (separate from lifecycle_status, which does NOT exist on this table). The
    projector does NOT auto-promote an unrelated claim/subject: inserting a
    verification records only the verification relationship + status as the
    canonical evidence states. It never mutates the referenced subject.
    """

    op: str
    verification_id: str
    project_id: str
    subject_type: Optional[str] = None
    subject_id: Optional[str] = None
    method: Optional[str] = None
    command_ref: Optional[str] = None
    observed_result: Optional[str] = None
    tested_commit: Optional[str] = None
    source_event_id: Optional[str] = None
    timestamp: Optional[str] = None
    verification_status: str = "none"
    artifact_references: Optional[str] = None
    # provenance
    trace_id: Optional[str] = None
    session_id: Optional[str] = None
    profile_id: Optional[str] = None
    created_at: Optional[str] = None
    derived_from_event_type: Optional[str] = None

    def validate(self) -> "VerificationOp":
        if self.op not in {o.value for o in M4Op}:
            raise InvalidTransitionError(f"unknown op: {self.op}")
        if not (self.verification_id and self.verification_id.strip()):
            raise MissingIdentityError("verification_id required and explicit; trace_id is not an identity")
        if not (self.project_id and self.project_id.strip()):
            raise MissingRequiredFieldError("project_id required")
        if self.subject_type is not None and self.subject_type not in VERIFICATION_SUBJECT_TYPES:
            raise MissingRequiredFieldError(
                f"subject_type must be one of {VERIFICATION_SUBJECT_TYPES}; got {self.subject_type}"
            )
        if self.verification_status not in VERIFICATION_STATUS_ENUM:
            raise MissingRequiredFieldError(
                f"verification_status must be one of {VERIFICATION_STATUS_ENUM}; got {self.verification_status}"
            )
        # Safe references only: command_ref / observed_result / artifact_references
        # must be sanitized references, never raw output, absolute paths, or secrets.
        for field_name in ("command_ref", "observed_result", "artifact_references"):
            val = getattr(self, field_name)
            if val is not None and not is_safe_reference(val):
                raise MissingRequiredFieldError(
                    f"{field_name} is not a safe reference (raw output / absolute path / secret rejected)"
                )
        # Verification does NOT auto-promote a subject; derived_from_event_type is
        # provenance only and must not change behavior here. No promotion guard
        # needed because verification_status is separate from lifecycle_status.
        return self


@dataclass
class ArtifactOp:
    """Explicit structured Project Artifact linkage operation. The projector
    consumes this verbatim.

    artifact_id is the explicit stable identity and MUST already exist in the M2
    zm_artifacts substrate (FK). M4.5 does NOT create a fake M2 artifact and does
    NOT duplicate artifact content. safe_reference is the only stored pointer and
    must be a safe (relative) reference. linked_requirement_ids / linked_decision_ids
    / linked_state_keys are explicit reference columns only (comma/colon-separated,
    never inferred from filenames/content/trace_id).
    """

    op: str
    artifact_id: str
    project_id: str
    artifact_type: Optional[str] = None
    version: Optional[str] = None
    safe_reference: Optional[str] = None
    source_event_id: Optional[str] = None
    verification_status: str = "none"
    linked_requirement_ids: Optional[str] = None
    linked_decision_ids: Optional[str] = None
    linked_state_keys: Optional[str] = None
    # provenance
    trace_id: Optional[str] = None
    session_id: Optional[str] = None
    profile_id: Optional[str] = None
    created_at: Optional[str] = None
    derived_from_event_type: Optional[str] = None

    def validate(self) -> "ArtifactOp":
        if self.op not in {o.value for o in M4Op}:
            raise InvalidTransitionError(f"unknown op: {self.op}")
        if not (self.artifact_id and self.artifact_id.strip()):
            raise MissingIdentityError("artifact_id required and explicit; filenames/trace_id are not identity")
        if not (self.project_id and self.project_id.strip()):
            raise MissingRequiredFieldError("project_id required")
        if self.verification_status not in VERIFICATION_STATUS_ENUM:
            raise MissingRequiredFieldError(
                f"verification_status must be one of {VERIFICATION_STATUS_ENUM}; got {self.verification_status}"
            )
        if self.safe_reference is not None and not is_safe_reference(self.safe_reference):
            raise MissingRequiredFieldError(
                "safe_reference is not a safe reference (absolute path / traversal / secret rejected)"
            )
        return self


__all__ = [
    "LIFECYCLE_ENUM",
    "M4Op",
    "M4Domain",
    "VERIFICATION_SUBJECT_TYPES",
    "VERIFICATION_STATUS_ENUM",
    "is_safe_reference",
    "M4ProjectionError",
    "MissingIdentityError",
    "MissingRequiredFieldError",
    "InvalidLifecycleError",
    "InvalidTransitionError",
    "ConflictError",
    "PromotionBlockedError",
    "CharterOp",
    "RequirementOp",
    "DecisionOp",
    "StateOp",
    "VerificationOp",
    "ArtifactOp",
]
