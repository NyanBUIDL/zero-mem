"""M5.4 — policy audit foundation (zm_policy_audit derived projection).

Canonical source for persistent audit: ``policy_decision`` JSONL events (a SEPARATE
canonical stream from the memory store being queried). The SQLite ``zm_policy_audit``
table is a DERIVED, disposable projection created by migration v8.

Scope (plan §15 / directive "zm_policy_audit"):
- M5.4 persists ONLY DENY decisions and grant-using (ALLOW via an explicit grant)
  decisions through this emitter. It does NOT turn every ordinary memory READ into a
  persistent audit mutation. Ordinary M3/M4 READ stays read-only with respect to the
  memory store being queried.
- The auditor never logs secrets, raw payloads, or unrestricted local paths. It
  records only audit-safe metadata (decision_id, operation, requester, target_scope,
  allow, reason_code, grant_refs, provenance).

No LLM, no network. The emitter is best-effort and never raises into the policy path.
"""

from __future__ import annotations

import json
from typing import Any, Callable, List, Optional

# Event types that carry audit weight in M5.4 (plan §15).
_AUDITABLE_ALLOW_REASON_PREFIXES = (
    "ALLOW_EXPLICIT_CROSS_PROFILE_READ",
    "ALLOW_EXPLICIT_CROSS_PROFILE_WRITE",
)


def _should_audit(decision: Any) -> bool:
    """M5.4 scope: audit DENY and grant-using ALLOW only (not ordinary local READ)."""
    if not getattr(decision, "allow", True):
        return True
    reason = getattr(decision, "reason_code", "") or ""
    return any(reason.startswith(p) for p in _AUDITABLE_ALLOW_REASON_PREFIXES)


def record_decision(canonical_writer: Callable[[dict], None],
                    decision,
                    *,
                    decision_id: str,
                    requester: Optional[str],
                    target_scope: str,
                    trace_id: Optional[str] = None,
                    session_id: Optional[str] = None,
                    profile_id: Optional[str] = None,
                    source_event_id: Optional[str] = None,
                    created_at: str = "1970-01-01T00:00:00Z") -> Optional[dict]:
    """Emit a canonical ``policy_decision`` event for an auditable decision.

    Returns the emitted event dict, or None if the decision is not within M5.4 audit
    scope (so ordinary local READs are NOT persisted). Never raises into the caller.
    """
    if not _should_audit(decision):
        return None
    grant_refs = list(getattr(decision, "grant_refs", []) or [])
    event = {
        "event_id": decision_id,
        "event_type": "policy_decision",
        "trace_id": trace_id,
        "session_id": session_id,
        "profile_id": profile_id,
        "created_at": created_at,
        "m4": {
            "domain": "policy_decision",
            "decision_id": decision_id,
            "operation": getattr(decision.normalized_scope, "operation", "READ"),
            "requester": requester or "",
            "target_scope": target_scope,
            "allow": bool(decision.allow),
            "reason_code": decision.reason_code,
            "grant_refs": grant_refs,
            "source_event_id": source_event_id,
        },
    }
    try:
        canonical_writer(event)
    except Exception:
        # Best-effort: audit failure must never break the policy decision.
        return None
    return event


def project_policy_decision(conn, event: dict) -> None:
    """Project one canonical ``policy_decision`` event into ``zm_policy_audit``.

    Idempotent (PK = decision_id). Caller manages the transaction.
    """
    m4 = event.get("m4") or {}
    if m4.get("domain") != "policy_decision":
        return
    cur = conn.cursor()
    grant_refs = m4.get("grant_refs")
    grant_refs_json = json.dumps(grant_refs, sort_keys=True) if isinstance(grant_refs, list) else None
    cur.execute(
        """
        INSERT INTO zm_policy_audit (
            decision_id, operation, requester, target_scope, allow, reason_code,
            grant_refs, source_event_id, trace_id, session_id, profile_id, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(decision_id) DO UPDATE SET
            operation=excluded.operation,
            requester=excluded.requester,
            target_scope=excluded.target_scope,
            allow=excluded.allow,
            reason_code=excluded.reason_code,
            grant_refs=excluded.grant_refs,
            source_event_id=excluded.source_event_id,
            trace_id=excluded.trace_id,
            session_id=excluded.session_id,
            profile_id=excluded.profile_id,
            created_at=excluded.created_at
        """,
        (
            m4.get("decision_id"),
            m4.get("operation"),
            m4.get("requester"),
            m4.get("target_scope"),
            int(bool(m4.get("allow"))),
            m4.get("reason_code"),
            grant_refs_json,
            m4.get("source_event_id"),
            event.get("trace_id"),
            event.get("session_id"),
            event.get("profile_id"),
            event.get("created_at"),
        ),
    )


__all__ = ["record_decision", "project_policy_decision", "_should_audit"]
