"""M5.1 — Profile/project/knowledge-space access policy (contracts + base rules).

This package is contracts-only for M5.1: typed ``AccessRequest`` / ``AllowedScope``
/ ``AccessDecision`` plus a deterministic ``evaluate`` implementing the base
precedence. It does NOT integrate with M3/M4 retrieval, does NOT implement
persistent grants, does NOT create schema v8, and does NOT write audit events.
"""

from .contracts import (
    READ, WRITE, Operation, ReasonCode,
    AccessRequest, AllowedScope, AccessDecision,
)
from .policy import evaluate

__all__ = [
    "READ", "WRITE", "Operation", "ReasonCode",
    "AccessRequest", "AllowedScope", "AccessDecision", "evaluate",
]
