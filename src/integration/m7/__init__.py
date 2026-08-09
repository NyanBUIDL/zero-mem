"""M7 — Controlled Injection + Master Zero-Mem Runtime Switch.

M7.2: deterministic, zero-LLM MEMORY-NEED ROUTER.

This package is incrementally built:
- M7.2 (this increment): deterministic memory-need router ONLY.
- M7.3+: authorized evidence eligibility + bounded evidence-set construction.
- M7.4+: Hermes controlled context-injection adapter/envelope.

M7.2 intentionally contains NO retrieval, NO authorization, NO injection,
NO SQLite/JSONL logic, NO LLM/network calls.
"""

from __future__ import annotations

from .contracts import (
    MemoryRoute,
    ReasonCode,
    RouterRequest,
    MemoryRouteDecision,
)
from .memory_router import route, route_from_text

__all__ = [
    "MemoryRoute",
    "ReasonCode",
    "RouterRequest",
    "MemoryRouteDecision",
    "route",
    "route_from_text",
]
