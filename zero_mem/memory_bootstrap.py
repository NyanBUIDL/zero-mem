"""Compatibility alias for race-safe first-run setup.

The setup lock now lives in :meth:`zero_mem.memory_layout.Layout.ensure` itself (T8), so every entry point - library,
CLI and MCP server - is safe when several processes start at the same moment on a data root nobody initialised.
:func:`ensure_layout` is kept for the callers that predate that (``zero-mem serve``, the MCP tool set); it is exactly
``layout.ensure(attempts=...)``.
"""
from __future__ import annotations

from .memory_layout import LOCK_NAME, SETUP_ATTEMPTS, Layout

ATTEMPTS = SETUP_ATTEMPTS


def ensure_layout(layout: Layout, *, attempts: int = ATTEMPTS) -> None:
    """Idempotently create private dirs, the canonical stream, the corpus root and the schema (race-safe)."""
    layout.ensure(attempts=attempts)


__all__ = ["ATTEMPTS", "LOCK_NAME", "ensure_layout"]
