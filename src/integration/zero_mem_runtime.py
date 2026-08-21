"""Zero-Mem runtime composition and master enable/disable gate.

The runtime owns the canonical writer, the derived SQLite projection store, and
one bounded projection worker. JSONL remains canonical; SQLite is disposable.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal, Optional

from src.storage.capture_boundary import AppendResult, CaptureStore, CaptureStoreConfig
from src.storage.jsonl_capture import JsonlCaptureStore
from src.storage.projection import ProjectionConfig, ProjectionCoordinator, ProjectionStatus, ProjectionWatermark
from src.storage.runtime_root import RuntimeStorageRoot
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig


class ZeroMemConfigError(ValueError):
    """Typed error for invalid master-switch or runtime configuration."""


_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
_FALSE_VALUES = frozenset({"false", "0", "no", "off"})


class RuntimeMode(str, Enum):
    """Explicit runtime mode controlling writer/capture/read/injection scope.

    V124-02. Each mode maps to an exact capability matrix; see
    ``ZeroMemRuntime.capability_matrix`` and the VALIDATION_SPEC truth table.
    """

    OFF = "off"
    OBSERVE = "observe"
    ASSIST = "assist"
    INJECT = "inject"

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.value


# Canonical accepted runtime-mode strings (kept explicit; no silent aliases).
_RUNTIME_MODE_VALUES = frozenset(mode.value for mode in RuntimeMode)


def parse_runtime_mode(raw: object) -> RuntimeMode:
    """Parse an explicit runtime mode string into ``RuntimeMode``.

    Raises ``ZeroMemConfigError`` for unknown values. Missing/None is NOT
    accepted here; ``RuntimeConfig`` owns the default-mode decision.
    """
    if not isinstance(raw, str):
        raise ZeroMemConfigError(f"runtime_mode must be a string, got {type(raw).__name__}")
    normalized = raw.strip().lower()
    if normalized not in _RUNTIME_MODE_VALUES:
        raise ZeroMemConfigError(f"invalid runtime_mode value: {raw!r}")
    return RuntimeMode(normalized)


def mode_read_enabled(mode: RuntimeMode) -> bool:
    """Read tools are registered only in assist/inject modes."""
    return mode in (RuntimeMode.ASSIST, RuntimeMode.INJECT)


def mode_injection_enabled(mode: RuntimeMode) -> bool:
    """Injection hook is registered only in inject mode (controlled)."""
    return mode is RuntimeMode.INJECT


@dataclass(frozen=True)
class RuntimeConfig:
    capture_root: Path
    enabled: bool = True
    mode: RuntimeMode = RuntimeMode.ASSIST
    projection_queue_capacity: int = 16
    projection_batch_size: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.capture_root, Path):
            raise TypeError("capture_root must be Path")
        if not isinstance(self.enabled, bool):
            raise TypeError("runtime enabled must be bool")
        if not isinstance(self.mode, RuntimeMode):
            # Accept a canonical runtime-mode string; reject anything else.
            if isinstance(self.mode, str):
                try:
                    object.__setattr__(self, "mode", parse_runtime_mode(self.mode))
                except ZeroMemConfigError as exc:
                    raise ValueError(str(exc)) from None
            else:
                raise TypeError("runtime mode must be RuntimeMode or a valid mode string")
        if not self.capture_root.is_absolute():
            raise ValueError("capture_root must be absolute")
        root = self.capture_root.expanduser()
        if root == Path.home() or Path.home() in root.parents:
            raise ValueError("capture_root must not be inside the real home directory")
        # Backward migration: explicit disabled overrides mode to OFF (fail-closed).
        if not self.enabled and self.mode is not RuntimeMode.OFF:
            object.__setattr__(self, "mode", RuntimeMode.OFF)
        for name, value in (("projection_queue_capacity", self.projection_queue_capacity), ("projection_batch_size", self.projection_batch_size)):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        object.__setattr__(self, "capture_root", root)


@dataclass(frozen=True)
class RuntimeHealth:
    status: Literal["OPEN", "CLOSED"]
    reason_code: str | None = None
    projection: ProjectionWatermark | None = None
    mode: str | None = None
    # V124-03 truthful-freshness surface (single runtime-owned topology).
    capture_enabled: bool = False
    last_canonical_sequence: int = 0
    last_projected_sequence: int = 0
    lag: int = 0
    projection_status: str | None = None
    read_store_identity: str | None = None
    injection_enabled: bool = False


class ZeroMemRuntime:
    """Instance-scoped owner of one writer, one derived store, and one worker.

    V124-02: an explicit ``mode`` governs which capabilities are live. ``off``
    opens no writer and no derived store. ``observe`` captures only. ``assist``
    additionally registers read tools. ``inject`` additionally registers the
    controlled injection hook.
    """

    def __init__(self, *, enabled: bool, mode: RuntimeMode = RuntimeMode.ASSIST,
                 writer: CaptureStore | None = None, owns_writer: bool = False,
                 derived: SQLiteStore | None = None,
                 projection: ProjectionCoordinator | None = None,
                 projection_error: str | None = None, source: str = "explicit",
                 injection_adapter: object | None = None) -> None:
        if not isinstance(enabled, bool):
            raise ZeroMemConfigError("runtime enabled must be bool")
        if not isinstance(mode, RuntimeMode):
            raise ZeroMemConfigError("runtime mode must be RuntimeMode")
        self.enabled = enabled
        self.mode = mode
        self._writer = writer
        self._owns_writer = owns_writer
        self._derived = derived
        self._projection = projection
        self._projection_error = projection_error
        self._read_services: list[object] = []
        self.source = source
        self._injection_adapter = injection_adapter
        self._closed = False
        self._last_canonical_sequence = 0

    @classmethod
    def open(cls, config: RuntimeConfig, *, store: CaptureStore | None = None) -> "ZeroMemRuntime":
        if not isinstance(config, RuntimeConfig):
            raise TypeError("config must be RuntimeConfig")
        if not config.enabled or config.mode is RuntimeMode.OFF:
            # OFF: fail-closed. Open no writer, no derived store, no worker.
            return cls(enabled=False, mode=RuntimeMode.OFF)
        storage_root = RuntimeStorageRoot.open(config.capture_root)
        writer = store if store is not None else JsonlCaptureStore(CaptureStoreConfig(storage_root.canonical))
        derived: SQLiteStore | None = None
        projection: ProjectionCoordinator | None = None
        projection_error: str | None = None
        try:
            derived = SQLiteStore(SQLiteStoreConfig(storage_root.derived / "events.sqlite"))
            derived.ensure_schema()
            projection = ProjectionCoordinator.from_ingest(
                ProjectionConfig(config.projection_queue_capacity, config.projection_batch_size, storage_root.canonical),
                store=derived,
            )
            projection.start()
        except Exception:
            projection_error = "PROJECTION_UNAVAILABLE"
            if derived is not None:
                derived.close()
                derived = None
        return cls(enabled=True, mode=config.mode, writer=writer, owns_writer=True, derived=derived,
                   projection=projection, projection_error=projection_error)

    def is_enabled(self) -> bool:
        return self.enabled and not self._closed

    def disabled_reason(self) -> Optional[str]:
        if self._closed:
            return "RUNTIME_CLOSED"
        return None if self.enabled else "ZERO_MEM_DISABLED"

    # --- V124-02 explicit-mode capability surface (per-cell, not inferred) ---
    @property
    def writer_open(self) -> bool:
        return self.enabled and not self._closed and self._writer is not None

    @property
    def capture_enabled(self) -> bool:
        return self.writer_open

    @property
    def read_enabled(self) -> bool:
        return self.writer_open and mode_read_enabled(self.mode)

    @property
    def injection_enabled(self) -> bool:
        return self.writer_open and mode_injection_enabled(self.mode)

    @property
    def injection_adapter(self) -> object | None:
        return self._injection_adapter

    def capability_matrix(self) -> dict[str, bool]:
        """Exact runtime-mode truth table; each cell asserted directly.

        Returns the four capability columns from VALIDATION_SPEC plus the
        health-reports-mode invariant flag.
        """
        return {
            "writer_open": self.writer_open,
            "conversation_captured": self.capture_enabled,
            "read_tool_registered": self.read_enabled,
            "injection_hook_registered": self.injection_enabled,
            "health_reports_mode": True,
        }

    @property
    def writer(self) -> CaptureStore:
        if self._closed:
            raise RuntimeError("RUNTIME_CLOSED")
        if not self.enabled or self._writer is None:
            raise RuntimeError("RUNTIME_WRITER_UNAVAILABLE")
        return self._writer

    @property
    def projection(self) -> ProjectionCoordinator | None:
        if self._closed:
            raise RuntimeError("RUNTIME_CLOSED")
        return self._projection

    def notify_append(self, result: AppendResult) -> ProjectionStatus:
        """Submit a durable append; projection failure never changes capture success.

        V124-03: the canonical sequence is recorded from the durable append receipt
        independent of projection state, so health/freshness truthfully reflect capture
        even when the derived store is unavailable or lagging.
        """
        if self._closed:
            return ProjectionStatus.CLOSED
        if isinstance(result.sequence, int) and not isinstance(result.sequence, bool) and result.sequence >= 0:
            self._last_canonical_sequence = max(self._last_canonical_sequence, result.sequence)
        if self._projection is None:
            return ProjectionStatus.UNAVAILABLE
        return self._projection.submit(self.writer_path, self.stream_name, result.sequence)

    def sync(self) -> str:
        """Return the truthful sync state of the single runtime-owned topology.

        V124-03 exit gate: ``CURRENT`` only when the derived watermark has caught the
        canonical watermark and the identity/checkpoint is valid. Otherwise reports
        ``STALE`` (lagging), ``UNAVAILABLE`` (derived not usable), ``OFF`` or ``DISABLED``.
        This never claims CURRENT on a false premise.
        """
        if not self.enabled or self._closed:
            return "OFF" if not self.enabled else "DISABLED"
        if self._writer is None:
            return "UNAVAILABLE"
        if self._projection is None:
            return "UNAVAILABLE"
        status = self.flush_projection(timeout=5.0)
        snapshot = self._projection.snapshot()
        if status is ProjectionStatus.CURRENT and snapshot.derived_sequence >= snapshot.canonical_sequence:
            return "CURRENT"
        return "STALE"

    @property
    def writer_path(self) -> Path:
        writer = self.writer
        path = getattr(writer, "path", None)
        if not isinstance(path, Path):
            raise RuntimeError("PROJECTION_SOURCE_UNAVAILABLE")
        return path

    @property
    def stream_name(self) -> str:
        return self.writer_path.name

    def health(self) -> RuntimeHealth:
        if self._closed:
            return RuntimeHealth(
                "CLOSED", "RUNTIME_CLOSED", mode=self.mode.value,
                capture_enabled=False, read_store_identity=None, injection_enabled=False,
            )
        if not self.enabled:
            return RuntimeHealth(
                "CLOSED", "ZERO_MEM_DISABLED", mode=self.mode.value,
                capture_enabled=False, read_store_identity=None, injection_enabled=False,
            )
        if self._writer is None:
            return RuntimeHealth(
                "CLOSED", "RUNTIME_WRITER_UNAVAILABLE", mode=self.mode.value,
                capture_enabled=False, read_store_identity=None, injection_enabled=False,
            )
        if self._projection is None:
            return RuntimeHealth(
                "OPEN", self._projection_error or "PROJECTION_UNAVAILABLE", mode=self.mode.value,
                capture_enabled=self.capture_enabled,
                last_canonical_sequence=self._last_canonical_sequence,
                last_projected_sequence=0,
                lag=self._last_canonical_sequence,
                projection_status="DERIVED_UNAVAILABLE",
                read_store_identity=None,
                injection_enabled=self.injection_enabled,
            )
        snapshot = self._projection.snapshot()
        derived = snapshot.derived_sequence
        canonical = snapshot.canonical_sequence
        lag = max(0, canonical - derived)
        # V124-03: health reads a snapshot; it never self-greens. STALE reflects lag;
        # UNAVAILABLE reflects a derived store that cannot be used.
        status_value = snapshot.status.value if isinstance(snapshot.status, ProjectionStatus) else str(snapshot.status)
        return RuntimeHealth(
            "OPEN", status_value, snapshot, mode=self.mode.value,
            capture_enabled=self.capture_enabled,
            last_canonical_sequence=canonical,
            last_projected_sequence=derived,
            lag=lag,
            projection_status=status_value,
            read_store_identity=str(self._derived.path) if self._derived is not None else None,
            injection_enabled=self.injection_enabled,
        )

    def flush_projection(self, timeout: float | None = None) -> ProjectionStatus:
        if self._projection is None:
            return ProjectionStatus.UNAVAILABLE
        return self._projection.flush(timeout)

    def open_read_service(self, *, requesting_profile_id: str | None):
        """Create the public adapter over a strict read-only derived connection."""
        if self._derived is None:
            raise RuntimeError("READ_SERVICE_UNAVAILABLE")
        from src.access.authorized_read import AuthorizedReadService
        from src.integration.public_read_adapter import AuthorizedPublicReadAdapter
        from src.retrieval.db import open_readonly
        readonly = open_readonly(self._derived.path)

        def freshness() -> dict[str, object]:
            snapshot = self.health().projection
            if snapshot is None:
                return {"status": "DERIVED_UNAVAILABLE", "canonical_sequence": 0, "derived_sequence": 0}
            return {
                "status": snapshot.status.value,
                "canonical_sequence": snapshot.canonical_sequence,
                "derived_sequence": snapshot.derived_sequence,
            }

        adapter = AuthorizedPublicReadAdapter(
            AuthorizedReadService(readonly, requesting_profile_id),
            requesting_profile_id=requesting_profile_id,
            freshness_provider=freshness,
            wait_provider=self.flush_projection,
        )
        self._read_services.append(adapter)
        return adapter

    def close(self, timeout: float | None = None) -> None:
        if self._closed:
            return None
        self._closed = True
        projection, self._projection = self._projection, None
        if projection is not None:
            projection.close(timeout=timeout)
        read_services, self._read_services = self._read_services, []
        for service in read_services:
            close = getattr(service, "close", None)
            if callable(close):
                close()
        writer, self._writer = self._writer, None
        if self._owns_writer and writer is not None:
            writer.close()
        derived, self._derived = self._derived, None
        if derived is not None:
            derived.close()
        return None


_default_runtime: Optional[ZeroMemRuntime] = None


def parse_zero_mem_enabled(raw: Optional[str]) -> bool:
    if raw is None:
        return True
    if not isinstance(raw, str):
        raise ZeroMemConfigError(f"ZERO_MEM_ENABLED must be a string or None, got {type(raw).__name__}")
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ZeroMemConfigError(f"invalid ZERO_MEM_ENABLED value: {raw!r}")


def configure(*, enabled: bool, source: str = "explicit") -> ZeroMemRuntime:
    global _default_runtime
    _default_runtime = ZeroMemRuntime(enabled=enabled, source=source)
    return _default_runtime


def new_runtime(*, enabled: bool) -> ZeroMemRuntime:
    return ZeroMemRuntime(enabled=enabled)


def get_runtime() -> ZeroMemRuntime:
    if _default_runtime is None:
        raise RuntimeError("ZeroMemRuntime not configured; call zero_mem_runtime.configure(enabled=...)")
    return _default_runtime


__all__ = ["RuntimeConfig", "RuntimeHealth", "RuntimeMode", "ZeroMemRuntime", "ZeroMemConfigError", "configure", "new_runtime", "get_runtime", "parse_runtime_mode", "mode_read_enabled", "mode_injection_enabled"]
