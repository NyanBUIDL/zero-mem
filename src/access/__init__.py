"""M5.1/M5.2 — Profile/project/knowledge-space access policy.

Contracts + base rules (M5.1) and the authorized-read facade over M3/M4 (M5.2).
No grants, no schema v8, no audit persistence, no WRITE integration.
"""

from .contracts import (
    READ, WRITE, Operation, ReasonCode,
    AccessRequest, AllowedScope, AccessDecision,
)
from .policy import evaluate
from .authorized_read import AuthorizedReadService, AuthorizedResult

__all__ = [
    "READ", "WRITE", "Operation", "ReasonCode",
    "AccessRequest", "AllowedScope", "AccessDecision", "evaluate",
    "AuthorizedReadService", "AuthorizedResult",
]
