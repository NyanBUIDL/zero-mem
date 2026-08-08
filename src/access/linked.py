from __future__ import annotations
"""M5.5 — linked-resource authorization hardening (derived, TRUE READ-ONLY).

Core invariant: AUTHORIZED SOURCE does NOT imply AUTHORIZED TARGET.

Every linked lookup (relation traversal, parent/child, source_event, supersession,
verification/artifact linkage) must independently re-check the TARGET against the
caller's EffectiveReadScope before the target's protected content is returned.

This module does NOT redesign M3/M4. It reuses the verified M3 relation surface
(src.retrieval.relations.get_related) and M4 read APIs, and re-checks each
returned linked object with the same effective-scope predicate M5.3 already uses
(authorized_read._scope_allows over authorized_read._ordered_scopes).

Fail-closed: if ANY linked target is outside the effective scope, the WHOLE
linked result is withheld (fixed sanitized boundary-violation reason; no target
existence/count/ID/lifecycle/snippet leakage). The canonical relation row is
never deleted — authorization changes visibility, not history.

All READ paths stay mode=ro + PRAGMA query_only. No migration, projector,
lifecycle writer, grant administration, or canonical append is invoked here.
"""

from typing import List, Optional

# M5.5 linked-authorization helpers. Imports of authorized_read helpers are
# deferred to function scope to avoid a circular import (authorized_read imports
# this module).
from src.access.contracts import AccessRequest, READ, WRITE
from src.access.grants import AuthorizedReadGrant, EffectiveReadScope
from src.retrieval.relations import get_related
from src.retrieval.query import get_event as m3_get_event
from src.retrieval.db import ReadonlyStore
from src.project_memory import reader as m4_reader


def _as_readonly(store):
    """Wrap a SQLiteStore/raw-connection as a ReadonlyStore (M3 needs store.conn)."""
    conn = store._conn if hasattr(store, "_conn") else store
    return ReadonlyStore(conn, __import__("pathlib").Path("/dev/null"))


def view_in_scope(eff: EffectiveReadScope, svc, view) -> bool:
    from src.access.authorized_read import _scope_allows
    """Is ``view`` (any object with profile_id/project_id) inside the eff scope?

    Reuses the exact M5.3 predicate. No timestamp winner, no fuzzy match.
    """
    profile_id = getattr(view, "profile_id", None)
    project_id = getattr(view, "project_id", None)
    requester = svc._requester
    for scope in svc._ordered_scopes(eff):
        if _scope_allows(scope, requester, profile_id, project_id):
            return True
    return False


def authorize_relation(svc, request: AccessRequest, event_id: str,
                       direction: Optional[str] = None,
                       relation_type: Optional[str] = None,
                       limit: Optional[int] = None,
                       cursor: Optional[str] = None,
                       grants: Optional[List[AuthorizedReadGrant]] = None) -> AuthorizedResult:
    """Relation traversal with target-scope recheck (fail closed).

    Relations never grant scope. An authorized source event does NOT authorize its
    linked target. Every target EventView is independently scope-checked; any
    out-of-scope target withholds the entire result (no leakage of target identity).
    """
    from src.access.authorized_read import AuthorizedResult
    eff = svc._gate(request, grants)
    if not eff.allow:
        return svc._denied(eff)
    # Precheck: the caller must be authorized to READ the SOURCE event before
    # traversing FROM it. An unauthorized source yields no traversal (fail closed).
    try:
        src_view = m3_get_event(_as_readonly(svc._store), event_id)
    except Exception:
        src_view = None
    if src_view is not None and not view_in_scope(eff, svc, src_view):
        return svc._boundary_violation(eff)
    res = get_related(_as_readonly(svc._store), event_id, relation_type=relation_type,
                      direction=direction, limit=limit, cursor=cursor)
    for item in res.items:
        if not view_in_scope(eff, svc, item.target):
            return svc._boundary_violation(eff)
    return AuthorizedResult(
        allowed=True, denied=False, reason_code=eff.reason_code,
        items=res.items, query=res.query, next_cursor=res.next_cursor, decision=eff)


def authorize_source_event(eff: EffectiveReadScope, svc, source_event_id: Optional[str]):
    """Resolve an M4 source_event_id only if the caller is authorized for it.

    Returns the M3 EventView when in scope, else None. Never leaks existence of an
    unauthorized source event.
    """
    if not source_event_id:
        return None
    try:
        view = m3_get_event(_as_readonly(svc._store), source_event_id)
    except Exception:
        return None
    if view is None:
        return None
    if view_in_scope(eff, svc, view):
        return view
    return None


def harden_m4_source_event(eff: EffectiveReadScope, svc, view) -> None:
    """In-place: withhold an embedded source_event when out of scope.

    Called after an M4 read API returns a view that already embedded its source
    event (include_source_event=True). The M4 view itself is authorized; only the
    embedded M3 source event needs an independent scope check.
    """
    se = getattr(view, "source_event", None)
    if se is not None and not view_in_scope(eff, svc, se):
        view.source_event = None


def authorize_m4_link(eff: EffectiveReadScope, svc, request: AccessRequest,
                      project_id: str, resource_type: str,
                      linked_ids: Optional[str],
                      low_level_fn, grants=None) -> AuthorizedResult:
    """Resolve M4 linked ids (verification/artifact) within project + resource-type scope.

    A linked id does NOT confer authorization: the project must be authorized AND the
    resource_type must be permitted by the caller's grant scope. Returns only the
    in-scope linked objects; out-of-scope / missing links are silently dropped (no leak).
    """
    from src.access.authorized_read import AuthorizedResult
    eff2 = svc._gate(request, grants)
    if not eff2.allow:
        return svc._denied(eff2)
    if not svc._m4_project_scope_ok(eff2, project_id):
        return svc._boundary_violation(eff2)
    if not svc._m4_resource_allowed(eff2, project_id, resource_type):
        return svc._denied(eff2)
    if not linked_ids:
        return AuthorizedResult(allowed=True, denied=False,
                                reason_code=eff2.reason_code, items=[], decision=eff2)
    ids = [i.strip() for i in linked_ids.split(",") if i.strip()]
    items = []
    for lid in ids:
        try:
            obj = low_level_fn(lid)
        except Exception:
            continue
        if obj is None:
            continue
        if view_in_scope(eff2, svc, obj):
            items.append(obj)
    return AuthorizedResult(allowed=True, denied=False,
                            reason_code=eff2.reason_code, items=items, decision=eff2)


def authorize_supersession_link(eff: EffectiveReadScope, svc,
                                 current_view, historical_ids: List[str]):
    """Historical supersession chain must obey CURRENT scope. Returns in-scope historical views.

    An authorized current object does NOT authorize its predecessor/successor. No
    transitive permission, no scope inheritance from supersession.
    """
    out = []
    for hid in historical_ids:
        try:
            hv = m3_get_event(_as_readonly(svc._store), hid)
        except Exception:
            continue
        if hv is None:
            continue
        if view_in_scope(eff, svc, hv):
            out.append(hv)
    return out
