"""Zero-Mem runtime composition and master enable/disable gate.

The runtime owns the canonical writer, the derived SQLite projection store, and
one bounded projection worker. JSONL remains canonical; SQLite is disposable.
"""
from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class RuntimeConfig:
    capture_root: Path
    enabled: bool = True
    projection_queue_capacity: int = 16
    projection_batch_size: int = 1

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
        for name, value in (("projection_queue_capacity", self.projection_queue_capacity), ("projection_batch_size", self.projection_batch_size)):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        object.__setattr__(self, "capture_root", root)


@dataclass(frozen=True)
class RuntimeHealth:
    status: Literal["OPEN", "CLOSED"]
    reason_code: str | None = None
    projection: ProjectionWatermark | None = None


class ZeroMemRuntime:
    """Instance-scoped owner of one writer, one derived store, and one worker."""

    def __init__(self, *, enabled: bool, writer: CaptureStore | None = None,
                 owns_writer: bool = False, derived: SQLiteStore | None = None,
                 projection: ProjectionCoordinator | None = None,
                 projection_error: str | None = None, source: str = "explicit") -> None:
        if not isinstance(enabled, bool):
            raise ZeroMemConfigError("runtime enabled must be bool")
        self.enabled = enabled
        self._writer = writer
        self._owns_writer = owns_writer
        self._derived = derived
        self._projection = projection
        self._projection_error = projection_error
        self._read_services: list[object] = []
        self.source = source
        self._closed = False

    @classmethod
    def open(cls, config: RuntimeConfig, *, store: CaptureStore | None = None) -> "ZeroMemRuntime":
        if not isinstance(config, RuntimeConfig):
            raise TypeError("config must be RuntimeConfig")
        if not config.enabled:
            return cls(enabled=False)
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
        return cls(enabled=True, writer=writer, owns_writer=True, derived=derived,
                   projection=projection, projection_error=projection_error)

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

    @property
    def projection(self) -> ProjectionCoordinator | None:
        if self._closed:
            raise RuntimeError("RUNTIME_CLOSED")
        return self._projection

    def notify_append(self, result: AppendResult) -> ProjectionStatus:
        """Submit a durable append; projection failure never changes capture success."""
        if self._closed:
            return ProjectionStatus.CLOSED
        if self._projection is None:
            return ProjectionStatus.UNAVAILABLE
        return self._projection.submit(self.writer_path, self.stream_name, result.sequence)

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
            return RuntimeHealth("CLOSED", "RUNTIME_CLOSED")
        if not self.enabled:
            return RuntimeHealth("CLOSED", "ZERO_MEM_DISABLED")
        if self._writer is None:
            return RuntimeHealth("CLOSED", "RUNTIME_WRITER_UNAVAILABLE")
        if self._projection is None:
            return RuntimeHealth("OPEN", self._projection_error or "PROJECTION_UNAVAILABLE")
        snapshot = self._projection.snapshot()
        reason = self._projection_error or snapshot.last_error
        return RuntimeHealth("OPEN", reason, snapshot)

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


__all__ = ["RuntimeConfig", "RuntimeHealth", "ZeroMemRuntime", "ZeroMemConfigError", "configure", "new_runtime", "get_runtime", "parse_zero_mem_enabled"]
