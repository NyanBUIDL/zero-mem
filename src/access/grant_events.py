"""M5.4 — canonical access_grant event model + derived projection.

Canonical source: append-only JSONL `access_grant` events (the same lightweight
canonical convention used by M4 events: top-level event envelope + an `m4` block).
SQLite `zm_access_grants` is a DERIVED, disposable, rebuildable projection.

Grant lifecycle / domain-state separation (plan §11.4):
- `lifecycle_status` uses ONLY the authoritative closed enum.
- `state` is a generic domain column; `state='revoked'` is the revocation
  representation (NOT a lifecycle value). `revoked` must never appear in
  `lifecycle_status`.
- Supersession is explicit: a newer grant with `supersedes=<old>`; the old row is
  set `lifecycle_status='superseded'` + `replaced_by=<new>`.

No timestamp winner, no semantic inference, no LLM, no network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .contracts import READ, WRITE

# Operation + target literals (plan §11.1).
_GRANT_OPERATIONS = (READ, WRITE)
_GRANT_TARGET_TYPES = ("profile", "project", "knowledge_space", "global")

# Authoritative closed lifecycle enum (master spec §7.1).
_LIFECYCLE_ENUM = {
    "raw", "observed", "candidate", "confirmed",
    "active", "superseded", "conflicted", "archived", "deleted",
}

# Grant mutation ops (plan §11.1).
GRANT_OP_CREATE = "create"
GRANT_OP_REVOKE = "revoke"
GRANT_OP_SUPERSEDE = "supersede"


@dataclass
class AccessGrantEvent:
    """Canonical structured access-grant event (plan §11.1 contract).

    This is the SOURCE OF TRUTH. The `m4` payload mirrors the plan contract.
    `op` is one of create/supersede/revoke. Provenance fields (event_id,
    trace_id, session_id, profile_id, project_id) are recorded verbatim.
    """

    grant_id: str
    subject_profile: str
    operation: str                       # READ | WRITE
    target_type: str                    # profile | project | knowledge_space | global
    target_id: str                      # profile/project/space id, or "*"
    op: str                             # create | supersede | revoke
    resource_types: Optional[List[str]] = None
    state: Optional[str] = None         # generic domain state; "revoked" => withdrawn
    lifecycle_status: str = "active"
    supersedes: Optional[str] = None
    replaced_by: Optional[str] = None
    verification_ref: Optional[str] = None
    source_event_id: Optional[str] = None
    created_at: str = ""
    # provenance
    event_id: str = ""
    trace_id: Optional[str] = None
    session_id: Optional[str] = None
    profile_id: Optional[str] = None
    project_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Validation (pure; deterministic; no I/O)
    # ------------------------------------------------------------------
    def validate(self) -> "AccessGrantEvent":
        if not self.grant_id or not isinstance(self.grant_id, str):
            raise ValueError("grant_id is required and must be a string")
        if self.operation not in _GRANT_OPERATIONS:
            raise ValueError(f"invalid operation: {self.operation!r}")
        if self.target_type not in _GRANT_TARGET_TYPES:
            raise ValueError(f"invalid target_type: {self.target_type!r}")
        if not self.target_id or not isinstance(self.target_id, str):
            raise ValueError("target_id is required")
        if self.op not in (GRANT_OP_CREATE, GRANT_OP_REVOKE, GRANT_OP_SUPERSEDE):
            raise ValueError(f"invalid grant op: {self.op!r}")
        if self.lifecycle_status not in _LIFECYCLE_ENUM:
            raise ValueError(f"invalid lifecycle_status: {self.lifecycle_status!r}")
        if self.op == GRANT_OP_CREATE and self.supersedes is not None:
            raise ValueError("create must not carry supersedes")
        if self.op == GRANT_OP_SUPERSEDE and not self.supersedes:
            raise ValueError("supersede requires supersedes (explicit old grant)")
        if self.op == GRANT_OP_SUPERSEDE and self.supersedes == self.grant_id:
            raise ValueError("self-supersession is not allowed")
        if self.op == GRANT_OP_REVOKE and self.supersedes is not None:
            raise ValueError("revoke must not carry supersedes")
        # WRITE requires a verification_ref (enforced at the admin boundary too,
        # but the event model rejects a malformed WRITE event without one).
        if self.operation == WRITE and self.op == GRANT_OP_CREATE and not self.verification_ref:
            raise ValueError("WRITE grant requires verification_ref")
        return self

    # ------------------------------------------------------------------
    # Canonical JSONL serialization (lightweight M4-style envelope)
    # ------------------------------------------------------------------
    def to_canonical_dict(self) -> dict:
        self.validate()
        m4 = {
            "domain": "access_grant",
            "identity": self.grant_id,
            "op": self.op,
            "grant_id": self.grant_id,
            "subject_profile": self.subject_profile,
            "operation": self.operation,
            "target_type": self.target_type,
            "target_id": self.target_id,
        }
        if self.resource_types is not None:
            m4["resource_types"] = list(self.resource_types)
        if self.state is not None:
            m4["state"] = self.state
        m4["lifecycle_status"] = self.lifecycle_status
        if self.supersedes is not None:
            m4["supersedes"] = self.supersedes
        if self.replaced_by is not None:
            m4["replaced_by"] = self.replaced_by
        if self.verification_ref is not None:
            m4["verification_ref"] = self.verification_ref
        if self.source_event_id is not None:
            m4["source_event_id"] = self.source_event_id
        return {
            "event_id": self.event_id or f"grant-{self.grant_id}-{self.op}",
            "event_type": "access_grant",
            "project_id": self.project_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "profile_id": self.profile_id,
            "created_at": self.created_at,
            "m4": m4,
        }

    @classmethod
    def from_canonical_dict(cls, d: dict) -> "AccessGrantEvent":
        """Parse a canonical access_grant JSONL line into a structured event.

        Generic prose / non-grant events are rejected (returns None) so an
        assistant saying 'give B access' can NEVER become a grant.
        """
        if not isinstance(d, dict):
            return None
        m4 = d.get("m4")
        if not isinstance(m4, dict):
            return None
        if m4.get("domain") != "access_grant":
            return None
        op = m4.get("op")
        if op not in (GRANT_OP_CREATE, GRANT_OP_REVOKE, GRANT_OP_SUPERSEDE):
            return None
        grant_id = m4.get("grant_id") or m4.get("identity")
        if not grant_id:
            return None
        return cls(
            grant_id=grant_id,
            subject_profile=m4.get("subject_profile", ""),
            operation=m4.get("operation", READ),
            target_type=m4.get("target_type", ""),
            target_id=m4.get("target_id", ""),
            op=op,
            resource_types=m4.get("resource_types"),
            state=m4.get("state"),
            lifecycle_status=m4.get("lifecycle_status", "active"),
            supersedes=m4.get("supersedes"),
            replaced_by=m4.get("replaced_by"),
            verification_ref=m4.get("verification_ref"),
            source_event_id=m4.get("source_event_id"),
            created_at=d.get("created_at", ""),
            event_id=d.get("event_id", ""),
            trace_id=d.get("trace_id"),
            session_id=d.get("session_id"),
            profile_id=d.get("profile_id"),
            project_id=d.get("project_id"),
        )


# ---------------------------------------------------------------------------
# Derived projection: canonical access_grant event -> zm_access_grants
# ---------------------------------------------------------------------------

def _serialize_resource_types(resource_types: Optional[List[str]]) -> Optional[str]:
    if resource_types is None:
        return None
    import json
    return json.dumps(list(resource_types), sort_keys=True)


def project_grant_event(conn, event: AccessGrantEvent) -> None:
    """Apply one canonical access_grant event to the derived projection.

    Idempotent, transaction-safe (caller manages the transaction). Deterministic.

    - create:    upsert the grant row (PK = grant_id).
    - revoke:    set state='revoked' on the existing row (history preserved; no
                 physical deletion). Non-authorizing thereafter.
    - supersede: insert/replace the new grant row; mark the old grant
                 lifecycle_status='superseded' + replaced_by=new_id.
    """
    event.validate()
    cur = conn.cursor()
    if event.op == GRANT_OP_CREATE:
        cur.execute(
            """
            INSERT INTO zm_access_grants (
                grant_id, subject_profile, operation, target_type, target_id,
                resource_types, state, lifecycle_status, supersedes, replaced_by,
                verification_ref, source_event_id, trace_id, session_id,
                profile_id, project_id, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(grant_id) DO UPDATE SET
                subject_profile=excluded.subject_profile,
                operation=excluded.operation,
                target_type=excluded.target_type,
                target_id=excluded.target_id,
                resource_types=excluded.resource_types,
                state=excluded.state,
                lifecycle_status=excluded.lifecycle_status,
                supersedes=excluded.supersedes,
                replaced_by=excluded.replaced_by,
                verification_ref=excluded.verification_ref,
                source_event_id=excluded.source_event_id,
                trace_id=excluded.trace_id,
                session_id=excluded.session_id,
                profile_id=excluded.profile_id,
                project_id=excluded.project_id,
                created_at=excluded.created_at
            """,
            (
                event.grant_id, event.subject_profile, event.operation,
                event.target_type, event.target_id,
                _serialize_resource_types(event.resource_types), event.state,
                event.lifecycle_status, event.supersedes, event.replaced_by,
                event.verification_ref, event.source_event_id, event.trace_id,
                event.session_id, event.profile_id, event.project_id,
                event.created_at,
            ),
        )
    elif event.op == GRANT_OP_REVOKE:
        cur.execute(
            "UPDATE zm_access_grants SET state='revoked' WHERE grant_id=?",
            (event.grant_id,),
        )
    elif event.op == GRANT_OP_SUPERSEDE:
        # Insert/replace the NEW grant FIRST so the old row's replaced_by FK
        # (pointing at the new grant_id) is already valid, then mark the old
        # grant superseded. This preserves both records (no physical deletion).
        cur.execute(
            """
            INSERT INTO zm_access_grants (
                grant_id, subject_profile, operation, target_type, target_id,
                resource_types, state, lifecycle_status, supersedes, replaced_by,
                verification_ref, source_event_id, trace_id, session_id,
                profile_id, project_id, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(grant_id) DO UPDATE SET
                subject_profile=excluded.subject_profile,
                operation=excluded.operation,
                target_type=excluded.target_type,
                target_id=excluded.target_id,
                resource_types=excluded.resource_types,
                state=excluded.state,
                lifecycle_status=excluded.lifecycle_status,
                supersedes=excluded.supersedes,
                replaced_by=excluded.replaced_by,
                verification_ref=excluded.verification_ref,
                source_event_id=excluded.source_event_id,
                trace_id=excluded.trace_id,
                session_id=excluded.session_id,
                profile_id=excluded.profile_id,
                project_id=excluded.project_id,
                created_at=excluded.created_at
            """,
            (
                event.grant_id, event.subject_profile, event.operation,
                event.target_type, event.target_id,
                _serialize_resource_types(event.resource_types), event.state,
                event.lifecycle_status, event.supersedes, event.replaced_by,
                event.verification_ref, event.source_event_id, event.trace_id,
                event.session_id, event.profile_id, event.project_id,
                event.created_at,
            ),
        )
        if event.supersedes:
            cur.execute(
                "UPDATE zm_access_grants "
                "SET lifecycle_status='superseded', replaced_by=? "
                "WHERE grant_id=?",
                (event.grant_id, event.supersedes),
            )


def rebuild_grants(conn, events) -> None:
    """Replay an ordered sequence of canonical grant events (idempotent)."""
    for raw in events:
        ev = raw if isinstance(raw, AccessGrantEvent) else AccessGrantEvent.from_canonical_dict(raw)
        if ev is None:
            continue
        project_grant_event(conn, ev)


__all__ = [
    "AccessGrantEvent",
    "GRANT_OP_CREATE", "GRANT_OP_REVOKE", "GRANT_OP_SUPERSEDE",
    "project_grant_event", "rebuild_grants",
]
