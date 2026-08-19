"""Zero-Mem runtime composition and master enable/disable gate.

The module-level compatibility state contains only the resolved master boolean.
Canonical writer ownership is instance-scoped and created through
``ZeroMemRuntime.open``; adapters never resolve a path or instantiate a store.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from src.storage.capture_boundary import CaptureStore, CaptureStoreConfig
from src.storage.jsonl_capture import JsonlCaptureStore
from src.storage.runtime_root import RuntimeStorageRoot


class ZeroMemConfigError(ValueError):
    """Typed error for invalid master-switch or runtime configuration."""


_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
_FALSE_VALUES = frozenset({"false", "0", "no", "off"})


@dataclass(frozen=True)
class RuntimeConfig:
    """Validated input for the runtime composition root."""

    capture_root: Path
    enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.capture_root, Path):
            raise TypeError("capture_root must be Path")
        if not isinstance(self.enabled, bool):
            raise TypeError("runtime enabled must be bool")
        if not self.capture_root.is_absolute():
            raise ValueError("capture_root must be absolute")
        root = self.capture_root.expanduser()
        if root == Path.home() or Path.home() in root.parents:
            raise ValueError("capture_root must not be inside the real home directory")
        object.__setattr__(self, "capture_root", root)


@dataclass(frozen=True)
class RuntimeHealth:
    status: Literal["OPEN", "CLOSED"]
    reason_code: str | None = None


def parse_zero_mem_enabled(raw: Optional[str]) -> bool:
    """Strictly parse the process-start master switch."""
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


class ZeroMemRuntime:
    """Instance-scoped runtime owning at most one canonical writer."""

    def __init__(
        self,
        *,
        enabled: bool,
        writer: CaptureStore | None = None,
        owns_writer: bool = False,
        source: str = "explicit",
    ) -> None:
        if not isinstance(enabled, bool):
            raise ZeroMemConfigError("runtime enabled must be bool")
        self.enabled = enabled
        self._writer = writer
        self._owns_writer = owns_writer
        self.source = source
        self._closed = False

    @classmethod
    def open(
        cls,
        config: RuntimeConfig,
        *,
        store: CaptureStore | None = None,
    ) -> "ZeroMemRuntime":
        """Create the sole runtime-owned canonical writer.

        ``store`` is an explicit injection seam for tests and controlled
        composition. Production callers pass only ``RuntimeConfig``.
        """
        if not isinstance(config, RuntimeConfig):
            raise TypeError("config must be RuntimeConfig")
        if not config.enabled:
            return cls(enabled=False)
        storage_root = RuntimeStorageRoot.open(config.capture_root)
        writer = store if store is not None else JsonlCaptureStore(
            CaptureStoreConfig(storage_root.canonical)
        )
        return cls(enabled=True, writer=writer, owns_writer=True)

    def is_enabled(self) -> bool:
        return self.enabled and not self._closed

    def disabled_reason(self) -> Optional[str]:
        if self._closed:
            return "RUNTIME_CLOSED"
        return None if self.enabled else "ZERO_MEM_DISABLED"

    @property
    def writer(self) -> CaptureStore:
        if self._closed:
            raise RuntimeError("RUNTIME_CLOSED")
        if not self.enabled or self._writer is None:
            raise RuntimeError("RUNTIME_WRITER_UNAVAILABLE")
        return self._writer

    def health(self) -> RuntimeHealth:
        if self._closed:
            return RuntimeHealth("CLOSED", "RUNTIME_CLOSED")
        if not self.enabled:
            return RuntimeHealth("CLOSED", "ZERO_MEM_DISABLED")
        if self._writer is None:
            return RuntimeHealth("CLOSED", "RUNTIME_WRITER_UNAVAILABLE")
        return RuntimeHealth("OPEN")

    def close(self) -> None:
        if self._closed:
            return None
        self._closed = True
        writer, self._writer = self._writer, None
        if self._owns_writer and writer is not None:
            writer.close()
        return None


# Compatibility state for the master boolean only; it never owns a writer.
_default_runtime: Optional[ZeroMemRuntime] = None


def configure(*, enabled: bool, source: str = "explicit") -> ZeroMemRuntime:
    """Resolve and install only the process-start master runtime gate."""
    global _default_runtime
    _default_runtime = ZeroMemRuntime(enabled=enabled, source=source)
    return _default_runtime


def new_runtime(*, enabled: bool) -> ZeroMemRuntime:
    """Create an explicit boolean-only runtime handle."""
    return ZeroMemRuntime(enabled=enabled)


def get_runtime() -> ZeroMemRuntime:
    if _default_runtime is None:
        raise RuntimeError(
            "ZeroMemRuntime not configured; call zero_mem_runtime.configure(enabled=...)"
        )
    return _default_runtime


__all__ = [
    "RuntimeConfig",
    "RuntimeHealth",
    "ZeroMemRuntime",
    "ZeroMemConfigError",
    "configure",
    "new_runtime",
    "get_runtime",
    "parse_zero_mem_enabled",
]
