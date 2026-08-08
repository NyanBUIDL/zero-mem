"""M4 project-memory projection package.

M4.1 defined the derived v7 schema (six tables, lifecycle CHECK, partial unique
indexes, NULL-safe keys). M4.2 implements the deterministic, idempotent write/
read projector for Project Charter + Requirement Registry. M4.3 adds the Decision
Log projector (supersession + conflict). M4.4 adds the Current Project State
reducer. M4.5 adds Verification Records + Project Artifact integration.

All projectors are deterministic and idempotent: replaying the same ordered
structured events into an equivalent empty v7 database yields the same rows.
They consume EXPLICIT typed operation envelopes; they never infer identity,
subjects, or verification from prose, timestamps, trace_id, embeddings, or LLM
output. They perform NO LLM calls and NO network calls.
"""

from __future__ import annotations

from .contracts import (
    LIFECYCLE_ENUM,
    M4Op,
    M4Domain,
    VERIFICATION_SUBJECT_TYPES,
    VERIFICATION_STATUS_ENUM,
    is_safe_reference,
    M4ProjectionError,
    MissingIdentityError,
    MissingRequiredFieldError,
    InvalidLifecycleError,
    InvalidTransitionError,
    ConflictError,
    PromotionBlockedError,
    CharterOp,
    RequirementOp,
    DecisionOp,
    StateOp,
    VerificationOp,
    ArtifactOp,
)
from .projector import (
    project_charter,
    project_requirement,
    project_decision,
    project_state,
    project_verification,
    project_artifact,
    classify_event_for_m4,
    CLASSIFY_CHARTER,
    CLASSIFY_REQUIREMENT,
    CLASSIFY_DECISION,
    CLASSIFY_STATE,
    CLASSIFY_VERIFICATION,
    CLASSIFY_PROJECT_ARTIFACT,
    CLASSIFY_SKIP,
)

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
    "project_charter",
    "project_requirement",
    "project_decision",
    "project_state",
    "project_verification",
    "project_artifact",
    "classify_event_for_m4",
    "CLASSIFY_CHARTER",
    "CLASSIFY_REQUIREMENT",
    "CLASSIFY_DECISION",
    "CLASSIFY_STATE",
    "CLASSIFY_VERIFICATION",
    "CLASSIFY_PROJECT_ARTIFACT",
    "CLASSIFY_SKIP",
]
