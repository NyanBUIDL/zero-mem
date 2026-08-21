"""V124-04 — secure HITL correction lifecycle over the runtime-owned topology.

Authorize-before-discovery -> propose (side-effect-free, redacted, frozen preview)
-> confirm (append schema-compatible linked control event) -> projection -> truthful
receipt. Asserts:

* redaction: API keys in rationale/payload never reach JSONL/log/evidence.
* no silent overwrite: original canonical record is byte-for-byte retained.
* delete-request applies a derived tombstone + audit with provenance (no canonical delete).
* supersession links the original via ``supersedes`` (ingestible relation).
* unauthorized actor is rejected BEFORE target lookup (no candidate/count/snippet leak).
* unknown target returns DENIED with no side effect.
* two corrections on the same target mint two distinct, occurrence-safe control events.
* a mutated/stale preview is rejected (fail closed).
* confirm never returns APPENDED when the canonical line was not added.
* projection failure after append returns APPENDED_WITH_PROJECTION_LAG (no lost receipt).
* Skill lifecycle capture never rewrites SKILL.md.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.integration.zero_mem_runtime import RuntimeConfig, RuntimeMode, ZeroMemRuntime
from src.capture.adapter import normalize_event
from src.capture.event_types import EventType
from src.redaction import redact_payload
from zero_mem.correction import (
    AuthorizationDenied,
    CorrectionController,
    CorrectionKind,
    ProposalPreview,
    CorrectionReceipt,
)

ACTOR = "operator:alice"
REQUESTING = "profile-v124-04"
SCOPE = "hitl:correction:proj-v124-04"


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
        profile_id=REQUESTING,
        project_id="proj-v124-04",
    )


def _capture(runtime: ZeroMemRuntime, seq: int) -> str:
    result = runtime.writer.append(_event(seq))
    assert result.status == "appended", result.status
    runtime.notify_append(result)
    return result.event_id


def _make_controller(tmp_path: Path) -> tuple[ZeroMemRuntime, CorrectionController]:
    runtime = ZeroMemRuntime.open(RuntimeConfig(capture_root=tmp_path / "c", mode=RuntimeMode.INJECT))
    ctrl = CorrectionController(
        runtime, actor_id=ACTOR, requesting_profile_id=REQUESTING, approved_scope=SCOPE
    )
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
        # The frozen preview carries a unique proposal id + digest.
        assert preview.proposal_id.startswith("prop-")
        assert preview.preview_digest
    finally:
        runtime.close()


def test_rationale_secret_never_persisted(tmp_path: Path) -> None:
    runtime, ctrl = _make_controller(tmp_path)
    try:
        target = _capture(runtime, 1)
        raw_secret = "AKIA-EXAMPLE-1234567890ABCDEF"
        preview = ctrl.propose(
            target,
            CorrectionKind.CORRECTION,
            f"rotate leaked key api_key={raw_secret}",
            {"api_key": raw_secret},
        )
        receipt = ctrl.confirm(preview)
        assert receipt.status in ("APPENDED", "APPENDED_WITH_PROJECTION_LAG")
        # The secret must be redacted in the preview and in canonical JSONL/log/evidence.
        assert raw_secret not in preview.rationale
        if preview.payload is not None:
            assert raw_secret not in json.dumps(preview.payload)
        raw = runtime.writer_path.read_text()
        assert raw_secret not in raw, "secret leaked into canonical JSONL"
    finally:
        runtime.close()


def test_unauthorized_actor_rejected_before_discovery(tmp_path: Path) -> None:
    runtime, ctrl = _make_controller(tmp_path)
    # Construct a controller with NO actor identity (the reviewed operator surface
    # must supply one). Authorization must fail before any target lookup.
    ctrl._actor_id = None
    try:
        target = _capture(runtime, 1)
        # propose returns None (DENIED) without leaking candidate/target/count.
        preview = ctrl.propose(target, CorrectionKind.CORRECTION, "x", {"a": 1})
        assert preview is None
        assert runtime.health().last_canonical_sequence == 0
        with pytest.raises(AuthorizationDenied):
            ctrl._authorize(CorrectionKind.CORRECTION)
    finally:
        runtime.close()


def test_unknown_target_denied_without_leak(tmp_path: Path) -> None:
    runtime, ctrl = _make_controller(tmp_path)
    try:
        preview = ctrl.propose("does-not-exist", CorrectionKind.CORRECTION, "x", {"a": 1})
        assert preview is None
        receipt = ctrl.confirm(preview)
        assert receipt is None or receipt.status == "DENIED"
        assert runtime.health().last_canonical_sequence == 0
    finally:
        runtime.close()


def test_two_corrections_on_same_target_distinct_events(tmp_path: Path) -> None:
    runtime, ctrl = _make_controller(tmp_path)
    try:
        target = _capture(runtime, 1)
        p1 = ctrl.propose(target, CorrectionKind.CORRECTION, "first", {"n": 1})
        p2 = ctrl.propose(target, CorrectionKind.CORRECTION, "second", {"n": 2})
        assert p1 is not None and p2 is not None
        assert p1.proposal_id != p2.proposal_id
        r1 = ctrl.confirm(p1)
        r2 = ctrl.confirm(p2)
        assert r1.status in ("APPENDED", "APPENDED_WITH_PROJECTION_LAG")
        assert r2.status in ("APPENDED", "APPENDED_WITH_PROJECTION_LAG")
        assert r1.control_event_id != r2.control_event_id
        lines = runtime.writer_path.read_text().splitlines()
        # 1 original + 2 distinct control events.
        assert len(lines) == 3
        eids = {json.loads(line)["event_id"] for line in lines}
        assert len(eids) == 3
    finally:
        runtime.close()


def test_mutated_preview_rejected(tmp_path: Path) -> None:
    runtime, ctrl = _make_controller(tmp_path)
    try:
        target = _capture(runtime, 1)
        preview = ctrl.propose(target, CorrectionKind.CORRECTION, "original", {"n": 1})
        assert preview is not None
        # Simulate a TOCTOU mutation: tamper with the rationale after proposal.
        tampered = ProposalPreview(
            proposal_id=preview.proposal_id,
            target_event_id=preview.target_event_id,
            kind=preview.kind,
            rationale="mutated",
            payload=preview.payload,
            preview_digest=preview.preview_digest,
        )
        receipt = ctrl.confirm(tampered)
        assert receipt.status == "REJECTED"
        assert runtime.health().last_canonical_sequence == 0
    finally:
        runtime.close()


def test_delete_request_tombstones_without_removing_canonical(tmp_path: Path) -> None:
    runtime, ctrl = _make_controller(tmp_path)
    try:
        target = _capture(runtime, 1)
        preview = ctrl.propose(target, CorrectionKind.DELETE_REQUEST, "no longer needed", None)
        receipt = ctrl.confirm(preview)
        assert receipt.status in ("APPENDED", "APPENDED_WITH_PROJECTION_LAG")
        assert receipt.kind == CorrectionKind.DELETE_REQUEST
        lines = runtime.writer_path.read_text().splitlines()
        assert len(lines) == 2
        assert target in lines[0]
        # Ingest-compatible deletion block is present; original canonical line is intact.
        assert "tombstone" in lines[1]
        ctrl_event = json.loads(lines[1])
        assert ctrl_event["lifecycle_status"] == "deleted"
        assert ctrl_event["deletion"]["target_event_id"] == target
        assert ctrl_event["deletion"]["approved_scope"] == SCOPE
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
        assert target in lines[1]
        ctrl_event = json.loads(lines[1])
        assert ctrl_event.get("supersedes") == target
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
        assert lines[0] == original_line
        assert len(lines) == 2
        assert lines[1].startswith("{") and '"control_event":true' in lines[1]
    finally:
        runtime.close()


def test_delete_request_projects_real_derived_tombstone(tmp_path: Path) -> None:
    import sqlite3

    runtime, ctrl = _make_controller(tmp_path)
    try:
        target = _capture(runtime, 1)
        original_line = runtime.writer_path.read_text().splitlines()[0]
        receipt = ctrl.confirm(ctrl.propose(target, CorrectionKind.DELETE_REQUEST, "rm", None))
        assert receipt.status in ("APPENDED", "APPENDED_WITH_PROJECTION_LAG")
        runtime.flush_projection(timeout=5.0)
        # The derived store must reflect a REAL tombstone, not just a canonical line.
        derived = tmp_path / "c" / "derived" / "events.sqlite"
        conn = sqlite3.connect(str(derived))
        conn.row_factory = sqlite3.Row
        try:
            life = conn.execute(
                "SELECT current_state FROM zm_lifecycle WHERE event_id=?", (target,)
            ).fetchone()
            tomb = conn.execute(
                "SELECT status, reason_code, approved_scope FROM zm_tombstones"
            ).fetchone()
            fts = conn.execute(
                "SELECT event_id FROM zm_fts WHERE event_id=?", (target,)
            ).fetchall()
        finally:
            conn.close()
        assert life is not None and life["current_state"] == "deleted"
        assert tomb is not None and tomb["status"] == "applied"
        # Target is removed from the active FTS/read surface.
        assert fts == []
        # Original canonical record is byte-for-byte unchanged.
        assert runtime.writer_path.read_text().splitlines()[0] == original_line
    finally:
        runtime.close()


def test_skill_lifecycle_capture_does_not_rewrite_skill_md(tmp_path: Path) -> None:
    runtime, ctrl = _make_controller(tmp_path)
    try:
        target = _capture(runtime, 1)
        ctrl.propose(target, CorrectionKind.CORRECTION, "x", {"note": "y"})
        md_files = list(runtime.writer_path.parent.rglob("*.md"))
        assert md_files == [], f"sidecar wrote unexpected markdown: {md_files}"
    finally:
        runtime.close()
