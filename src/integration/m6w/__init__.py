"""M6W - the MCP memory tool set (T6b): recall / context (read) and add / ingest / forget (write).

A separate package from ``src.integration.m6`` on purpose: the M6 surface stays structurally read-only (its tool list
is pinned by tests); this package is mounted into the same pinned stdio server only when the operator asks for it
(``--enable-memory`` / ``--enable-write``). Everything delegates to :class:`zero_mem.memory.Memory`.
"""
from __future__ import annotations

from .contracts import READ_TOOLS, WRITE_TOOLS, tool_definitions
from .pathguard import PathGuard, RootsConfigError, normalize_roots
from .toolset import MemoryToolSet, ToolSetConfig, ToolSetConfigError, build_tool_set

__all__ = [
    "MemoryToolSet", "PathGuard", "READ_TOOLS", "RootsConfigError", "ToolSetConfig", "ToolSetConfigError",
    "WRITE_TOOLS", "build_tool_set", "normalize_roots", "tool_definitions",
]
