"""M6 — Hermes / MCP read-only integration (READ direction sidecar adapter).

M6.1 + M6.2: integration contracts, read-only transport/tool surface, and the
approved M3-oriented M6 read tools wired through the verified M5
AuthorizedReadService.

This package is the READ direction of the External Zero-Mem sidecar, disjoint
from ``src.integration.capture_*`` (the M1 WRITE/capture direction). M6.2 wires
only: memory_query, memory_search, memory_get_event, memory_get_related. M4
project_* tools remain unwired (M6.3) and return CAPABILITY_UNAVAILABLE.

READ-ONLY by construction: no import of GrantAdminService / AuthorizedWriteService
/ grant_events / migrations / ingest; no SQLite/JSONL/projector/canonical-writer
path is invoked for mutation. 0 LLM + 0 external network.
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
from .runtime import M6Runtime, configure as _configure_runtime
from . import handlers

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
    "M6Runtime",
    "configure",
    "handlers",
]


def configure(store_path) -> M6Runtime:
    """Configure the M6 runtime (derived SQLite path) and register M3 handlers.

    Must be called once at startup with a project-local/integration store path.
    No hard-coded repository or user paths.
    """
    rt = _configure_runtime(store_path)
    register_m3_handlers_on_default(rt)
    return rt


def register_m3_handlers_on_default(runtime: M6Runtime) -> None:
    from .dispatcher import _default_dispatcher
    handlers.register_m3_handlers(_default_dispatcher, runtime)
