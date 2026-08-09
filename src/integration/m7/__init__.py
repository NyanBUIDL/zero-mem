"""M7 — Controlled Injection + Master Zero-Mem Runtime Switch.

M7.2: deterministic memory-need router (route classification only).
M7.3: authorized evidence eligibility + bounded EvidenceSet construction (this
       increment). Retrieves via the verified M5 AuthorizedReadService; performs
       NO injection, NO writes, NO LLM, NO network.
M7.4+: Hermes controlled context-injection adapter/envelope.

M7.3 intentionally contains NO retrieval logic of its own beyond mapping routes to
the verified M5 authorized-read surface, NO authorization logic (reused from M5),
NO SQLite/JSONL direct access, NO injection.
"""

from __future__ import annotations

from .contracts import (
    MemoryRoute,
    ReasonCode,
    RouterRequest,
    MemoryRouteDecision,
    EvidenceRole,
    EvidenceItem,
    EvidenceSet,
)
from .memory_router import route, route_from_text
from .eligibility import is_eligible, EligibilityResult
from .budget import select_evidence, estimate_tokens, BudgetSelection
from .evidence_builder import build_evidence_set

__all__ = [
    "MemoryRoute",
    "ReasonCode",
    "RouterRequest",
    "MemoryRouteDecision",
    "EvidenceRole",
    "EvidenceItem",
    "EvidenceSet",
    "route",
    "route_from_text",
    "is_eligible",
    "EligibilityResult",
    "select_evidence",
    "estimate_tokens",
    "BudgetSelection",
    "build_evidence_set",
]
