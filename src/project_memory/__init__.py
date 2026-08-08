"""M4 project-memory projection package.

M4.1 defined the derived v7 schema (six tables, lifecycle CHECK, partial unique
indexes, NULL-safe keys). M4.2 implements the deterministic, idempotent write/
read projector for Project Charter + Requirement Registry. M4.3 adds the Decision
Log projector (supersession + conflict). M4.4 adds the Current Project State
reducer. M4.5 adds Verification Records + Project Artifact integration. M4.6
adds TRUE READ-ONLY query APIs over the v7 derived tables, composed with the M3
read-only retrieval layer.

All projectors are deterministic and idempotent: replaying the same ordered
structured events into an equivalent empty v7 database yields the same rows.
They consume EXPLICIT typed operation envelopes; they never infer identity,
subjects, or verification from prose, timestamps, trace_id, embeddings, or LLM
output. They perform NO LLM calls and NO network calls.

M4.6 read APIs are strictly read-only: they open SQLite through the M3
``ReadonlyStore`` (mode=ro + query_only), never invoke projectors or migrations,
and never mutate store/JSONL state.
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
from .reader import (  # noqa: F401
    INVALID_PROJECT_ID,
    INVALID_SUBJECT_TYPE,
    CharterView,
    RequirementView,
    DecisionView,
    ProjectStateView,
    VerificationView,
    ProjectArtifactView,
    ProjectMemoryResult,
    get_project_charter,
    list_project_charters,
    get_requirement,
    list_requirements,
    get_decision,
    list_decisions,
    get_active_decision,
    get_current_project_state,
    get_state_value,
    get_verification,
    list_verifications,
    list_project_artifacts,
    is_query_only,
    open_readonly,
    ReadonlyStore,
)
from .rebuild import (  # noqa: F401
    M4_TABLES,
    event_to_op,
    rebuild_project_memory,
    rebuild_all_project_memory,
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
    # M4.6 read-only APIs
    "INVALID_PROJECT_ID",
    "INVALID_SUBJECT_TYPE",
    "CharterView",
    "RequirementView",
    "DecisionView",
    "ProjectStateView",
    "VerificationView",
    "ProjectArtifactView",
    "ProjectMemoryResult",
    "get_project_charter",
    "list_project_charters",
    "get_requirement",
    "list_requirements",
    "get_decision",
    "list_decisions",
    "get_active_decision",
    "get_current_project_state",
    "get_state_value",
    "get_verification",
    "list_verifications",
    "list_project_artifacts",
    "is_query_only",
    "open_readonly",
    "ReadonlyStore",
    # M4.7 rebuild
    "M4_TABLES",
    "event_to_op",
    "rebuild_project_memory",
    "rebuild_all_project_memory",
]
