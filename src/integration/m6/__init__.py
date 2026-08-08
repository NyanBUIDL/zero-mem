"""M6 — Hermes / MCP read-only integration (READ direction sidecar adapter).

M6.1 deliverable: integration contracts + read-only transport/tool surface only.

This package is the READ direction of the External Zero-Mem sidecar. It is
deliberately disjoint from ``src.integration.capture_*`` (the M1 WRITE/capture
direction). M6.1 establishes:

* allowlisted typed tool registry (READ-only tools only);
* strict typed request contracts (no inferred identity, no caller authority);
* a single sanitized response envelope;
* a transport-independent dispatcher contract;
* a thin MCP/transport wrapper foundation;
* strict forbidden-field rejection (no self-authorization);
* proof of READ-ONLY by construction (no writable import path is reachable).

M6.1 does NOT wire M3/M4 execution (that is M6.2/M6.3). The dispatcher only
validates, routes to an allowlisted tool, and — when no READ handler is
registered yet — returns a deterministic ``CAPABILITY_UNAVAILABLE`` envelope.
No SQLite, JSONL, projector, migration, grant, or WRITE path is imported or
invoked here.
"""

from .contracts import (
    M6Request,
    M6Response,
    Operation,
    ResourceType,
    ResponseStatus,
    validate_request,
)
from .errors import M6Error, M6ErrorCode
from .tools import TOOL_REGISTRY, ToolSpec, get_tool, list_tool_names
from .dispatcher import Dispatcher, dispatch, register

__all__ = [
    "M6Request",
    "M6Response",
    "Operation",
    "ResourceType",
    "ResponseStatus",
    "validate_request",
    "M6Error",
    "M6ErrorCode",
    "TOOL_REGISTRY",
    "ToolSpec",
    "get_tool",
    "list_tool_names",
    "Dispatcher",
    "dispatch",
    "register",
]
