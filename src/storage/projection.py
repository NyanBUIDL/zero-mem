"""Bounded asynchronous projection coordination over derived storage."""
from __future__ import annotations

import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable


class ProjectionStatus(str, Enum):
    ENQUEUED = "PROJECTION_ENQUEUED"
    CURRENT = "DERIVED_CURRENT"
    PENDING = "DERIVED_PENDING"
    UNAVAILABLE = "DERIVED_UNAVAILABLE"
    CLOSED = "PROJECTION_CLOSED"


@dataclass(frozen=True)
class ProjectionConfig:
    queue_capacity: int
    batch_size: int
    source_root: Path

    def __post_init__(self) -> None:
        if not isinstance(self.queue_capacity, int) or isinstance(self.queue_capacity, bool) or self.queue_capacity <= 0:
            raise ValueError("queue_capacity must be a positive integer")
        if not isinstance(self.batch_size, int) or isinstance(self.batch_size, bool) or self.batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")
        if not isinstance(self.source_root, Path) or not self.source_root.is_absolute():
            raise ValueError("source_root must be an absolute Path")
        object.__setattr__(self, "source_root", self.source_root.resolve())


@dataclass(frozen=True)
class ProjectionWatermark:
    canonical_sequence: int
    derived_sequence: int
    status: ProjectionStatus
    last_success_at: float | None = None
    last_error: str | None = None


@dataclass(frozen=True)
class ProjectionNotification:
    source_path: Path
    source_id: str
    canonical_sequence: int


Projector = Callable[[ProjectionNotification], int]
_SENTINEL = object()


class ProjectionCoordinator:
    """One bounded worker for a trusted runtime-owned derived projector.

    ``projector`` is an internal dependency, never a transport/user callback. Production
    construction should use ``from_ingest`` so canonical JSONL remains read-only by the
    existing ingestion contract; the injectable callback exists for deterministic tests.
    """

    def __init__(self, config: ProjectionConfig, *, projector: Projector) -> None:
        if not callable(projector):
            raise TypeError("projector must be callable")
        self.config = config
        self._projector = projector
        self._queue: queue.Queue[ProjectionNotification | object] = queue.Queue(
            maxsize=config.queue_capacity
        )
        self._deferred: deque[ProjectionNotification] = deque(maxlen=config.queue_capacity)
        self._condition = threading.Condition()
        self._worker: threading.Thread | None = None
        self._closed = False
        self._failed = False
        self._canonical_sequence = 0
        self._derived_sequence = 0
        self._submitted: dict[str, int] = {}
        self._last_success_at: float | None = None
        self._last_error: str | None = None

    @classmethod
    def from_ingest(cls, config: ProjectionConfig, *, store: object) -> "ProjectionCoordinator":
        """Build a coordinator using the canonical existing ingestion path."""
        from src.storage.coordination import coordinated
        from src.storage.ingest import get_checkpoint, ingest_file

        def projector(notification: ProjectionNotification) -> int:
            derived_path = getattr(store, "path", None)
            if not isinstance(derived_path, Path):
                raise RuntimeError("projection_coordination_unavailable")
            with coordinated(notification.source_path, derived_path, mode="exclusive", timeout=5.0):
                report = ingest_file(store, notification.source_path, notification.source_id)
                checkpoint = get_checkpoint(store, notification.source_id)
            if report.stopped or checkpoint is None or not isinstance(checkpoint.get("last_sequence"), int):
                raise RuntimeError("projection_ingest_unavailable")
            return int(checkpoint["last_sequence"])

        return cls(config, projector=projector)

    def start(self) -> None:
        with self._condition:
            if self._closed:
                raise RuntimeError("PROJECTION_CLOSED")
            if self._worker is not None:
                return None
            self._worker = threading.Thread(
                target=self._run,
                name="zero-mem-projection",
                daemon=True,
            )
            self._worker.start()
        return None

    def submit(self, source_path: Path, source_id: str, canonical_sequence: int) -> ProjectionStatus:
        if not isinstance(source_path, Path) or not source_path.is_absolute():
            return ProjectionStatus.UNAVAILABLE
        try:
            if source_path.is_symlink():
                return ProjectionStatus.UNAVAILABLE
            source_path = source_path.resolve()
            source_path.relative_to(self.config.source_root)
        except (OSError, ValueError):
            return ProjectionStatus.UNAVAILABLE
        if not isinstance(source_id, str) or not source_id:
            return ProjectionStatus.UNAVAILABLE
        if not isinstance(canonical_sequence, int) or isinstance(canonical_sequence, bool) or canonical_sequence < 0:
            return ProjectionStatus.UNAVAILABLE
        with self._condition:
            if self._closed:
                return ProjectionStatus.CLOSED
            if self._failed:
                return ProjectionStatus.UNAVAILABLE
            if self._worker is None:
                raise RuntimeError("PROJECTION_NOT_STARTED")
            self._canonical_sequence = max(self._canonical_sequence, canonical_sequence)
            previous = self._submitted.get(source_id)
            has_deferred = any(item.source_id == source_id for item in self._deferred)
            if previous is not None and canonical_sequence <= previous and not has_deferred:
                if self._derived_sequence >= canonical_sequence:
                    return ProjectionStatus.CURRENT
                return ProjectionStatus.PENDING
            self._submitted[source_id] = canonical_sequence
        notification = ProjectionNotification(source_path, source_id, canonical_sequence)
        try:
            self._queue.put_nowait(notification)
        except queue.Full:
            with self._condition:
                for index, pending in enumerate(self._deferred):
                    if pending.source_id == notification.source_id:
                        if notification.canonical_sequence > pending.canonical_sequence:
                            self._deferred[index] = notification
                        self._condition.notify_all()
                        return ProjectionStatus.PENDING
                if len(self._deferred) >= self.config.queue_capacity:
                    return ProjectionStatus.UNAVAILABLE
                self._deferred.append(notification)
                self._condition.notify_all()
            return ProjectionStatus.PENDING
        with self._condition:
            # A successful resubmission supersedes a same-source deferred
            # notification. Deferred work is deliberately not auto-promoted
            # by the worker: until resubmission it remains DERIVED_PENDING.
            self._deferred = deque(
                (
                    pending
                    for pending in self._deferred
                    if not (
                        pending.source_id == notification.source_id
                        and pending.canonical_sequence <= notification.canonical_sequence
                    )
                ),
                maxlen=self.config.queue_capacity,
            )
            self._condition.notify_all()
        return ProjectionStatus.ENQUEUED

    def snapshot(self) -> ProjectionWatermark:
        with self._condition:
            if self._closed:
                status = ProjectionStatus.CLOSED
            elif self._failed:
                status = ProjectionStatus.UNAVAILABLE
            elif self._derived_sequence >= self._canonical_sequence and self._queue.unfinished_tasks == 0 and not self._deferred:
                status = ProjectionStatus.CURRENT
            else:
                status = ProjectionStatus.PENDING
            return ProjectionWatermark(
                self._canonical_sequence,
                self._derived_sequence,
                status,
                self._last_success_at,
                self._last_error,
            )

    def flush(self, timeout: float | None = None) -> ProjectionStatus:
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while self._queue.unfinished_tasks or self._deferred:
                if self._failed:
                    return ProjectionStatus.UNAVAILABLE
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return ProjectionStatus.PENDING
                self._condition.wait(timeout=remaining)
            return self.snapshot().status

    def close(self, timeout: float | None = None) -> None:
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            if self._closed:
                return None
            self._closed = True
            worker = self._worker
        if worker is None:
            return None
        self.flush(timeout=self._remaining(deadline))
        while worker.is_alive():
            try:
                self._queue.put_nowait(_SENTINEL)
                break
            except queue.Full:
                if deadline is not None and time.monotonic() >= deadline:
                    return None
                threading.Event().wait(0.001)
        worker.join(timeout=self._remaining(deadline))
        return None

    def _remaining(self, deadline: float | None) -> float | None:
        return None if deadline is None else max(0.0, deadline - time.monotonic())

    def _run(self) -> None:
        item = self._queue.get()
        batch_count = 0
        while item is not _SENTINEL:
            try:
                derived_sequence = self._projector(item)
                if not isinstance(derived_sequence, int) or isinstance(derived_sequence, bool) or derived_sequence < item.canonical_sequence:
                    raise ValueError("projection watermark invalid")
                with self._condition:
                    self._derived_sequence = max(self._derived_sequence, derived_sequence)
            except Exception:
                with self._condition:
                    self._failed = True
                    self._last_error = "PROJECTION_FAILED"
                self._queue.task_done()
                self._drain_after_failure()
                with self._condition:
                    self._condition.notify_all()
                return
            with self._condition:
                self._last_success_at = time.time()
            self._queue.task_done()
            batch_count += 1
            with self._condition:
                self._condition.notify_all()
            if batch_count >= self.config.batch_size:
                batch_count = 0
                threading.Event().wait(0)
            item = self._queue.get()
        self._queue.task_done()
        with self._condition:
            self._condition.notify_all()

    def _drain_after_failure(self) -> None:
        try:
            item = self._queue.get_nowait()
        except queue.Empty:
            return
        while item is not _SENTINEL:
            self._queue.task_done()
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return
        self._queue.task_done()


__all__ = [
    "ProjectionConfig",
    "ProjectionCoordinator",
    "ProjectionNotification",
    "ProjectionStatus",
    "ProjectionWatermark",
]
