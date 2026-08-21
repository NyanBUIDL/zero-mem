"""V124-04 — HITL correction lifecycle over the runtime-owned topology.

Inspect -> propose -> preview -> explicit confirm -> append linked control event
-> rebuild projection. Control events APPEND to canonical JSONL (never overwrite);
recovery is one-way via rebuild_from_jsonl (ADR-009). Denial leaks nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from src.capture.adapter import normalize_event
from src.capture.event_types import EventType
from src.redaction import redact_payload


class CorrectionKind(str, Enum):
    CORRECTION = "correction"
    SUPERSESSION = "supersession"
    DELETE_REQUEST = "delete_request"


@dataclass(frozen=True)
class ProposalPreview:
    target_event_id: str
    kind: CorrectionKind
    rationale: str
    payload: Mapping[str, Any] | None


@dataclass(frozen=True)
class CorrectionReceipt:
    status: str
    kind: CorrectionKind | None = None
    linked_target: str | None = None
    control_event_id: str | None = None


class CorrectionController:
    """Controlled HITL correction lifecycle for the Zero-Mem sidecar.

    Operates on the runtime-owned topology: canonical writer + derived projection.
    propose() is side-effect-free; confirm() appends a linked control event and
    rebuilds the derived store. No canonical record is overwritten or deleted.
    """

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    def propose(
        self,
        target_event_id: str,
        kind: CorrectionKind,
        rationale: str,
        payload: Mapping[str, Any] | None,
    ) -> ProposalPreview | None:
        # No mutation. Deny unknown target without leaking candidate content.
        if not target_event_id or not self._target_exists(target_event_id):
            return None
        return ProposalPreview(
            target_event_id=target_event_id,
            kind=kind,
            rationale=rationale,
            payload=payload,
        )

    def confirm(self, preview: ProposalPreview | None) -> CorrectionReceipt:
        if preview is None:
            return CorrectionReceipt(status="DENIED")
        # Build a validated control-event envelope directly (normalize_event would strip the
        # linkage fields into sanitized_content). validate_envelope tolerates extra top-level
        # keys, so the supersession/tombstone linkage survives at the canonical top level.
        safe = redact_payload(payload=dict(preview.payload or {}))
        from datetime import datetime, timezone
        from src.capture.event_types import Confidence, LifecycleStatus, Retention, Sensitivity, VerificationStatus

        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        control_event_id = f"ctrl-{preview.target_event_id}"
        envelope = {
            "event_id": control_event_id,
            "trace_id": f"trace-{control_event_id}",
            "event_type": EventType.SYSTEM_EVENT.value,
            "source": "zero_mem.correction",
            "schema_version": 1,
            "created_at": now,
            "observed_at": now,
            "sequence": self._runtime.writer._next_sequence if hasattr(self._runtime.writer, "_next_sequence") else 0,
            "session_id": None,
            "profile_id": "zero_mem",
            "project_id": "zero_mem",
            "task_id": None,
            "turn_id": None,
            "parent_trace_id": None,
            "relation_ids": (),
            "lifecycle_status": LifecycleStatus.OBSERVED.value,
            "verification_status": VerificationStatus.NONE.value,
            "confidence": Confidence.MEDIUM.value,
            "sensitivity": Sensitivity.PRIVATE.value,
            "retention": Retention.PERSISTENT.value,
            "sanitized_content": safe.content,
            "sanitized_content_hash": safe.content_hash,
            "redaction_audit": safe.audit.to_dict(),
            # --- HITL linkage (preserved at canonical top level; no silent overwrite) ---
            "control_event": True,
            "control_kind": preview.kind.value,
            "supersedes": preview.target_event_id,
            "tombstone": preview.kind == CorrectionKind.DELETE_REQUEST,
            "rationale": preview.rationale,
        }
        result = self._runtime.writer.append(envelope)
        self._runtime.notify_append(result)
        # Derived projection is rebuildable from canonical JSONL (ADR-009). The bounded
        # projection worker ingests the new control event incrementally on flush.
        try:
            self._runtime.flush_projection(timeout=5.0)
        except Exception:
            pass
        return CorrectionReceipt(
            status="APPENDED",
            kind=preview.kind,
            linked_target=preview.target_event_id,
            control_event_id=result.event_id,
        )

    def _target_exists(self, target_event_id: str) -> bool:
        store = self._runtime.writer
        try:
            return store.contains_event_id(target_event_id)
        except Exception:
            return False
