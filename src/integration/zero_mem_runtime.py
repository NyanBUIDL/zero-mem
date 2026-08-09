"""M7.1 — Master Zero-Mem runtime gate (single source of truth).

Owns the ONE authoritative master enable/disable boolean (``ZERO_MEM_ENABLED``).
Contains NO retrieval, authorization, SQLite, JSONL, routing, or injection logic.
It is a pure configuration/runtime-state holder consulted by M1, M6, and future
M7 modules so that the master setting is resolved exactly once per process start
and never re-parsed per request.

Design constraints (M7.1 plan):
* one canonical resolved boolean;
* absent config defaults to ``True`` (backward-compatible with M0-M6);
* invalid/garbled config raises ``ZeroMemConfigError`` (NOT silently true/false);
* restart required to change the setting (no watcher/polling);
* no mutable request/authorization state is stored here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class ZeroMemConfigError(ValueError):
    """Typed error for invalid master-switch configuration.

    Distinct from disabled state: an invalid value must fail closed at
    initialization, it must NOT be coerced into enabled or disabled.
    """


# Strict accepted spellings (case-insensitive, whitespace-stripped).
_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
_FALSE_VALUES = frozenset({"false", "0", "no", "off"})


def parse_zero_mem_enabled(raw: Optional[str]) -> bool:
    """Strictly parse a raw config string into the master boolean.

    MISSING (None) -> compatibility default ``True``.
    INVALID (anything not in the documented set) -> raises ``ZeroMemConfigError``.
    """
    if raw is None:
        return True
    if not isinstance(raw, str):
        raise ZeroMemConfigError(
            f"ZERO_MEM_ENABLED must be a string or None, got {type(raw).__name__}"
        )
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ZeroMemConfigError(
        f"invalid ZERO_MEM_ENABLED value: {raw!r} "
        f"(allowed: true/1/yes/on, false/0/no/off; absent defaults to true)"
    )


@dataclass(frozen=True)
class ZeroMemRuntime:
    """Immutable resolved master runtime state.

    Holds only whether Zero-Mem participates globally. No request, grant, scope,
    or authorization state is stored here.
    """

    enabled: bool

    def is_enabled(self) -> bool:
        return self.enabled

    def disabled_reason(self) -> Optional[str]:
        return None if self.enabled else "ZERO_MEM_DISABLED"


# Module-level default runtime, configured once per process via ``configure``.
_default_runtime: Optional[ZeroMemRuntime] = None


def configure(*, enabled: bool) -> ZeroMemRuntime:
    """Resolve and install the master runtime state for this process.

    Called during supported runtime/configuration initialization (startup), not
    per request. Changing the switch requires restart.
    """
    global _default_runtime
    _default_runtime = ZeroMemRuntime(enabled=bool(enabled))
    return _default_runtime


def get_runtime() -> ZeroMemRuntime:
    if _default_runtime is None:
        raise RuntimeError(
            "ZeroMemRuntime not configured; call zero_mem_runtime.configure(enabled=...)"
        )
    return _default_runtime


__all__ = [
    "ZeroMemRuntime",
    "ZeroMemConfigError",
    "configure",
    "get_runtime",
    "parse_zero_mem_enabled",
]
