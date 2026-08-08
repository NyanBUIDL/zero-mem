"""M5.4 — trusted control-plane grant administration (separate policy surface).

This module implements the TRUSTED GRANT-ADMIN SURFACE (plan §11.6). It is
deliberately separate from the normal `AccessRequest` READ/WRITE policy surface:

- A normal `AccessRequest` can NEVER reach this code. There is no `mode='admin'`
  parameter, no field on `AccessRequest` that triggers grant administration, and
  no function that converts an `AccessRequest` into a `GrantAdminRequest`.
- The ONLY way to administer grants is to call `GrantAdminService` methods
  directly. Authority comes from *entering this boundary* (the hosting/control
  plane decides who may invoke it), NOT from any caller-supplied claim.
- `GrantAdminRequest` carries NO `trusted` / `is_admin` / `grant_admin` /
  `allow_grant_creation` / `verified` authority-bearing field. Adding such a
  field would be a security defect and is intentionally absent.

Canonical authority: the trusted entrypoint appends a canonical `access_grant`
JSONL event (the source of truth) and projects it into the derived
`zm_access_grants` table. SQLite is never canonical.

No LLM, no network. WRITE grants require a verified M4 verification record
(resolved read-only).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .contracts import READ, WRITE
from .grant_events import (
    AccessGrantEvent,
    GRANT_OP_CREATE,
    GRANT_OP_REVOKE,
    GRANT_OP_SUPERSEDE,
    project_grant_event,
)

# Canonical writer type: takes one canonical event dict and appends it.
CanonicalWriter = Callable[[dict], None]


@dataclass
class GrantAdminRequest:
    """Typed trusted control-plane request (plan §11.6 / directive GrantAdminRequest).

    NOTE: there is intentionally NO `trusted` / `is_admin` / `grant_admin` /
    `allow_grant_creation` / `verified` field. Authority is conferred by entering
    the trusted control-plane boundary (calling `GrantAdminService`), not by any
    payload claim.
    """

    action: str                              # CREATE | REVOKE | SUPERSEDE
    grant_id: str
    subject_profile: str
    operation: str                           # READ | WRITE
    target_type: str                        # profile | project | knowledge_space | global
    target_id: str
    resource_types: Optional[List[str]] = None
    verification_ref: Optional[str] = None
    supersedes: Optional[str] = None
    # provenance
    event_id: str = ""
    trace_id: Optional[str] = None
    session_id: Optional[str] = None
    profile_id: Optional[str] = None
    project_id: Optional[str] = None
    created_at: str = ""
    source_event_id: Optional[str] = None

    _VALID_ACTIONS = (GRANT_OP_CREATE, GRANT_OP_REVOKE, GRANT_OP_SUPERSEDE)

    def validate(self) -> "GrantAdminRequest":
        if self.action not in self._VALID_ACTIONS:
            raise ValueError(f"invalid grant-admin action: {self.action!r}")
        if not self.grant_id:
            raise ValueError("grant_id is required")
        if self.operation not in (READ, WRITE):
            raise ValueError(f"invalid operation: {self.operation!r}")
        if self.target_type not in ("profile", "project", "knowledge_space", "global"):
            raise ValueError(f"invalid target_type: {self.target_type!r}")
        if not self.target_id:
            raise ValueError("target_id is required")
        if self.action == GRANT_OP_REVOKE and self.supersedes is not None:
            raise ValueError("revoke must not carry supersedes")
        if self.action == GRANT_OP_SUPERSEDE and not self.supersedes:
            raise ValueError("supersede requires supersedes")
        if self.action == GRANT_OP_SUPERSEDE and self.supersedes == self.grant_id:
            raise ValueError("self-supersession is not allowed")
        if self.action == GRANT_OP_CREATE and self.supersedes is not None:
            raise ValueError("create must not carry supersedes")
        return self

    def to_event(self) -> AccessGrantEvent:
        self.validate()
        return AccessGrantEvent(
            grant_id=self.grant_id,
            subject_profile=self.subject_profile,
            operation=self.operation,
            target_type=self.target_type,
            target_id=self.target_id,
            op=self.action,
            resource_types=self.resource_types,
            state=None,
            lifecycle_status="active",
            supersedes=self.supersedes,
            replaced_by=None,
            verification_ref=self.verification_ref,
            source_event_id=self.source_event_id,
            created_at=self.created_at or "1970-01-01T00:00:00Z",
            event_id=self.event_id or f"grant-{self.grant_id}-{self.action}",
            trace_id=self.trace_id,
            session_id=self.session_id,
            profile_id=self.profile_id,
            project_id=self.project_id,
        )


class GrantAdminService:
    """Trusted control-plane entrypoint for grant administration.

    Structural separation guarantee: this class is NEVER invoked by the normal
    policy surface (`evaluate`, `compose_effective_scope`, `query_events`,
    `authorize_write`). Those take `AccessRequest` only.
    """

    def __init__(
        self,
        conn,
        canonical_writer: CanonicalWriter,
        verification_lookup: Optional[Callable[[str], Optional[object]]] = None,
    ) -> None:
        """Initialize the trusted grant-admin service.

        - ``conn``: writable SQLite connection to the derived grant store
          (``zm_access_grants``). The caller (control plane) supplies it; an
          ordinary AccessRequest flow never does.
        - ``canonical_writer``: appends the canonical access_grant JSONL event
          (the trusted boundary). Injected; never derived from request claims.
        - ``verification_lookup``: ``verification_ref -> VerificationView | None``
          resolved READ-ONLY from the M4 substrate (required for WRITE grants).
        """
        self._conn = conn
        self._writer = canonical_writer
        self._verify = verification_lookup

    # ------------------------------------------------------------------
    # Trusted operations (each is an explicit control-plane entrypoint)
    # ------------------------------------------------------------------
    def create(self, req: GrantAdminRequest) -> dict:
        req.validate()
        event = req.to_event()
        # WRITE verification predicate (plan §11.3): verification_ref required and
        # the referenced M4 verification must be READ-ONLY verified.
        if event.operation == WRITE:
            self._require_verified(event.verification_ref)
        project_grant_event(self._conn, event)
        self._conn.commit()
        self._writer(event.to_canonical_dict())
        return {"action": "CREATE", "grant_id": req.grant_id, "status": "ok"}

    def revoke(self, req: GrantAdminRequest) -> dict:
        if req.action != GRANT_OP_REVOKE:
            raise ValueError("revoke() requires action=REVOKE")
        req.validate()
        event = AccessGrantEvent(
            grant_id=req.grant_id,
            subject_profile=req.subject_profile,
            operation=req.operation,
            target_type=req.target_type,
            target_id=req.target_id,
            op=GRANT_OP_REVOKE,
            state="revoked",               # domain state, never lifecycle
            lifecycle_status="active",     # preserved for audit visibility
            created_at=req.created_at or "1970-01-01T00:00:00Z",
            event_id=req.event_id or f"grant-{req.grant_id}-revoke",
            trace_id=req.trace_id, session_id=req.session_id,
            profile_id=req.profile_id, project_id=req.project_id,
        )
        project_grant_event(self._conn, event)
        self._conn.commit()
        self._writer(event.to_canonical_dict())
        return {"action": "REVOKE", "grant_id": req.grant_id, "status": "ok"}

    def supersede(self, req: GrantAdminRequest) -> dict:
        if req.action != GRANT_OP_SUPERSEDE:
            raise ValueError("supersede() requires action=SUPERSEDE")
        req.validate()
        event = req.to_event()
        if event.operation == WRITE:
            self._require_verified(event.verification_ref)
        project_grant_event(self._conn, event)
        self._conn.commit()
        self._writer(event.to_canonical_dict())
        return {"action": "SUPERSEDE", "grant_id": req.grant_id,
                "supersedes": req.supersedes, "status": "ok"}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _require_verified(self, verification_ref: Optional[str]) -> None:
        if not verification_ref:
            raise ValueError("WRITE grant requires verification_ref")
        if self._verify is None:
            raise ValueError("verification lookup unavailable")
        rec = self._verify(verification_ref)
        if rec is None:
            raise ValueError("verification_ref does not resolve")
        status = getattr(rec, "verification_status", None)
        if status != "verified":
            raise ValueError("verification is not in verified state")


__all__ = ["GrantAdminRequest", "GrantAdminService"]
