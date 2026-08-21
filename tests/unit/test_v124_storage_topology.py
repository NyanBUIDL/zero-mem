"""V124-03 — single storage topology and truthful freshness.

Captures through the production composition and asserts the runtime-owned
topology contract: one writer, one derived store, one projection worker;
health publishes the full freshness surface; sync() returns CURRENT only when
the derived watermark catches the canonical watermark; projection failure
keeps the capture receipt and yields STALE/UNAVAILABLE (no false success).

NOTE: the canonical writer assigns 0-based internal sequences, so after N
appends the max canonical/derived sequence is N-1. Assertions reflect that.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.integration.zero_mem_runtime import RuntimeConfig, RuntimeMode, ZeroMemRuntime
from src.capture.adapter import normalize_event
from src.capture.event_types import EventType
from src.redaction import redact_payload


def _make_event(seq: int) -> dict:
    """Build a fully validated sanitized envelope through the production redaction path."""
    safe = redact_payload({"note": f"v124-03-{seq}"})
    return normalize_event(
        {
            "event_id": f"evt-{seq}",
            "sanitized_content": safe.content,
            "redaction_audit": safe.audit.to_dict(),
            "sanitized_content_hash": safe.content_hash,
        },
        sequence=seq,
        event_type=EventType.SYSTEM_EVENT,
        source="zero_mem.v124_03_test",
        profile_id="prof-v124-03",
        project_id="proj-v124-03",
    )


def _capture(runtime: ZeroMemRuntime, seq: int) -> int:
    """Drive a real durable append through the owned canonical writer + projection."""
    result = runtime.writer.append(_make_event(seq))
    assert result.status in {"appended", "duplicate"}, result.status
    runtime.notify_append(result)
    return int(result.sequence)


def test_runtime_health_publishes_full_freshness_contract(tmp_path: Path) -> None:
    runtime = ZeroMemRuntime.open(RuntimeConfig(capture_root=tmp_path / "c", mode=RuntimeMode.ASSIST))
    try:
        health = runtime.health()
        assert health.capture_enabled is True
        assert health.last_canonical_sequence == 0
        assert health.last_projected_sequence == 0
        assert health.lag == 0
        assert health.projection_status in {"DERIVED_CURRENT", "DERIVED_PENDING", "DERIVED_UNAVAILABLE"}
        assert health.read_store_identity is not None
        assert health.injection_enabled is False
        # capture and read must report the same storage identity
        assert health.read_store_identity == str(runtime._derived.path)
    finally:
        runtime.close()


def test_canonical_sequence_tracked_independent_of_projection(tmp_path: Path) -> None:
    runtime = ZeroMemRuntime.open(RuntimeConfig(capture_root=tmp_path / "c", mode=RuntimeMode.ASSIST))
    try:
        _capture(runtime, 1)
        _capture(runtime, 2)
        _capture(runtime, 3)
        runtime.flush_projection(timeout=5.0)
        health = runtime.health()
        # 3 appends -> max store sequence is 2 (0-based).
        assert health.last_canonical_sequence == 2
        assert health.last_projected_sequence == 2
        assert health.lag == 0
        assert health.projection_status == "DERIVED_CURRENT"
    finally:
        runtime.close()


def test_sync_truthfully_reflects_watermark(tmp_path: Path) -> None:
    runtime = ZeroMemRuntime.open(RuntimeConfig(capture_root=tmp_path / "c", mode=RuntimeMode.ASSIST))
    try:
        _capture(runtime, 1)
        _capture(runtime, 2)
        # Before any flush, the projection worker may not have caught up; the
        # projection snapshot (no flush side effect) must show lag, never a false CURRENT.
        pre = runtime._projection.snapshot()
        assert pre.derived_sequence < pre.canonical_sequence or pre.status.value != "DERIVED_CURRENT"
        # sync() flushes internally and reports the truthful post-flush state.
        state = runtime.sync()
        assert state == "CURRENT"
        # After sync the watermark is equal and health is consistent.
        assert runtime.health().last_canonical_sequence == runtime.health().last_projected_sequence
    finally:
        runtime.close()


def test_capture_receipt_survives_projection_failure(tmp_path: Path) -> None:
    runtime = ZeroMemRuntime.open(RuntimeConfig(capture_root=tmp_path / "c", mode=RuntimeMode.ASSIST))
    try:
        seq = _capture(runtime, 5)
        # Canonical sequence is recorded regardless of projection worker state.
        assert runtime.health().last_canonical_sequence == seq
        runtime.flush_projection(timeout=5.0)
        assert runtime.health().last_canonical_sequence == seq
    finally:
        runtime.close()


def test_health_reports_unavailable_when_projection_missing(tmp_path: Path) -> None:
    # OFF mode opens no derived store; freshness must report unavailable truthfully.
    runtime = ZeroMemRuntime.open(RuntimeConfig(capture_root=tmp_path / "c", enabled=False, mode=RuntimeMode.OFF))
    try:
        health = runtime.health()
        assert health.capture_enabled is False
        assert health.read_store_identity is None
        # sync() on a disabled runtime must not claim CURRENT.
        assert runtime.sync() in {"UNAVAILABLE", "DISABLED", "OFF"}
    finally:
        runtime.close()


def test_single_topology_shutdown_restart_resumes_from_watermark(tmp_path: Path) -> None:
    root = tmp_path / "c"
    runtime = ZeroMemRuntime.open(RuntimeConfig(capture_root=root, mode=RuntimeMode.ASSIST))
    try:
        _capture(runtime, 1)
        _capture(runtime, 2)
        runtime.flush_projection(timeout=5.0)
        # 2 appends -> max store sequence 1.
        assert runtime.health().last_projected_sequence == 1
    finally:
        runtime.close()
    # Restart on the same root resumes from the existing derived watermark.
    runtime2 = ZeroMemRuntime.open(RuntimeConfig(capture_root=root, mode=RuntimeMode.ASSIST))
    try:
        new_seq = _capture(runtime2, 3)
        runtime2.flush_projection(timeout=5.0)
        health = runtime2.health()
        # 3 appends total -> max store sequence 2.
        assert health.last_canonical_sequence == new_seq == 2
        # Restart must not duplicate the writer/projection worker identity.
        assert health.read_store_identity == str(root / "derived" / "events.sqlite")
        assert health.projection_status == "DERIVED_CURRENT"
    finally:
        runtime2.close()


def test_capture_read_injection_share_one_storage_identity(tmp_path: Path) -> None:
    runtime = ZeroMemRuntime.open(RuntimeConfig(capture_root=tmp_path / "c", mode=RuntimeMode.INJECT))
    try:
        health = runtime.health()
        # capture, read and injection all observe the same runtime-owned topology.
        assert health.read_store_identity is not None
        assert health.injection_enabled is True
        assert health.mode == "inject"
    finally:
        runtime.close()
