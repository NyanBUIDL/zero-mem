"""V124-04 — HITL correction lifecycle over the runtime-owned topology.

Inspect -> propose -> preview -> explicit confirm -> append linked control event
-> rebuild projection. Asserts: no silent overwrite (original trace preserved),
denial leaks no candidate, delete-request keeps the canonical record and applies a
tombstone with provenance, and Skill lifecycle capture never rewrites SKILL.md.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.integration.zero_mem_runtime import RuntimeConfig, RuntimeMode, ZeroMemRuntime
from src.capture.adapter import normalize_event
from src.capture.event_types import EventType
from src.redaction import redact_payload
from zero_mem.correction import (
    CorrectionController,
    CorrectionKind,
    ProposalPreview,
    CorrectionReceipt,
)


def _event(seq: int) -> dict:
    safe = redact_payload({"note": f"v124-04-{seq}"})
    return normalize_event(
        {
            "event_id": f"evt-{seq}",
            "sanitized_content": safe.content,
            "redaction_audit": safe.audit.to_dict(),
            "sanitized_content_hash": safe.content_hash,
        },
        sequence=seq,
        event_type=EventType.SYSTEM_EVENT,
        source="zero_mem.v124_04_test",
        profile_id="prof-v124-04",
        project_id="proj-v124-04",
    )


def _capture(runtime: ZeroMemRuntime, seq: int) -> str:
    result = runtime.writer.append(_event(seq))
    assert result.status == "appended", result.status
    runtime.notify_append(result)
    return result.event_id


def _make_controller(tmp_path: Path) -> tuple[ZeroMemRuntime, CorrectionController]:
    runtime = ZeroMemRuntime.open(RuntimeConfig(capture_root=tmp_path / "c", mode=RuntimeMode.INJECT))
    ctrl = CorrectionController(runtime)
    return runtime, ctrl


def test_propose_returns_preview_without_mutation(tmp_path: Path) -> None:
    runtime, ctrl = _make_controller(tmp_path)
    try:
        target = _capture(runtime, 1)
        preview = ctrl.propose(target, CorrectionKind.CORRECTION, "fix typo", {"note": "corrected"})
        assert isinstance(preview, ProposalPreview)
        assert preview.target_event_id == target
        assert preview.kind == CorrectionKind.CORRECTION
        # propose must not append anything to canonical JSONL.
        assert runtime._last_canonical_sequence == 0
        assert runtime.health().last_canonical_sequence == 0
    finally:
        runtime.close()


def test_delete_request_tombstones_without_removing_canonical(tmp_path: Path) -> None:
    runtime, ctrl = _make_controller(tmp_path)
    try:
        target = _capture(runtime, 1)
        preview = ctrl.propose(target, CorrectionKind.DELETE_REQUEST, "no longer needed", None)
        receipt = ctrl.confirm(preview)
        assert receipt.kind == CorrectionKind.DELETE_REQUEST
        # Canonical record is NOT deleted; a tombstone control event is appended.
        lines = runtime.writer_path.read_text().splitlines()
        assert len(lines) == 2
        assert target in lines[0]
        assert "tombstone" in lines[1]
    finally:
        runtime.close()


def test_denial_does_not_leak_candidate(tmp_path: Path) -> None:
    runtime, ctrl = _make_controller(tmp_path)
    try:
        # Unknown target id -> denial with no candidate content leaked.
        preview = ctrl.propose("does-not-exist", CorrectionKind.CORRECTION, "x", {"a": 1})
        assert preview is None
        result = ctrl.confirm(None)
        assert result is None or result.status == "DENIED"
        # Nothing appended to canonical.
        assert runtime.health().last_canonical_sequence == 0
    finally:
        runtime.close()


def test_supersession_links_original_trace(tmp_path: Path) -> None:
    runtime, ctrl = _make_controller(tmp_path)
    try:
        target = _capture(runtime, 1)
        preview = ctrl.propose(target, CorrectionKind.SUPERSESSION, "updated version", {"note": "v2"})
        receipt = ctrl.confirm(preview)
        assert receipt.linked_target == target
        lines = runtime.writer_path.read_text().splitlines()
        assert len(lines) == 2
        # The control event references the superseded original (no silent overwrite).
        assert target in lines[1]
        import json
        assert json.loads(lines[1]).get("supersedes") == target
    finally:
        runtime.close()


def test_confirm_preserves_original_no_silent_overwrite(tmp_path: Path) -> None:
    runtime, ctrl = _make_controller(tmp_path)
    try:
        target = _capture(runtime, 1)
        original_line = runtime.writer_path.read_text().splitlines()[0]
        preview = ctrl.propose(target, CorrectionKind.CORRECTION, "fix typo", {"note": "corrected"})
        ctrl.confirm(preview)
        lines = runtime.writer_path.read_text().splitlines()
        # Original canonical record is byte-for-byte retained; only a linked event is added.
        assert lines[0] == original_line
        assert len(lines) == 2
        assert lines[1].startswith("{") and '"control_event":true' in lines[1]
    finally:
        runtime.close()


def test_skill_lifecycle_capture_does_not_rewrite_skill_md(tmp_path: Path) -> None:
    # V124-04 Skills pillar: Zero-Mem observes skill lifecycles but must never own or
    # rewrite Hermes SKILL.md definitions. Assert no .md under the capture root is written
    # or mutated by the sidecar during capture + correction.
    runtime, ctrl = _make_controller(tmp_path)
    try:
        target = _capture(runtime, 1)
        ctrl.propose(target, CorrectionKind.CORRECTION, "x", {"note": "y"})
        # Scan capture root for any markdown file (sidecar must not emit SKILL.md etc.).
        md_files = list(runtime.writer_path.parent.rglob("*.md"))
        assert md_files == [], f"sidecar wrote unexpected markdown: {md_files}"
    finally:
        runtime.close()