"""M5.4 — deterministic grant resolution from the derived ``zm_access_grants``.

This module is the RESOLUTION layer. It reads structured policy state only (never
fuzzy text, never semantic similarity, never relations, never timestamps to pick a
"winner"). It produces VALIDATED internal authorization objects
(``AuthorizedReadGrant``) that the M5.3 machinery already trusts.

Resolution rules (plan §11.5 / directive "Grant authorization predicate"):
- grant.operation == request.operation
- grant.lifecycle_status == active
- grant.state != revoked
- target scope matches EXACTLY
- requested resource_type is covered
- grant is not conflicted/deleted/superseded/archived/raw/observed/candidate/confirmed
- WRITE: verification_ref resolves READ-ONLY to a verified M4 record

No timestamp winner. No LLM. No network. Deterministic.

The resolver never writes; it is pure read of the derived projection.
"""

from __future__ import annotations

import json
from typing import Callable, List, Optional, Tuple

from .contracts import READ, WRITE
from .grants import AuthorizedReadGrant

# Only lifecycle_status == active authorizes (plan §11.5). Everything else is
# non-authorizing (terminal or pre-active).
_AUTHORIZING_LIFECYCLE = {"active"}


def _parse_resource_types(raw: Optional[str]) -> Optional[List[str]]:
    if raw is None:
        return None
    try:
        val = json.loads(raw)
        return list(val) if isinstance(val, list) else None
    except (ValueError, TypeError):
        return None


def _row_to_read_grant(row) -> AuthorizedReadGrant:
    """Convert a zm_access_grants row into a validated AuthorizedReadGrant."""
    return AuthorizedReadGrant(
        grant_id=row["grant_id"],
        subject_profile=row["subject_profile"],
        operation=row["operation"],
        target_type=row["target_type"],
        target_id=row["target_id"],
        resource_types=_parse_resource_types(row["resource_types"]),
        state=row["state"],
        lifecycle_status=row["lifecycle_status"],
        supersedes=row["supersedes"],
        verification_ref=row["verification_ref"],
        source_event_id=row["source_event_id"],
        created_at=row["created_at"],
    )


def resolve_read_grants(conn, requesting_profile: Optional[str],
                        target_type: Optional[str] = None,
                        target_id: Optional[str] = None,
                        resource_type: Optional[str] = None) -> List[AuthorizedReadGrant]:
    """Resolve authorizing READ grants for ``requesting_profile`` from derived state.

    Returns validated ``AuthorizedReadGrant`` objects (one per authorizing READ
    grant). Mirrors the M5.3 pre-authorized contract exactly so the existing
    ``compose_effective_scope`` path is unchanged.

    Scope is exact: a grant only contributes when its target matches the requested
    target (when given). A profile grant B/P never authorizes B/Q; a project grant
    does not broaden to all profiles/spaces.
    """
    cur = conn.cursor()
    sql = (
        "SELECT * FROM zm_access_grants "
        "WHERE operation = 'READ' "
        "AND subject_profile = ? "
        "AND lifecycle_status = 'active' "
        "AND (state IS NULL OR state != 'revoked')"
    )
    params: list = [requesting_profile]
    if target_type is not None:
        sql += " AND target_type = ?"
        params.append(target_type)
    if target_id is not None:
        sql += " AND target_id = ?"
        params.append(target_id)
    cur.execute(sql, params)
    out: List[AuthorizedReadGrant] = []
    for row in cur.fetchall():
        g = _row_to_read_grant(row)
        # Resource-type restriction (plan §11.3): when a specific resource_type is
        # requested, the grant must cover it. None means "all".
        if resource_type is not None and not g.covers_resource(resource_type):
            continue
        out.append(g)
    return out


def _grant_authorizes_write(row, target_type: str, target_id: str,
                            resource_type: Optional[str]) -> bool:
    if row["operation"] != WRITE:
        return False
    if row["lifecycle_status"] != "active":
        return False
    if row["state"] == "revoked":
        return False
    if row["target_type"] != target_type:
        return False
    if row["target_id"] != target_id:
        return False
    if resource_type is not None:
        rts = _parse_resource_types(row["resource_types"])
        if rts is not None and resource_type not in rts:
            return False
    return True


def resolve_write_grant(conn, requesting_profile: Optional[str],
                        verification_lookup: Callable[[str], Optional[object]],
                        target_type: str, target_id: str,
                        resource_type: Optional[str] = None) -> Optional[dict]:
    """Deterministically resolve a single authorizing WRITE grant.

    Returns the matched grant dict (with ``verification_status`` added) only when
    ALL predicates pass, including the WRITE verification predicate (resolved
    READ-ONLY from the M4 substrate). Returns ``None`` otherwise.

    Conflict rule (plan §11.7): if multiple active WRITE grants match the exact
    scope, there is no deterministic narrowed single scope -> DENY (return None
    with a conflict marker). We never pick "newest" or "most permissive".
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM zm_access_grants "
        "WHERE operation = 'WRITE' AND subject_profile = ? "
        "AND lifecycle_status = 'active' "
        "AND (state IS NULL OR state != 'revoked')",
        (requesting_profile,),
    )
    candidates = [r for r in cur.fetchall()
                  if _grant_authorizes_write(r, target_type, target_id, resource_type)]
    if not candidates:
        return None
    if len(candidates) > 1:
        # Irreconcilable contradictory policy -> fail closed (DENY_POLICY_CONFLICT).
        return {"conflict": True, "grant_ids": [c["grant_id"] for c in candidates]}
    row = candidates[0]
    # WRITE verification predicate (plan §11.3): verification_ref MUST resolve to a
    # verified M4 verification record, read-only.
    vref = row["verification_ref"]
    if not vref:
        return None
    rec = verification_lookup(vref)
    if rec is None:
        return None
    status = getattr(rec, "verification_status", None)
    if status != "verified":
        return None
    return {
        "grant_id": row["grant_id"],
        "subject_profile": row["subject_profile"],
        "operation": WRITE,
        "target_type": row["target_type"],
        "target_id": row["target_id"],
        "resource_types": _parse_resource_types(row["resource_types"]),
        "state": row["state"],
        "lifecycle_status": row["lifecycle_status"],
        "verification_ref": vref,
        "verification_status": status,
        "source_event_id": row["source_event_id"],
        "conflict": False,
    }


__all__ = [
    "resolve_read_grants",
    "resolve_write_grant",
    "AuthorizedReadGrant",
]
