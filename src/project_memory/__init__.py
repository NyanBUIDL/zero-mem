"""M4 project-memory projection package.

M4.1 defined the derived v7 schema (six tables, lifecycle CHECK, partial unique
indexes, NULL-safe keys). M4.2 implements the deterministic, idempotent write/
project path for the Project Charter and Requirement Registry domains only.

The projector is a SEPARATE write path from M3 TRUE READ-ONLY retrieval
(open_readonly + PRAGMA query_only=ON). It never reads for retrieval and never
modifies the read-only guarantees. It consumes explicit typed operation
envelopes (see contracts.py); it does not infer charter/requirement data from
prose, timestamps, trace_id, or semantic similarity, and it does not invent
event names.
"""

from .contracts import (
    LIFECYCLE_ENUM,
    M4Op,
    M4Domain,
    M4ProjectionError,
    MissingIdentityError,
    MissingRequiredFieldError,
    InvalidLifecycleError,
    InvalidTransitionError,
    ConflictError,
    PromotionBlockedError,
    CharterOp,
    RequirementOp,
)
from .projector import (
    project_charter,
    project_requirement,
    classify_event_for_m4,
    CLASSIFY_CHARTER,
    CLASSIFY_REQUIREMENT,
    CLASSIFY_SKIP,
)

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
    "project_charter",
    "project_requirement",
    "classify_event_for_m4",
    "CLASSIFY_CHARTER",
    "CLASSIFY_REQUIREMENT",
    "CLASSIFY_SKIP",
]
