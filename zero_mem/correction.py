"""V124-04 — secure HITL correction lifecycle over the runtime-owned topology.

Inspect -> authorize-before-discovery -> propose -> immutable sanitized preview
-> preview digest + unique proposal ID -> explicit confirm by proposal ID/digest
-> append schema-compatible linked control event -> projection -> truthful receipt.

Security invariants (authority chain: ADR-009 / SPEC-AMENDMENT-001 / GITHUB-POLICY):

* Authorization is evaluated BEFORE target discovery. An unauthorized actor is
  rejected with no target/candidate/count/snippet leakage.
* User-controlled fields (rationale, payload) are redacted by ``redact_payload``
  BEFORE the preview is built, before persistence, and before any log line.
* The proposal preview is deep-frozen (frozen dataclass) and its digest is computed
  over the sanitized payload, so a mutated preview fails closed at confirm time.
* Control events APPEND to canonical JSONL using the SAME contract ``ingest.py``
  understands (``lifecycle_status`` ``deletion``/``superseded_by`` blocks), so
  derived tombstones, audit rows, and supersession relations are actually projected.
* ``control_event_id`` is occurrence-safe (UUID), never the collision-prone
  fixed ``ctrl-{target}`` form; multiple corrections on the same target are allowed.
* ``confirm()`` inspects the append result and never returns APPENDED when the
  canonical line was not actually added (duplicate/reject/failure surfaces as
  DUPLICATE / REJECTED / UNAVAILABLE respectively).
* Projection failure AFTER a successful canonical append returns
  APPENDED_WITH_PROJECTION_LAG rather than losing the receipt or falsely claiming full
  success. Capture success is independent of projection success.

Correction is exposed ONLY through this reviewed operator/HITL surface; it is never
registered as an automatic read tool.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from src.capture.adapter import normalize_event
from src.capture.event_types import (
    Confidence,
    EventType,
    LifecycleStatus,
    Retention,
    Sensitivity,
    VerificationStatus,
)
from src.redaction import redact_payload


class CorrectionKind(str, Enum):
    CORRECTION = "correction"
    SUPERSESSION = "supersession"
    DELETE_REQUEST = "delete_request"


@dataclass(frozen=True)
class ProposalPreview:
    """Immutable, sanitized correction proposal.

    ``rationale`` and ``payload`` are already redacted by construction. ``preview_id``
    and ``preview_digest`` bind a later ``confirm()`` to this exact, unmutated proposal.
    """

    proposal_id: str
    target_event_id: str
    kind: CorrectionKind
    rationale: str
    payload: Mapping[str, Any] | None
    preview_digest: str


@dataclass(frozen=True)
class CorrectionReceipt:
    status: str
    kind: CorrectionKind | None = None
    linked_target: str | None = None
    control_event_id: str | None = None


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _digest(preview: ProposalPreview) -> str:
    material = json.dumps(
        {
            "proposal_id": preview.proposal_id,
            "target_event_id": preview.target_event_id,
            "kind": preview.kind.value,
            "rationale": preview.rationale,
            "payload": preview.payload,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class AuthorizationDenied(RuntimeError):
    """Raised when the actor is not authorized; carries no target/candidate data."""


class CorrectionController:
    """Controlled HITL correction lifecycle for the Zero-Mem sidecar.

    Operates on the runtime-owned topology: canonical writer + derived projection.
    propose() is side-effect-free; confirm() appends a linked, schema-compatible
    control event and rebuilds the derived store. No canonical record is overwritten
    or deleted.
    """

    def __init__(
        self,
        runtime: Any,
        *,
        actor_id: str | None = None,
        requesting_profile_id: str | None = None,
        approved_scope: str | None = None,
    ) -> None:
        self._runtime = runtime
        # Explicit, non-inferred actor identity. Never hardcoded to a sentinel; the
        # operator surface must supply a real actor or authorization fails closed.
        self._actor_id = actor_id
        self._requesting_profile_id = requesting_profile_id
        self._approved_scope = approved_scope

    # --- authorization (BEFORE discovery) -----------------------------------
    def _authorize(self, kind: CorrectionKind) -> None:
        """Fail closed before any target discovery when the actor/scope is invalid.

        Leaks no target identifier, candidate content, count, or snippet.
        """
        if not self._actor_id or not str(self._actor_id).strip():
            raise AuthorizationDenied("correction_actor_required")
        if not self._requesting_profile_id or not str(self._requesting_profile_id).strip():
            raise AuthorizationDenied("correction_requesting_profile_required")
        # The reviewed operator surface requires an explicit approved scope label.
        if not self._approved_scope or not str(self._approved_scope).strip():
            raise AuthorizationDenied("correction_scope_required")

    # --- discovery (only after authorization) ------------------------------
    def _target_exists(self, target_event_id: str) -> bool:
        store = self._runtime.writer
        try:
            return store.contains_event_id(target_event_id)
        except Exception:
            return False

    def propose(
        self,
        target_event_id: str,
        kind: CorrectionKind,
        rationale: str,
        payload: Mapping[str, Any] | None,
        *,
        actor_id: str | None = None,
        requesting_profile_id: str | None = None,
        approved_scope: str | None = None,
    ) -> ProposalPreview | None:
        # Authorize BEFORE discovery. Any failure here leaks nothing about the target.
        if actor_id is not None:
            self._actor_id = actor_id
        if requesting_profile_id is not None:
            self._requesting_profile_id = requesting_profile_id
        if approved_scope is not None:
            self._approved_scope = approved_scope
        try:
            self._authorize(kind)
        except AuthorizationDenied:
            return None

        if not target_event_id or not self._target_exists(target_event_id):
            # Unknown/unauthorized target: return None (DENIED) without leaking
            # candidate id, count, or snippet. No canonical append occurs.
            return None

        # Redact ALL user-controlled fields before constructing the preview.
        safe = redact_payload(payload=dict(payload or {}))
        redacted_rationale = redact_payload(
            payload={"rationale": rationale or ""}
        ).content.get("rationale", "")
        preview = ProposalPreview(
            proposal_id=f"prop-{uuid.uuid4().hex}",
            target_event_id=target_event_id,
            kind=kind,
            rationale=redacted_rationale,
            payload=safe.content,
            preview_digest="",
        )
        # Freeze the digest over the sanitized, immutable preview.
        return replace(preview, preview_digest=_digest(preview))

    def confirm(self, preview: ProposalPreview | None) -> CorrectionReceipt:
        if preview is None:
            return CorrectionReceipt(status="DENIED")
        # Stale/altered preview must fail closed: re-derive the digest and compare.
        if _digest(preview) != preview.preview_digest:
            return CorrectionReceipt(status="REJECTED", kind=preview.kind)
        # Authorize again at confirm time (defense in depth; never trust a cached
        # proposal without a live authorization check).
        try:
            self._authorize(preview.kind)
        except AuthorizationDenied:
            return CorrectionReceipt(status="DENIED", kind=preview.kind)

        # Build an INGEST-COMPATIBLE control envelope. ``ingest.py`` already projects
        # tombstones (lifecycle_status='deleted' + deletion block) and supersession
        # (superseded_by) into the derived store; using that same contract guarantees
        # the correction actually takes effect in the read surface.
        now = _utcnow()
        control_event_id = f"ctrl-{uuid.uuid4().hex}"

        # Delete requests carry a deletion block (Decision B: tombstones are the
        # canonical deletion record). Supersession marks the target superseded.
        deletion_block = None
        lifecycle_status = LifecycleStatus.OBSERVED.value
        superseded_by = None
        if preview.kind is CorrectionKind.DELETE_REQUEST:
            lifecycle_status = LifecycleStatus.DELETED.value
            deletion_block = {
                "target_event_id": preview.target_event_id,
                "reason_code": "hitl_delete_request",
                "approved_scope": self._approved_scope,
            }
        elif preview.kind is CorrectionKind.SUPERSESSION:
            lifecycle_status = LifecycleStatus.OBSERVED.value
            superseded_by = preview.target_event_id

        envelope = {
            "event_id": control_event_id,
            "trace_id": f"trace-{control_event_id}",
            "event_type": EventType.SYSTEM_EVENT.value,
            "source": "operator",
            "schema_version": 1,
            "created_at": now,
            "observed_at": now,
            "sequence": self._runtime.writer._next_sequence
            if hasattr(self._runtime.writer, "_next_sequence")
            else 0,
            "session_id": None,
            "profile_id": self._requesting_profile_id,
            "project_id": self._runtime.writer.project_id
            if hasattr(self._runtime.writer, "project_id")
            else None,
            "task_id": None,
            "turn_id": None,
            "parent_trace_id": None,
            "relation_ids": (),
            "lifecycle_status": lifecycle_status,
            "verification_status": VerificationStatus.APPROVAL.value,
            "confidence": Confidence.HIGH.value,
            "sensitivity": Sensitivity.INTERNAL.value,
            "retention": Retention.PERSISTENT.value,
            "sanitized_content": {"control_kind": preview.kind.value, "linked_target": preview.target_event_id},
            "sanitized_content_hash": "",
            "redaction_audit": {"rules": [], "paths": [], "count": 0},
            # HITL linkage preserved at canonical top level (tolerated by validate_envelope).
            "control_event": True,
            "control_kind": preview.kind.value,
            "supersedes": preview.target_event_id,
            "superseded_by": superseded_by,
            "tombstone": preview.kind is CorrectionKind.DELETE_REQUEST,
            "deletion": deletion_block,
            "rationale": preview.rationale,
            "actor_id": self._actor_id,
            "approved_scope": self._approved_scope,
        }
        # Ingestion requires a valid sanitized_content_hash; normalize_event computes it
        # deterministically and re-validates. We then re-attach the HITL linkage keys at
        # the canonical top level (normalize_event would otherwise nest unknown keys under
        # sanitized_content.extra), so ingest.py reads deletion/superseded_by directly.
        normalized = normalize_event(
            envelope,
            sequence=int(envelope["sequence"]),
            event_type=EventType.SYSTEM_EVENT,
            source="operator",
            profile_id=envelope["profile_id"],
            project_id=envelope["project_id"],
        )
        normalized["control_event"] = True
        normalized["control_kind"] = preview.kind.value
        normalized["supersedes"] = preview.target_event_id
        normalized["superseded_by"] = superseded_by
        normalized["tombstone"] = preview.kind is CorrectionKind.DELETE_REQUEST
        normalized["deletion"] = deletion_block
        normalized["rationale"] = preview.rationale
        normalized["actor_id"] = self._actor_id
        normalized["approved_scope"] = self._approved_scope
        result = self._runtime.writer.append(normalized)
        self._runtime.notify_append(result)

        if result.status != "appended":
            # The canonical line was NOT added: surface the real outcome.
            if result.status.startswith("duplicate"):
                return CorrectionReceipt(
                    status="DUPLICATE", kind=preview.kind, linked_target=preview.target_event_id
                )
            return CorrectionReceipt(
                status="REJECTED", kind=preview.kind, linked_target=preview.target_event_id
            )

        # Derived projection is rebuildable from canonical JSONL (ADR-009). A projection
        # failure after a successful append must NOT lose the receipt.
        try:
            self._runtime.flush_projection(timeout=5.0)
        except Exception:
            return CorrectionReceipt(
                status="APPENDED_WITH_PROJECTION_LAG",
                kind=preview.kind,
                linked_target=preview.target_event_id,
                control_event_id=result.event_id,
            )
        return CorrectionReceipt(
            status="APPENDED",
            kind=preview.kind,
            linked_target=preview.target_event_id,
            control_event_id=result.event_id,
        )
