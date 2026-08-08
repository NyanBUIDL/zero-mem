"""M5.2 — authorized-read facade over the VERIFIED M3/M4 read surfaces.

This module integrates the M5.1 policy boundary with existing read-only retrieval.
It does NOT implement grants, schema v8, audit persistence, or WRITE authorization.

Flow (authorization-before-retrieval):
    AccessRequest
      -> M5.1 evaluate()        -> AccessDecision
      -> ALLOW: translate AllowedScope -> restrictive query filters
                 -> invoke LOW-LEVEL M3/M4 read API (store stays read-only)
                 -> DEFENSIVE post-validation: drop any record outside AllowedScope
      -> DENY:  return typed denial WITHOUT invoking any low-level query

The low-level backend is invoked only on ALLOW. Reads are TRUE READ-ONLY
(mode=ro + query_only); the facade never opens a writer/projector, never runs a
migration, never appends canonical events.

Global/default representation: in this substrate, a "global/default" record is one
with a NULL profile_id (unowned/default space). Global read for a bound caller
combines the requester's OWN profile with NULL-profile records. It NEVER exposes
another profile's records (cross-profile stays denied; see _scope_allows).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .contracts import (
    AccessDecision, AccessRequest, AllowedScope, READ, ReasonCode,
)
from .policy import evaluate

from src.retrieval.models import QueryError
from src.retrieval.query import query_events, get_event, get_trace, _build_where, _row_to_view
from src.retrieval.search import search_text
from src.storage.ingest import ZM_META_COLUMNS
from src.project_memory import reader as m4


# ---------------------------------------------------------------------------
# Typed policy-aware result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AuthorizedResult:
    """Distinguishes allowed+results, allowed+zero, denied, invalid, downstream error.

    A DENY is never disguised as results=[]/error=None. Denials carry a fixed
    reason_code and NO protected existence information.
    """

    allowed: bool
    denied: bool
    reason_code: str
    items: List[Any] = field(default_factory=list)
    query: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None          # sanitized downstream error (distinct from DENY)
    decision: Optional[AccessDecision] = None
    next_cursor: Optional[str] = None

    @property
    def is_invalid(self) -> bool:
        return self.reason_code == ReasonCode.DENY_INVALID_REQUEST.value

    @property
    def is_downstream_error(self) -> bool:
        return self.error is not None and not self.denied


# ---------------------------------------------------------------------------
# Scope translation (authorization-before-query)
# ---------------------------------------------------------------------------

def _profile_predicate(scope: AllowedScope,
                        requester: Optional[str]) -> Tuple[Optional[str], List[str]]:
    """Restrictive profile SQL predicate (prefixed for zm_meta).

    - scoped profiles: 'zm_meta.profile_id IN (...)'
    - global read: 'requester OR zm_meta.profile_id IS NULL' (unowned/default only;
      never another profile)
    - unbound + global: 'zm_meta.profile_id IS NULL' only
    - implicit local (no global, no explicit profile): own profile only
    - fail-closed fallback: '1=0'

    Returns (clause_or_None, params). None means the low-level API already
    enforces scope via profile_id equality; the clause is AND-ed otherwise.
    """
    profiles = list(scope.allowed_profile_ids)
    if scope.global_read_allowed:
        if requester is not None:
            if profiles:
                combined = sorted(set(profiles + [requester]))
                ph = ",".join("?" * len(combined))
                return (f"(zm_meta.profile_id IN ({ph}) OR zm_meta.profile_id IS NULL)", combined)
            return ("(zm_meta.profile_id = ? OR zm_meta.profile_id IS NULL)", [requester])
        # unbound + global => global/default (NULL profile) only
        return ("zm_meta.profile_id IS NULL", [])
    if profiles:
        ph = ",".join("?" * len(profiles))
        return (f"zm_meta.profile_id IN ({ph})", profiles)
    if requester is not None:
        return ("zm_meta.profile_id = ?", [requester])
    return ("1=0", [])


def _project_predicate(scope: AllowedScope) -> Tuple[Optional[str], List[str]]:
    if scope.allowed_project_ids:
        ph = ",".join("?" * len(scope.allowed_project_ids))
        return (f"zm_meta.project_id IN ({ph})", list(scope.allowed_project_ids))
    return (None, [])


def _scope_allows(scope: AllowedScope, requester: Optional[str],
                  profile_id: Optional[str], project_id: Optional[str]) -> bool:
    """Defensive post-validation: is (profile_id, project_id) inside AllowedScope?

    The requesting profile always owns its own data (implicit-local / global both
    include the requester's profile). Global read additionally permits NULL-profile
    (unowned/default) records. Cross-profile records are ALWAYS denied.
    """
    allowed_profiles = set(scope.allowed_profile_ids)
    if requester is not None:
        allowed_profiles.add(requester)
    if scope.global_read_allowed:
        proj_ok = (project_id in scope.allowed_project_ids) if scope.allowed_project_ids else True
        if profile_id is None:
            return proj_ok                       # global/default unowned record
        if profile_id in allowed_profiles:
            return proj_ok                       # requester's own profile
        return False                            # cross-profile: DENIED even under global
    if profile_id is None:
        return False
    if profile_id not in allowed_profiles:
        return False
    if scope.allowed_project_ids:
        if project_id is None or project_id not in scope.allowed_project_ids:
            return False
    return True


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------

class AuthorizedReadService:
    """Gates M3/M4 reads behind the M5.1 policy. Store is used read-only."""

    def __init__(self, store, requesting_profile_id: Optional[str]) -> None:
        self._store = store
        self._requester = requesting_profile_id

    # -- policy gate --------------------------------------------------------
    def _gate(self, request: AccessRequest) -> AccessDecision:
        return evaluate(request)

    def _denied(self, decision: AccessDecision) -> AuthorizedResult:
        return AuthorizedResult(allowed=False, denied=True,
                                reason_code=decision.reason_code, decision=decision)

    def _downstream(self, decision: AccessDecision, error: str) -> AuthorizedResult:
        return AuthorizedResult(allowed=True, denied=False, reason_code=decision.reason_code,
                               error=error, decision=decision)

    def _boundary_violation(self, decision: AccessDecision) -> AuthorizedResult:
        return AuthorizedResult(allowed=False, denied=True,
                                reason_code=ReasonCode.DENY_ISOLATED_SCOPE_ESCAPE.value,
                                decision=decision)

    # -- M3 structured ------------------------------------------------------
    def _select_m3(self, scope: AllowedScope, limit: Optional[int],
                   profile_filter: Optional[str] = None,
                   project_filter: Optional[str] = None,
                   session_filter: Optional[str] = None,
                   verification_filter: Optional[str] = None,
                   lifecycle_filter: Optional[str] = None,
                   created_at_after: Optional[str] = None,
                   created_at_before: Optional[str] = None) -> List[Any]:
        from src.retrieval.models import QueryRequest
        from src.retrieval.query import _validate_limit, cursor_mod
        extra = QueryRequest(
            project_id=project_filter,
            session_id=session_filter,
            verification_status=verification_filter,
            lifecycle_status=lifecycle_filter,
            created_at_after=created_at_after,
            created_at_before=created_at_before,
        )
        where, params = _build_where(extra)
        p_clause, p_params = _profile_predicate(scope, self._requester)
        if p_clause:
            where = where + " AND " + p_clause
            params = params + p_params
        eff_limit = _validate_limit(limit)
        cols = ",".join(ZM_META_COLUMNS)
        sql = (f"SELECT {cols} FROM zm_meta WHERE {where} "
               f"ORDER BY created_at ASC, event_id ASC LIMIT ?")
        params.append(eff_limit)
        rows = self._store.conn.execute(sql, params).fetchall()
        return [_row_to_view(r) for r in rows]

    def query_events(self, request: AccessRequest,
                     profile_filter: Optional[str] = None,
                     project_filter: Optional[str] = None,
                     session_filter: Optional[str] = None,
                     verification_filter: Optional[str] = None,
                     lifecycle_filter: Optional[str] = None,
                     created_at_after: Optional[str] = None,
                     created_at_before: Optional[str] = None,
                     limit: Optional[int] = None,
                     cursor: Optional[str] = None) -> AuthorizedResult:
        decision = self._gate(request)
        if not decision.allow:
            return self._denied(decision)
        scope = decision.normalized_scope
        proj = project_filter if project_filter is not None else (
            request.project_ids[0] if request.project_ids else None)
        try:
            rows = self._select_m3(scope, limit, profile_filter=profile_filter,
                                   project_filter=proj,
                                   session_filter=session_filter,
                                   verification_filter=verification_filter,
                                   lifecycle_filter=lifecycle_filter,
                                   created_at_after=created_at_after,
                                   created_at_before=created_at_before)
        except QueryError as exc:
            return self._downstream(decision, exc.code)
        items = [v for v in rows
                 if _scope_allows(scope, self._requester, v.profile_id, v.project_id)]
        if len(items) != len(rows):
            return self._boundary_violation(decision)
        return AuthorizedResult(allowed=True, denied=False, reason_code=decision.reason_code,
                                items=items, query=scope.as_dict(), decision=decision)

    def get_event(self, request: AccessRequest, event_id: str) -> AuthorizedResult:
        decision = self._gate(request)
        if not decision.allow:
            return self._denied(decision)
        scope = decision.normalized_scope
        try:
            view = get_event(self._store, event_id)
        except QueryError as exc:
            return self._downstream(decision, exc.code)
        if view is None:
            return AuthorizedResult(allowed=True, denied=False,
                                    reason_code=decision.reason_code,
                                    items=[], decision=decision)
        if not _scope_allows(scope, self._requester, view.profile_id, view.project_id):
            return self._boundary_violation(decision)
        return AuthorizedResult(allowed=True, denied=False,
                                reason_code=decision.reason_code,
                                items=[view], decision=decision)

    def get_trace(self, request: AccessRequest, trace_id: str) -> AuthorizedResult:
        decision = self._gate(request)
        if not decision.allow:
            return self._denied(decision)
        scope = decision.normalized_scope
        try:
            views = get_trace(self._store, trace_id)
        except QueryError as exc:
            return self._downstream(decision, exc.code)
        items = [v for v in views
                 if _scope_allows(scope, self._requester, v.profile_id, v.project_id)]
        if len(items) != len(views):
            return self._boundary_violation(decision)
        return AuthorizedResult(allowed=True, denied=False,
                                reason_code=decision.reason_code,
                                items=items, decision=decision)

    # -- M3 FTS -------------------------------------------------------------
    def search_text(self, request: AccessRequest, text: str,
                    profile_filter: Optional[str] = None,
                    project_filter: Optional[str] = None,
                    session_filter: Optional[str] = None,
                    verification_filter: Optional[str] = None,
                    limit: Optional[int] = None,
                    cursor: Optional[str] = None) -> AuthorizedResult:
        decision = self._gate(request)
        if not decision.allow:
            return self._denied(decision)
        scope = decision.normalized_scope
        from src.retrieval.models import QueryRequest
        # SQL-level restriction: when scoped, pin to the requester; under global the
        # SQL is broader but the defensive post-validation below keeps only
        # NULL-profile (global/default) and requester-owned hits.
        if scope.allowed_profile_ids and not scope.global_read_allowed:
            eff_profile = scope.allowed_profile_ids[0]
        elif self._requester is not None and not scope.global_read_allowed:
            eff_profile = self._requester
        else:
            eff_profile = profile_filter  # global: rely on post-validation
        eff_project = project_filter if project_filter is not None else (
            request.project_ids[0] if request.project_ids else None)
        req = QueryRequest(
            profile_id=eff_profile,
            project_id=eff_project,
            session_id=session_filter,
            verification_status=verification_filter,
        )
        try:
            res = search_text(self._store, text, req=req, limit=limit, cursor=cursor)
        except QueryError as exc:
            return self._downstream(decision, exc.code)
        if res.error is not None:
            return AuthorizedResult(allowed=True, denied=False,
                                   reason_code=decision.reason_code,
                                   error=res.error, decision=decision)
        items = [h for h in res.results
                 if _scope_allows(scope, self._requester, h.profile_id, h.project_id)]
        if len(items) != len(res.results):
            return self._boundary_violation(decision)
        return AuthorizedResult(allowed=True, denied=False, reason_code=decision.reason_code,
                                items=items, next_cursor=res.next_cursor, decision=decision)

    # -- M4 (project-memory) ------------------------------------------------
    def _m4_project_scope_ok(self, decision: AccessDecision, project_id: Optional[str]) -> bool:
        """M4 reads are project-scoped; the project must be explicitly authorized.

        Global read has no well-defined 'global project' in M4, so cross-project
        reads stay DENIED unless the project is in allowed_project_ids.
        """
        scope = decision.normalized_scope
        if project_id is None:
            return False
        return project_id in scope.allowed_project_ids

    def m4_charter(self, request: AccessRequest, project_id: str,
                   charter_id: Optional[str] = None,
                   include_source_event: bool = False) -> AuthorizedResult:
        decision = self._gate(request)
        if not decision.allow:
            return self._denied(decision)
        if not self._m4_project_scope_ok(decision, project_id):
            return self._boundary_violation(decision)
        try:
            view = m4.get_project_charter(self._store, project_id, charter_id=charter_id,
                                          include_source_event=include_source_event)
        except QueryError as exc:
            return self._downstream(decision, exc.code)
        if view is None:
            return AuthorizedResult(allowed=True, denied=False,
                                    reason_code=decision.reason_code, decision=decision)
        if not _scope_allows(decision.normalized_scope, self._requester,
                             view.profile_id, view.project_id):
            return self._boundary_violation(decision)
        return AuthorizedResult(allowed=True, denied=False,
                                reason_code=decision.reason_code,
                                items=[view], decision=decision)

    def _m4_list(self, request: AccessRequest, project_id: str,
                 low_level_fn: Callable[[], Any]) -> AuthorizedResult:
        decision = self._gate(request)
        if not decision.allow:
            return self._denied(decision)
        if not self._m4_project_scope_ok(decision, project_id):
            return self._boundary_violation(decision)
        try:
            res = low_level_fn()
        except QueryError as exc:
            return self._downstream(decision, exc.code)
        # get_current_project_state returns a plain list; list_* return ProjectMemoryResult.
        if hasattr(res, "items"):
            source_items = res.items
            query = res.query
            next_cursor = res.next_cursor
        else:
            source_items = res
            query = {}
            next_cursor = None
        allowed = [v for v in source_items
                   if _scope_allows(decision.normalized_scope, self._requester,
                                   getattr(v, "profile_id", None),
                                   getattr(v, "project_id", None))]
        if len(allowed) != len(source_items):
            return self._boundary_violation(decision)
        return AuthorizedResult(allowed=True, denied=False,
                                reason_code=decision.reason_code,
                                items=allowed, query=query,
                                next_cursor=next_cursor, decision=decision)

    def m4_requirements(self, request: AccessRequest, project_id: str,
                        limit: Optional[int] = None,
                        cursor: Optional[str] = None) -> AuthorizedResult:
        return self._m4_list(request, project_id,
                             lambda: m4.list_requirements(self._store, project_id,
                                                          limit=limit, cursor=cursor))

    def m4_decisions(self, request: AccessRequest, project_id: str,
                     limit: Optional[int] = None,
                     cursor: Optional[str] = None) -> AuthorizedResult:
        return self._m4_list(request, project_id,
                             lambda: m4.list_decisions(self._store, project_id,
                                                       limit=limit, cursor=cursor))

    def m4_current_state(self, request: AccessRequest, project_id: str) -> AuthorizedResult:
        return self._m4_list(request, project_id,
                             lambda: m4.get_current_project_state(self._store, project_id))

    def m4_verifications(self, request: AccessRequest, project_id: str,
                         limit: Optional[int] = None,
                         cursor: Optional[str] = None) -> AuthorizedResult:
        return self._m4_list(request, project_id,
                             lambda: m4.list_verifications(self._store, project_id,
                                                          limit=limit, cursor=cursor))

    def m4_artifacts(self, request: AccessRequest, project_id: str,
                     limit: Optional[int] = None,
                     cursor: Optional[str] = None) -> AuthorizedResult:
        return self._m4_list(request, project_id,
                             lambda: m4.list_project_artifacts(self._store, project_id,
                                                              limit=limit, cursor=cursor))


__all__ = ["AuthorizedReadService", "AuthorizedResult",
           "_profile_predicate", "_project_predicate", "_scope_allows"]
