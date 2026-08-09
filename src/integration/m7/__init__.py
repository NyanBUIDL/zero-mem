"""M7 — Controlled Injection + Master Zero-Mem Runtime Switch.

M7.2: deterministic memory-need router (route classification only).
M7.3: authorized evidence eligibility + bounded EvidenceSet construction.
M7.4: Hermes controlled context-injection adapter/envelope (this increment).
       Registers a real ``pre_llm_call`` hook; runs M7.1→M7.2→M7.3; serializes
       the EvidenceSet as safe DATA-only context appended to the user message.
M7.5+: conflict / insufficient-evidence / prompt-injection hardening.

M7.3 intentionally contains NO retrieval logic of its own beyond mapping routes
to the verified M5 authorized-read surface, NO authorization logic (reused
from M5), NO SQLite/JSONL direct access, NO injection.
M7.4 performs NO new retrieval, NO reranking, NO lifecycle changes, NO writes,
NO LLM, NO network. It serializes the already-authorized EvidenceSet and
injects it as explicitly-labeled historical/contextual evidence DATA.
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
from .envelope import serialize_evidence_set
from .injection_adapter import InjectionAdapter, InjectionResult

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
    "serialize_evidence_set",
    "InjectionAdapter",
    "InjectionResult",
]
