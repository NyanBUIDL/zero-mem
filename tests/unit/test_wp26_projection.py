from __future__ import annotations

import threading
import time
from pathlib import Path

from src.storage.projection import (
    ProjectionConfig,
    ProjectionCoordinator,
    ProjectionStatus,
)


def test_projection_processes_notification_and_reaches_current(tmp_path: Path) -> None:
    calls: list[tuple[str, int]] = []

    def projector(notification) -> int:
        calls.append((notification.source_id, notification.canonical_sequence))
        return notification.canonical_sequence

    coordinator = ProjectionCoordinator(
        ProjectionConfig(queue_capacity=2, batch_size=1, source_root=tmp_path),
        projector=projector,
    )
    coordinator.start()
    try:
        assert coordinator.submit(tmp_path / "events.jsonl", "events", 3) is ProjectionStatus.ENQUEUED
        assert coordinator.flush(timeout=1.0) is ProjectionStatus.CURRENT
        assert coordinator.snapshot().derived_sequence == 3
        assert calls == [("events", 3)]
    finally:
        coordinator.close(timeout=1.0)


def test_queue_full_stays_pending_without_worker_failure(tmp_path: Path) -> None:
    gate = threading.Event()
    started = threading.Event()

    def projector(notification) -> int:
        started.set()
        gate.wait(timeout=1.0)
        return notification.canonical_sequence

    coordinator = ProjectionCoordinator(
        ProjectionConfig(queue_capacity=1, batch_size=1, source_root=tmp_path),
        projector=projector,
    )
    coordinator.start()
    try:
        first = coordinator.submit(tmp_path / "events.jsonl", "events", 1)
        assert started.wait(timeout=1.0)
        second = coordinator.submit(tmp_path / "events.jsonl", "events", 2)
        third = coordinator.submit(tmp_path / "events.jsonl", "events", 3)
        assert first is ProjectionStatus.ENQUEUED
        assert second is ProjectionStatus.ENQUEUED
        assert third is ProjectionStatus.PENDING
        assert coordinator.snapshot().status is ProjectionStatus.PENDING
        gate.set()
        assert coordinator.flush(timeout=1.0) is ProjectionStatus.PENDING
        assert coordinator.submit(tmp_path / "events.jsonl", "events", 3) is ProjectionStatus.ENQUEUED
        assert coordinator.flush(timeout=1.0) is ProjectionStatus.CURRENT
    finally:
        gate.set()
        coordinator.close(timeout=1.0)


def test_worker_failure_is_unavailable_and_does_not_retry(tmp_path: Path) -> None:
    calls = 0

    def projector(notification) -> int:
        nonlocal calls
        calls += 1
        raise ValueError("secret failure detail")

    coordinator = ProjectionCoordinator(
        ProjectionConfig(queue_capacity=2, batch_size=1, source_root=tmp_path),
        projector=projector,
    )
    coordinator.start()
    try:
        coordinator.submit(tmp_path / "events.jsonl", "events", 1)
        assert coordinator.flush(timeout=1.0) is ProjectionStatus.UNAVAILABLE
        time.sleep(0.02)
        assert calls == 1
        assert coordinator.snapshot().derived_sequence == 0
    finally:
        coordinator.close(timeout=1.0)


def test_projection_rejects_source_outside_approved_root(tmp_path: Path) -> None:
    coordinator = ProjectionCoordinator(
        ProjectionConfig(queue_capacity=1, batch_size=1, source_root=tmp_path / "approved"),
        projector=lambda notification: notification.canonical_sequence,
    )
    coordinator.start()
    try:
        assert coordinator.submit(tmp_path / "outside.jsonl", "outside", 1) is ProjectionStatus.UNAVAILABLE
    finally:
        coordinator.close(timeout=1.0)


def test_projection_does_not_write_canonical_source(tmp_path: Path) -> None:
    canonical = tmp_path / "events.jsonl"
    canonical.write_bytes(b"canonical\n")
    before = canonical.read_bytes()
    coordinator = ProjectionCoordinator(
        ProjectionConfig(queue_capacity=2, batch_size=1, source_root=tmp_path),
        projector=lambda notification: notification.canonical_sequence,
    )
    coordinator.start()
    try:
        coordinator.submit(canonical, "events", 1)
        assert coordinator.flush(timeout=1.0) is ProjectionStatus.CURRENT
    finally:
        coordinator.close(timeout=1.0)
    assert canonical.read_bytes() == before
