"""M5.2/M5.3 — authorized-read facade over the VERIFIED M3/M4 read surfaces.

Integrates the M5.1 policy boundary and M5.3 explicit cross-profile READ
composition with existing read-only retrieval. It does NOT implement grants (M5.4), schema v8 (M5.4), audit persistence, or WRITE
authorization (M5.4). M5.5 linked-resource hardening lives in src/access/linked.py and
is wired here via get_related/get_parent/get_children/get_incoming/get_outgoing and
source-event/verification/artifact link re-checks.

Flow (authorization-before-retrieval):
    AccessRequest
      -> compose_effective_scope()  -> EffectiveReadScope
      -> ALLOW: decompose into restrictive per-scope queries (base + per grant)
                -> invoke LOW-LEVEL M3/M4 read API (store stays read-only)
                -> DEFENSIVE post-validation: drop any record outside any scope
      -> DENY:  return typed denial WITHOUT invoking any low-level query

The low-level backend is invoked only on ALLOW. Reads are TRUE READ-ONLY
(mode=ro + query_only); the facade never opens a writer/projector, never runs a
migration, never appends canonical events.

Global/default representation: a "global/default" record is one with a NULL
profile_id (unowned/default space). Global read for a bound caller combines the
requester's OWN profile with NULL-profile records; it NEVER exposes another
profile's records unless an explicit grant authorizes that profile/project.

Decomposition: an EffectiveReadScope is a ``base`` AllowedScope (profile+project
AND-restrictive, per M5.1) plus zero or more per-grant atomic scopes. Each grant
scope is independently restrictive:
  - profile grant  -> profile_id IN (target)
  - project grant  -> project_id IN (target), profile UNRESTRICTED (a project read
                      grant authorizes reading that project across profiles)
  - space grant     -> knowledge_space IN (target)
Results from each restrictive query are merged and de-duplicated; post-validation
guarantees no record outside any authorized scope survives.
"""

from __future__ import annotations

import sqlite3

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .contracts import (
    AccessDecision, AccessRequest, AllowedScope, READ, ReasonCode,
)
from .grants import AuthorizedReadGrant, EffectiveReadScope, compose_effective_scope
from .policy import evaluate
from . import linked as _linked

from src.retrieval.models import QueryError
from src.retrieval.query import query_events, get_event, get_trace, _build_where, _row_to_view, _validate_limit
from src.retrieval.search import search_text
from src.retrieval.cursor import make_fingerprint, encode_cursor, validate_cursor_binding, DEFAULT_LIMIT, MAX_LIMIT
from src.storage.ingest import ZM_META_COLUMNS
from src.project_memory import reader as m4


_validate_limit_safe = _validate_limit


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
    decision: Optional[Any] = None
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
    - project/space-only grant scope: None (profile UNRESTRICTED; project/space
      clause enforces the boundary)

    Returns (clause_or_None, params). None means no profile restriction is applied
    (caller relies on the project/space clause).
    """
    profiles = list(scope.allowed_profile_ids)
    if scope.global_read_allowed:
        if requester is not None:
            if profiles:
                combined = sorted(set(profiles + [requester]))
                ph = ",".join("?" * len(combined))
                return (f"(zm_meta.profile_id IN ({ph}) OR zm_meta.profile_id IS NULL)", combined)
            return ("(zm_meta.profile_id = ? OR zm_meta.profile_id IS NULL)", [requester])
        return ("zm_meta.profile_id IS NULL", [])
    if profiles:
        ph = ",".join("?" * len(profiles))
        return (f"zm_meta.profile_id IN ({ph})", profiles)
    # DEF-028 (DEF-A1): ONLY per-grant atomic scopes are profile-unrestricted
    # (their project/space clause enforces the boundary). A base/policy scope
    # carrying project/space ids (e.g. a caller-requested knowledge-space
    # filter) must NOT drop the profile restriction — fall through to the
    # requester-scoped clauses below.
    if scope.is_grant:
        return (None, [])
    # Implicit-local base scope (no explicit profile, no grant): restrict to the
    # requester's own profile only (M5.2 semantics restored).
    if requester is not None:
        return ("zm_meta.profile_id = ?", [requester])
    return (None, [])


def _project_predicate(scope: AllowedScope) -> Tuple[Optional[str], List[str]]:
    if scope.allowed_project_ids:
        ph = ",".join("?" * len(scope.allowed_project_ids))
        return (f"zm_meta.project_id IN ({ph})", list(scope.allowed_project_ids))
    return (None, [])


def _ks_predicate(scope: AllowedScope) -> Tuple[Optional[str], List[str]]:
    """V1.6.0 C4 (ADR-V160-01 sec7): per-row knowledge-space SQL predicate.

    Correlated EXISTS on the multi-KS junction zm_event_spaces - never a
    direct JOIN, so an event [A,B] matching a UNION [A,B] appears EXACTLY once.
    A row is authorized when grant intersects row KS set != empty; NULL/empty-KS
    rows have no junction rows and are never matched (fail-closed). The SQL
    layer is the authorization boundary; _scope_allows re-checks defensively.
    """
    if scope.allowed_knowledge_space_ids:
        ph = ",".join("?" * len(scope.allowed_knowledge_space_ids))
        # C4 review (P1): the junction is the ONLY authorization source for
        # event-path space grants. A row whose junction rows are missing/
        # deleted/corrupt is NEVER matched (fail-closed) - the legacy singular
        # zm_meta.knowledge_space_id is NOT a fallback (proper legacy goes
        # through the v13 migration backfill, which creates junction rows).
        return (f"EXISTS (SELECT 1 FROM zm_event_spaces s "
                f"WHERE s.event_id = zm_meta.event_id "
                f"AND s.knowledge_space_id IN ({ph}))",
                list(scope.allowed_knowledge_space_ids))
    return (None, [])


def _scope_allows(scope: AllowedScope, requester: Optional[str],
                  profile_id: Optional[str], project_id: Optional[str],
                  row_knowledge_space_ids: Optional[Iterable[str]] = None,
                  row_knowledge_space_id: Optional[str] = None) -> bool:
    """Defensive post-validation: is (profile_id, project_id, ks) inside scope?

    - global read permits NULL-profile (unowned/default) records.
    - profile-grant / base scope: profile membership is REQUIRED (and project, when
      scoped, is AND-restrictive). A same-profile request for project P must NOT
      expose another profile's rows in P.
    - project/space grant scope (no profile restriction): project/space membership
      alone authorizes the row across profiles (a project read grant authorizes
      reading that project regardless of which profile owns the row).
    - cross-profile rows without an explicit grant => DENIED.
    - knowledge-space grant - V1.6.0 C4 (ADR-V160-01 sec7): the row KS SET
      (from the multi-KS junction zm_event_spaces) must intersect the granted
      set (grant x row != empty); NULL/empty KS (no junction rows) is never
      authorized by a space grant, regardless of what the derived corpus
      projection claims. NULL/empty => DENY (fail-closed).
    """
    # Backward-compat alias (pre-C4 DEF-010/011/012 callers): a singular row ks
    # is treated as a one-element set; None -> empty (unscoped, fail-closed).
    if row_knowledge_space_ids is None:
        row_knowledge_space_ids = ((row_knowledge_space_id,)
                                   if row_knowledge_space_id else ())

    # Project/space grant scopes are profile-unrestricted; the project/space clause
    # enforces the boundary. For base / profile-grant / implicit-local scopes, fold
    # the requester into the allowed set so the requester's OWN data is authorized.
    # DEF-028 (DEF-A1): grant-ness comes from the explicit is_grant marker, NOT
    # from the presence of project/space ids (a base scope carrying a
    # caller-requested KS filter must stay requester-scoped).
    is_grant_scope = scope.is_grant
    allowed_profiles = set(scope.allowed_profile_ids)
    if not is_grant_scope and requester is not None:
        allowed_profiles.add(requester)
    profile_restricted = (bool(allowed_profiles) or scope.global_read_allowed)

    if scope.global_read_allowed and profile_id is None:
        proj_ok = (project_id in scope.allowed_project_ids) if scope.allowed_project_ids else True
        return proj_ok

    if profile_restricted:
        # Profile membership required; project, when scoped, is AND-restrictive.
        if profile_id not in allowed_profiles:
            return False
        if scope.allowed_project_ids:
            return project_id in scope.allowed_project_ids
        if scope.allowed_knowledge_space_ids:
            # DEF-028 parity: a base scope with a KS filter still enforces the
            # row's KS set (mirrors the SQL junction EXISTS); NULL/empty KS is
            # unscoped and never space-authorized (fail-closed).
            if not row_knowledge_space_ids:
                return False
            return bool(set(row_knowledge_space_ids)
                        & set(scope.allowed_knowledge_space_ids))
        return True

    # Grant scope with no profile restriction (project/space grant): membership suffices.
    if scope.allowed_project_ids and project_id in scope.allowed_project_ids:
        return True
    if scope.allowed_knowledge_space_ids:
        # V1.6.0 C4 (DEF-011 closed): per-row only, over the multi-KS junction.
        # grant x row KS set != empty authorizes; no resolver fallback.
        if not row_knowledge_space_ids:
            return False
        return bool(set(row_knowledge_space_ids)
                    & set(scope.allowed_knowledge_space_ids))
    return False


def _junction_ks_map(conn, event_ids: Iterable[Optional[str]]) -> Dict[str, List[str]]:
    """One-query map event_id -> junction KS list (C4 defensive re-check)."""
    ids = [e for e in event_ids if e is not None]
    if not ids:
        return {}
    ph = ",".join("?" * len(ids))
    out: Dict[str, List[str]] = {}
    rows = conn.execute(
        f"SELECT event_id, knowledge_space_id FROM zm_event_spaces "
        f"WHERE event_id IN ({ph}) "
        "ORDER BY event_id ASC, knowledge_space_id ASC", ids).fetchall()
    for r in rows:
        out.setdefault(r["event_id"], []).append(r["knowledge_space_id"])
    return out


def _attach_source_event_spaces(conn, views: Iterable[Any]) -> None:
    """Attach full junction membership to already-read M4 view objects.

    M4 records retain ``source_event_id`` but do not duplicate the event's
    Multi-KS set.  C8 resolves that derived metadata in one bounded query so
    authorization and projection consume the explicit source-event set.
    Missing junction rows attach an empty tuple and remain fail-closed.
    """
    materialized = tuple(views)
    ks_map = _junction_ks_map(
        conn, (getattr(view, "source_event_id", None) for view in materialized)
    )
    for view in materialized:
        event_id = getattr(view, "source_event_id", None)
        setattr(view, "knowledge_space_ids", tuple(ks_map.get(event_id, ())))


def _row_ks_ids(view: Any) -> Tuple[str, ...]:
    """Row KS set for the defensive check: full set, else singular, else empty."""
    ks_set = getattr(view, "knowledge_space_ids", None)
    if ks_set:
        return tuple(ks_set)
    single = getattr(view, "knowledge_space_id", None)
    return (single,) if single else ()


def _scope_predicate(scope: AllowedScope, requester: Optional[str]) -> Tuple[str, List[str]]:
    """One complete parameterized SQL predicate for a restrictive scope."""
    clauses: List[str] = []
    params: List[str] = []
    for clause, values in (_profile_predicate(scope, requester),
                           _project_predicate(scope), _ks_predicate(scope)):
        if clause:
            clauses.append(f"({clause})")
            params.extend(values)
    return (" AND ".join(clauses), params) if clauses else ("1=0", [])


def _effective_scope_predicate(eff: EffectiveReadScope,
                               requester: Optional[str]) -> Tuple[str, List[str]]:
    """OR-union complete scopes before FTS ranking/snippets/pagination."""
    parts: List[str] = []
    params: List[str] = []
    for scope in [eff.base, *eff.grant_scopes]:
        clause, values = _scope_predicate(scope, requester)
        parts.append(f"({clause})")
        params.extend(values)
    return (" OR ".join(parts), params) if parts else ("1=0", [])


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------

class AuthorizedReadService:
    """Gates M3/M4 reads behind the M5.1/M5.3 policy. Store is used read-only."""

    def __init__(self, store, requesting_profile_id: Optional[str],
                 grant_conn=None, corpus_conn=None,
                 expected_projection_digest: Optional[str] = None) -> None:
        self._store = store
        self._requester = requesting_profile_id
        # Optional writable/derived connection to zm_access_grants. When supplied,
        # persistent READ grants are resolved from canonical state (M5.4) and feed
        # the existing M5.3 compose_effective_scope path WITHOUT redesign. The
        # resolved grants are VALIDATED from their own fields (no caller trust).
        self._grant_conn = grant_conn
        # Optional read-only connection to the derived corpus DB (zm_corpus_*).
        # Supplies the DEF-004 Option B knowledge-space resolution layer: a space
        # grant is mapped to concrete (profile_id, project_id) members from corpus
        # state. When None, space grants stay fail-closed (non-authorizing).
        self._corpus_conn = corpus_conn
        # V150-WP1 (DEF-011): fail-closed integrity gate for the derived input.
        # When armed (expected digest supplied), space-member expansion only
        # proceeds if the live projection digest matches; otherwise space grants
        # stay non-authorizing (deny), never over-authorize on stale/tampered
        # derived state. Unarmed (None) preserves pre-V150 behavior for callers
        # that do not opt in yet (e.g. tests constructing the service directly).
        # V150-WP3: the EVENT path no longer consults the resolver at all
        # (per-row zm_meta.ks only); this field is retained solely for the
        # CORPUS read path (corpus_unit_search) integrity verification.
        self._projection_digest = expected_projection_digest

    def close(self) -> None:
        """Close the owned read-only store connection, if it exposes close().

        V141-R2 (DEF-014): also close the injected corpus connection so a
        long-running sidecar does not accumulate open sqlite fds across
        requests (one corpus conn per _open_facade call).
        """
        close = getattr(self._store, "close", None)
        if callable(close):
            close()
        corpus_close = getattr(self._corpus_conn, "close", None)
        if callable(corpus_close):
            try:
                corpus_close()
            except sqlite3.Error:
                pass  # already closed / driver-level failure must not mask the read result
            self._corpus_conn = None

    # -- policy gate --------------------------------------------------------
    def _resolve_persistent_grants(self, request: AccessRequest,
                                   grants: Optional[List[AuthorizedReadGrant]]) -> Optional[List[AuthorizedReadGrant]]:
        """Resolve persistent READ grants from the derived projection (M5.4 -> M5.3).

        If the caller already supplied explicit in-memory grants, those win (M5.3
        contract preserved). Otherwise, when a grant connection is available, resolve
        authorizing READ grants for this requester via the deterministic resolver.
        """
        if grants is not None:
            return grants
        if self._grant_conn is None:
            return None
        from .resolver import resolve_read_grants
        ttype = None
        tid = None
        if request.target_profile_ids and len(request.target_profile_ids) == 1:
            ttype, tid = "profile", request.target_profile_ids[0]
        elif request.project_ids and len(request.project_ids) == 1:
            ttype, tid = "project", request.project_ids[0]
        elif request.knowledge_space_ids and len(request.knowledge_space_ids) == 1:
            ttype, tid = "knowledge_space", request.knowledge_space_ids[0]
        return resolve_read_grants(
            self._grant_conn, self._requester,
            target_type=ttype, target_id=tid,
            resource_type=request.resource_type)

    def _gate(self, request: AccessRequest,
              grants: Optional[List[AuthorizedReadGrant]] = None) -> EffectiveReadScope:
        """M5.1 base policy, composed with explicit READ grants (M5.3 / M5.4).

        Grants may be supplied explicitly (M5.3 in-memory contract) OR resolved from
        persistent canonical state (M5.4). No caller self-authorization: grants are
        validated from their own fields only.
        """
        resolved = self._resolve_persistent_grants(request, grants)
        eff = compose_effective_scope(request, resolved)
        if not self._resource_allowed(eff, request):
            eff = replace(eff, allow=False,
                          reason_code=ReasonCode.DENY_UNAUTHORIZED_CROSS_PROFILE_READ.value)
        return eff

    def authorize(self, request: AccessRequest) -> EffectiveReadScope:
        """Authorize a validated request without touching retrieval or freshness state."""
        return self._gate(request)

    def _denied(self, eff: EffectiveReadScope) -> AuthorizedResult:
        return AuthorizedResult(allowed=False, denied=True,
                                reason_code=eff.reason_code, decision=eff)

    def _downstream(self, eff: EffectiveReadScope, error: str) -> AuthorizedResult:
        return AuthorizedResult(allowed=True, denied=False, reason_code=eff.reason_code,
                               error=error, decision=eff)

    def _boundary_violation(self, eff: EffectiveReadScope) -> AuthorizedResult:
        return AuthorizedResult(allowed=False, denied=True,
                                reason_code=ReasonCode.DENY_ISOLATED_SCOPE_ESCAPE.value,
                                decision=eff)

    # -- scope decomposition ----------------------------------------------
    def _expand_scope_with_spaces(self, scope: AllowedScope) -> AllowedScope:
        """V150-WP3 (DEF-010/DEF-011 closed): NO-OP on the event path.

        Historically (DEF-004 Option B) this expanded a space grant into the
        concrete (profile_id, project_id) members resolved from the derived
        corpus projection, merging them into the scope's profile/project
        dimensions. That expansion WAS the coarsening channel (grant space ≡
        grant project) and made event authorization depend on a second derived
        state. Since V150-WP2/WP3 the event path authorizes per-row via
        ``zm_meta.knowledge_space_id`` alone; member expansion is neither
        needed nor permitted here. The resolver layer remains for the CORPUS
        read path (``corpus_unit_search``), where ks data is native.

        Kept as an explicit no-op so call sites and tests keep a stable seam.
        """
        return scope

    def _ordered_scopes(self, eff: EffectiveReadScope) -> List[AllowedScope]:
        """Stable, deduplicated list of scopes to query (base first, then grants).

        Each scope is expanded with its resolved knowledge-space members (DEF-004
        Option B) so profile/project predicates authorize space-owned rows.
        """
        import json
        expanded_base = self._expand_scope_with_spaces(eff.base)
        scopes: List[AllowedScope] = [expanded_base]
        seen = {json.dumps(expanded_base.as_dict(), sort_keys=True)}
        for g in eff.grant_scopes:
            eg = self._expand_scope_with_spaces(g)
            d = json.dumps(eg.as_dict(), sort_keys=True)
            if d not in seen:
                seen.add(d)
                scopes.append(eg)
        return scopes

    # -- M3 structured ------------------------------------------------------
    def _select_m3(self, scope: AllowedScope, limit: Optional[int],
                   project_filter: Optional[str] = None,
                   session_filter: Optional[str] = None,
                   verification_filter: Optional[str] = None,
                   lifecycle_filter: Optional[str] = None,
                   created_at_after: Optional[str] = None,
                   created_at_before: Optional[str] = None,
                   keyset: Optional[tuple] = None) -> List[Any]:
        from src.retrieval.models import QueryRequest
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
        j_clause, j_params = _project_predicate(scope)
        ks_clause, ks_params = _ks_predicate(scope)
        clauses = []
        if p_clause:
            clauses.append("(" + p_clause + ")")
            params = params + p_params
        if j_clause:
            clauses.append("(" + j_clause + ")")
            params = params + j_params
        if ks_clause:
            clauses.append("(" + ks_clause + ")")
            params = params + ks_params
        if clauses:
            where = where + " AND " + " AND ".join(clauses)
        else:
            # Neither profile nor project restriction (should not happen for valid
            # scopes) -> fail closed.
            where = where + " AND 1=0"
        if keyset is not None:
            where += " AND (created_at, event_id) > (?, ?)"
            params.extend([keyset[0], keyset[1]])
        # Internal callers validate the public limit before adding the look-ahead
        # row; do not re-apply the public ceiling to ``MAX_LIMIT + 1``.
        eff_limit = limit if limit is not None else -1
        cols = ",".join(ZM_META_COLUMNS)
        sql = (f"SELECT {cols} FROM zm_meta WHERE {where} "
               f"ORDER BY created_at ASC, event_id ASC")
        if eff_limit >= 0:
            sql += " LIMIT ?"
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
                     cursor: Optional[str] = None,
                     grants: Optional[List[AuthorizedReadGrant]] = None) -> AuthorizedResult:
        eff_limit = _validate_limit_safe(limit)
        eff = self._gate(request, grants)
        if not eff.allow:
            return self._denied(eff)
        # Scope-bound cursor fingerprint: reuse under a different EffectiveReadScope
        # (e.g. authorized scope changed) is a mismatch.
        from src.retrieval.models import QueryRequest as _QR
        # DEF-029 (DEF-B1): the fingerprint must bind EVERY filter the query
        # actually applies. project_filter and the time-window filters were
        # executed by _select_m3 but omitted here, so a cursor minted under one
        # filter set was accepted under another (keyset applied to a different
        # window -> rows silently skipped).
        proj = project_filter if project_filter is not None else (
            request.project_ids[0] if request.project_ids else None)
        fp_request = _QR(
            profile_id=profile_filter,
            session_id=session_filter,
            verification_status=verification_filter,
            lifecycle_status=lifecycle_filter,
            project_id=proj,
            created_at_after=created_at_after,
            created_at_before=created_at_before,
        )
        eff_text = "|".join([
            f"req={self._requester or ''}",
            f"iso={eff.base.isolated}",
            f"glob={eff.base.global_read_allowed}",
            f"p={','.join(sorted(eff.base.allowed_profile_ids))}",
            f"pj={','.join(sorted(eff.base.allowed_project_ids))}",
            f"ks={','.join(sorted(eff.base.allowed_knowledge_space_ids))}",
            f"grants={','.join(sorted(eff.grant_refs))}",
        ])
        fp = make_fingerprint(fp_request, text=eff_text)
        keyset = None
        if cursor is not None:
            data = validate_cursor_binding(cursor, fp, eff_limit)
            keyset = (data["sort"][0], data["sort"][1])
        try:
            seen_ids: set = set()
            merged: List[Any] = []
            for scope in self._ordered_scopes(eff):
                rows = self._select_m3(scope, eff_limit + 1, project_filter=proj,
                                       session_filter=session_filter,
                                       verification_filter=verification_filter,
                                       lifecycle_filter=lifecycle_filter,
                                       created_at_after=created_at_after,
                                       created_at_before=created_at_before,
                                       keyset=keyset)
                ks_map = _junction_ks_map(self._store.conn,
                                          [v.event_id for v in rows])
                for v in rows:
                    if v.event_id in seen_ids:
                        continue
                    if not _scope_allows(scope, self._requester,
                                             v.profile_id, v.project_id,
                                             row_knowledge_space_ids=ks_map.get(v.event_id, ())):
                        return self._boundary_violation(eff)
                    seen_ids.add(v.event_id)
                    merged.append(v)
            # Deterministic global ordering across composed scopes.
            merged.sort(key=lambda v: (v.created_at, v.event_id))
            # Keyset pagination over the merged, de-duplicated, sorted result set.
            if keyset is not None:
                merged = [v for v in merged
                          if (v.created_at, v.event_id) > keyset]
            items = merged[:eff_limit]
        except QueryError as exc:
            return self._downstream(eff, exc.code)
        next_cursor = None
        if len(merged) > eff_limit:
            last = items[-1]
            next_cursor = encode_cursor(fp, last.created_at, last.event_id,
                                        eff_limit)
        return AuthorizedResult(allowed=True, denied=False, reason_code=eff.reason_code,
                                items=items, query=eff.base.as_dict(),
                                next_cursor=next_cursor, decision=eff)

    def get_event(self, request: AccessRequest, event_id: str,
                  grants: Optional[List[AuthorizedReadGrant]] = None) -> AuthorizedResult:
        eff = self._gate(request, grants)
        if not eff.allow:
            return self._denied(eff)
        try:
            view = get_event(self._store, event_id)
        except QueryError as exc:
            return self._downstream(eff, exc.code)
        if view is None:
            return AuthorizedResult(allowed=True, denied=False,
                                    reason_code=eff.reason_code, decision=eff)
        ks_map = _junction_ks_map(self._store.conn, [view.event_id])
        for scope in self._ordered_scopes(eff):
            if _scope_allows(scope, self._requester, view.profile_id,
                             view.project_id,
                             row_knowledge_space_ids=ks_map.get(view.event_id, ())):
                return AuthorizedResult(allowed=True, denied=False,
                                        reason_code=eff.reason_code,
                                        items=[view], decision=eff)
        return self._boundary_violation(eff)

    def get_trace(self, request: AccessRequest, trace_id: str,
                  grants: Optional[List[AuthorizedReadGrant]] = None) -> AuthorizedResult:
        eff = self._gate(request, grants)
        if not eff.allow:
            return self._denied(eff)
        try:
            views = get_trace(self._store, trace_id)
        except QueryError as exc:
            return self._downstream(eff, exc.code)
        items = []
        ks_map = _junction_ks_map(self._store.conn,
                                  [v.event_id for v in views])
        for v in views:
            ok = False
            for scope in self._ordered_scopes(eff):
                if _scope_allows(scope, self._requester, v.profile_id,
                                 v.project_id,
                                 row_knowledge_space_ids=ks_map.get(v.event_id, ())):
                    ok = True
                    break
            if not ok:
                return self._boundary_violation(eff)
            items.append(v)
        return AuthorizedResult(allowed=True, denied=False, reason_code=eff.reason_code,
                                items=items, decision=eff)

    # -- M3 FTS -------------------------------------------------------------
    def search_text(self, request: AccessRequest, text: str,
                    profile_filter: Optional[str] = None,
                    project_filter: Optional[str] = None,
                    session_filter: Optional[str] = None,
                    verification_filter: Optional[str] = None,
                    limit: Optional[int] = None,
                    cursor: Optional[str] = None,
                    grants: Optional[List[AuthorizedReadGrant]] = None) -> AuthorizedResult:
        # Server validates once, before policy or retrieval.  Invalid caller input
        # is never silently defaulted or clamped by the facade.
        eff_limit = _validate_limit_safe(limit)
        eff = self._gate(request, grants)
        if not eff.allow:
            return self._denied(eff)
        from src.retrieval.models import QueryRequest
        clause, params = _effective_scope_predicate(eff, self._requester)
        fingerprint_extra = "v151|" + clause + "|" + ",".join(params) + "|" + ",".join(sorted(eff.grant_refs))
        try:
            req = QueryRequest(
                project_id=project_filter or (request.project_ids[0] if request.project_ids else None),
                session_id=session_filter,
                verification_status=verification_filter,
            )
            res = search_text(self._store, text, req=req, limit=eff_limit, cursor=cursor,
                              candidate_where=clause, candidate_params=params,
                              fingerprint_extra=fingerprint_extra)
            if res.error is not None:
                return AuthorizedResult(allowed=True, denied=False,
                                        reason_code=eff.reason_code,
                                        error=res.error, decision=eff)
            # SQL is the authorization boundary.  This only detects/filters an
            # unexpected backend inconsistency; it never turns a hidden row into a
            # boundary error visible to the caller.
            scopes = self._ordered_scopes(eff)
            # V1.6.0 C5: FTS candidates use the same C4 correlated-EXISTS
            # predicate as structured reads.  Defensive post-validation must
            # therefore use the complete junction set too; PRIMARY-KS alone
            # would incorrectly discard an event [A,B] authorized through B.
            # A missing junction row stays an empty set and fails closed.
            ks_by_event = _junction_ks_map(
                self._store.conn, (hit.event_id for hit in res.results)
            )
            items = [h for h in res.results if any(
                _scope_allows(scope, self._requester, h.profile_id, h.project_id,
                              row_knowledge_space_ids=ks_by_event.get(h.event_id, ()))
                for scope in scopes)]
        except QueryError as exc:
            return self._downstream(eff, exc.code)
        return AuthorizedResult(allowed=True, denied=False, reason_code=eff.reason_code,
                                items=items, next_cursor=res.next_cursor, decision=eff)

    # -- M4 (project-memory) ------------------------------------------------
    def _m4_project_scope_ok(self, eff: EffectiveReadScope, project_id: str) -> bool:
        """M4 reads are project-scoped; the project must be explicitly authorized.

        Cross-profile requests produce an EMPTY base scope (the base policy denies
        cross-profile), so authorized projects come from grant scopes. Union the
        base and grant-scope project ids.
        """
        if project_id is None:
            return False
        allowed_projects = set(eff.base.allowed_project_ids)
        for g in eff.grant_scopes:
            allowed_projects.update(g.allowed_project_ids)
        return project_id in allowed_projects

    _M4_RESOURCE_TYPE = {
        "m4_requirements": "requirement",
        "m4_decisions": "decision",
        "m4_current_state": "state",
        "m4_verifications": "verification",
        "m4_artifacts": "artifact",
        "m4_charter": "charter",
    }

    def _m4_resource_allowed(self, eff: EffectiveReadScope, project_id: str,
                             resource_type: str) -> bool:
        """Enforce per-project grant resource-type restriction (plan §11.3)."""
        rt = eff.grant_resource_types.get(project_id)
        if rt is None:
            return True
        return resource_type in rt

    def _resource_allowed(self, eff: EffectiveReadScope, request: AccessRequest) -> bool:
        """Cross-resource isolation for explicit-resource-type reads (M3 event/
        relation). A grant that restricts resource_types must not authorize other
        resource types. Base-policy allows and unrestricted grants pass. M4
        project-memory reads pass resource_type=None and are gated per-call by
        _m4_resource_allowed, so they are unaffected here."""
        rt = request.resource_type
        if rt is None:
            return True
        if not eff.grant_scopes:
            # decision rests on base policy, not a restricting grant
            return True
        for proj in (request.project_ids or []):
            allowed = eff.grant_resource_types.get(proj)
            if allowed is not None and rt not in allowed:
                return False
        return True

    def m4_charter(self, request: AccessRequest, project_id: str,
                   charter_id: Optional[str] = None,
                   include_source_event: bool = False,
                   grants: Optional[List[AuthorizedReadGrant]] = None) -> AuthorizedResult:
        eff = self._gate(request, grants)
        if not eff.allow:
            return self._denied(eff)
        if not self._m4_project_scope_ok(eff, project_id):
            return self._boundary_violation(eff)
        if not self._m4_resource_allowed(eff, project_id, "charter"):
            return self._denied(eff)
        try:
            view = m4.get_project_charter(self._store, project_id, charter_id=charter_id,
                                          include_source_event=include_source_event)
        except QueryError as exc:
            return self._downstream(eff, exc.code)
        if include_source_event:
            _linked.harden_m4_source_event(eff, self, view)
        if view is None:
            return AuthorizedResult(allowed=True, denied=False,
                                    reason_code=eff.reason_code, decision=eff)
        _attach_source_event_spaces(self._store.conn, (view,))
        for scope in self._ordered_scopes(eff):
            if _scope_allows(scope, self._requester, view.profile_id,
                             view.project_id,
                             row_knowledge_space_ids=_row_ks_ids(view)):
                return AuthorizedResult(allowed=True, denied=False,
                                        reason_code=eff.reason_code,
                                        items=[view], decision=eff)
        return self._boundary_violation(eff)

    def _m4_list(self, request: AccessRequest, project_id: str,
                 low_level_fn: Callable[[], Any],
                 resource_type: Optional[str] = None,
                 grants: Optional[List[AuthorizedReadGrant]] = None) -> AuthorizedResult:
        eff = self._gate(request, grants)
        if not eff.allow:
            return self._denied(eff)
        if not self._m4_project_scope_ok(eff, project_id):
            return self._boundary_violation(eff)
        if resource_type is not None and not self._m4_resource_allowed(eff, project_id, resource_type):
            return self._denied(eff)
        try:
            res = low_level_fn()
        except QueryError as exc:
            return self._downstream(eff, exc.code)
        if hasattr(res, "items"):
            source_items = res.items
            query = res.query
            next_cursor = res.next_cursor
        else:
            source_items = res
            query = {}
            next_cursor = None
        _attach_source_event_spaces(self._store.conn, source_items)
        allowed = []
        for v in source_items:
            if getattr(v, "source_event", None) is not None:
                _linked.harden_m4_source_event(eff, self, v)
            ok = False
            for scope in self._ordered_scopes(eff):
                if _scope_allows(scope, self._requester,
                                getattr(v, "profile_id", None),
                                getattr(v, "project_id", None),
                                row_knowledge_space_ids=_row_ks_ids(v)):
                    ok = True
                    break
            if not ok:
                return self._boundary_violation(eff)
            allowed.append(v)
        return AuthorizedResult(allowed=True, denied=False,
                                reason_code=eff.reason_code,
                                items=allowed, query=query,
                                next_cursor=next_cursor, decision=eff)

    def m4_requirements(self, request: AccessRequest, project_id: str,
                        limit: Optional[int] = None,
                        cursor: Optional[str] = None,
                        grants: Optional[List[AuthorizedReadGrant]] = None) -> AuthorizedResult:
        return self._m4_list(request, project_id,
                             lambda: m4.list_requirements(self._store, project_id,
                                                          limit=limit, cursor=cursor),
                             resource_type="requirement", grants=grants)

    def m4_decisions(self, request: AccessRequest, project_id: str,
                     limit: Optional[int] = None,
                     cursor: Optional[str] = None,
                     grants: Optional[List[AuthorizedReadGrant]] = None) -> AuthorizedResult:
        return self._m4_list(request, project_id,
                             lambda: m4.list_decisions(self._store, project_id,
                                                       limit=limit, cursor=cursor),
                             resource_type="decision", grants=grants)

    def m4_current_state(self, request: AccessRequest, project_id: str,
                          grants: Optional[List[AuthorizedReadGrant]] = None) -> AuthorizedResult:
        return self._m4_list(request, project_id,
                             lambda: m4.get_current_project_state(self._store, project_id),
                             resource_type="state", grants=grants)

    def m4_verifications(self, request: AccessRequest, project_id: str,
                         limit: Optional[int] = None,
                         cursor: Optional[str] = None,
                         grants: Optional[List[AuthorizedReadGrant]] = None) -> AuthorizedResult:
        return self._m4_list(request, project_id,
                             lambda: m4.list_verifications(self._store, project_id,
                                                          limit=limit, cursor=cursor),
                             resource_type="verification", grants=grants)

    def m4_artifacts(self, request: AccessRequest, project_id: str,
                     limit: Optional[int] = None,
                     cursor: Optional[str] = None,
                     grants: Optional[List[AuthorizedReadGrant]] = None) -> AuthorizedResult:
        return self._m4_list(request, project_id,
                             lambda: m4.list_project_artifacts(self._store, project_id,
                                                              limit=limit, cursor=cursor),
                             resource_type="artifact", grants=grants)


    # -- M5.5 linked-resource authorization ---------------------------------
    def get_related(self, request: AccessRequest, event_id: str,
                    direction: Optional[str] = None,
                    relation_type: Optional[str] = None,
                    limit: Optional[int] = None,
                    cursor: Optional[str] = None,
                    grants: Optional[List[AuthorizedReadGrant]] = None) -> AuthorizedResult:
        """Relation traversal with target-scope recheck (fail closed).

        Relations never grant scope: an authorized source event does NOT authorize
        its linked target. Every target is independently scope-checked; any
        out-of-scope target withholds the whole result (no leakage).
        """
        return _linked.authorize_relation(self, request, event_id, direction=direction,
                                           relation_type=relation_type, limit=limit,
                                           cursor=cursor, grants=grants)

    def get_outgoing(self, request: AccessRequest, event_id: str,
                     relation_type: Optional[str] = None, limit: Optional[int] = None,
                     cursor: Optional[str] = None,
                     grants: Optional[List[AuthorizedReadGrant]] = None) -> AuthorizedResult:
        """Outgoing relation edges (from_event_id = event_id), target-scope rechecked."""
        return self.get_related(request, event_id, direction="outgoing",
                                relation_type=relation_type, limit=limit, cursor=cursor,
                                grants=grants)

    def get_incoming(self, request: AccessRequest, event_id: str,
                     relation_type: Optional[str] = None, limit: Optional[int] = None,
                     cursor: Optional[str] = None,
                     grants: Optional[List[AuthorizedReadGrant]] = None) -> AuthorizedResult:
        """Incoming relation edges (to_event_id = event_id), target-scope rechecked."""
        return self.get_related(request, event_id, direction="incoming",
                                relation_type=relation_type, limit=limit, cursor=cursor,
                                grants=grants)

    def get_parent(self, request: AccessRequest, event_id: str,
                   grants: Optional[List[AuthorizedReadGrant]] = None) -> AuthorizedResult:
        """Parent linkage (outgoing 'child_of'); target-scope rechecked. Fail closed."""
        return self.get_related(request, event_id, direction="outgoing",
                                relation_type="child_of", limit=1, grants=grants)

    def get_children(self, request: AccessRequest, event_id: str,
                     limit: Optional[int] = None, cursor: Optional[str] = None,
                     grants: Optional[List[AuthorizedReadGrant]] = None) -> AuthorizedResult:
        """Child linkage (incoming 'child_of'); targets-scope rechecked. Fail closed."""
        return self.get_related(request, event_id, direction="incoming",
                                relation_type="child_of", limit=limit, cursor=cursor,
                                grants=grants)

    def m4_requirement_verifications(self, request: AccessRequest, project_id: str,
                                     requirement_id: str,
                                     grants: Optional[List[AuthorizedReadGrant]] = None) -> AuthorizedResult:
        """Resolve a Requirement's linked verification ids within scope.

        A requirement link does NOT authorize the verification: the project must be
        authorized AND resource_type='verification' must be permitted. Returns only
        in-scope verifications (missing/out-of-scope dropped, no leak).
        """
        from src.project_memory import reader as _m4
        eff = self._gate(request, grants)
        if not eff.allow:
            return self._denied(eff)
        if not self._m4_project_scope_ok(eff, project_id):
            return self._boundary_violation(eff)
        if not self._m4_resource_allowed(eff, project_id, "verification"):
            return self._denied(eff)
        req = _m4.get_requirement(self._store, requirement_id)
        if req is None:
            return AuthorizedResult(allowed=True, denied=False,
                                    reason_code=eff.reason_code, items=[], decision=eff)
        return _linked.authorize_m4_link(
            eff, self, request, project_id, "verification",
            getattr(req, "linked_verification_ids", None),
            lambda vid: _m4.get_verification(self._store, vid), grants=grants)

    def m4_requirement_artifacts(self, request: AccessRequest, project_id: str,
                                 requirement_id: str,
                                 grants: Optional[List[AuthorizedReadGrant]] = None) -> AuthorizedResult:
        """Resolve a Requirement's linked artifact ids within scope (artifact resource-type)."""
        from src.project_memory import reader as _m4
        eff = self._gate(request, grants)
        if not eff.allow:
            return self._denied(eff)
        if not self._m4_project_scope_ok(eff, project_id):
            return self._boundary_violation(eff)
        if not self._m4_resource_allowed(eff, project_id, "artifact"):
            return self._denied(eff)
        req = _m4.get_requirement(self._store, requirement_id)
        if req is None:
            return AuthorizedResult(allowed=True, denied=False,
                                    reason_code=eff.reason_code, items=[], decision=eff)
        return _linked.authorize_m4_link(
            eff, self, request, project_id, "artifact",
            getattr(req, "linked_artifact_ids", None),
            lambda aid: _m4.get_artifact(self._store, aid), grants=grants)



    def corpus_unit_search(
        self,
        request: AccessRequest,
        text: str,
        *,
        metadata: Optional[dict] = None,
        limit: Optional[int] = None,
        semantic: Optional[Any] = None,
        grants: Optional[List[AuthorizedReadGrant]] = None,
    ) -> AuthorizedResult:
        """Authorization-before-influence corpus_unit retrieval.

        Authorization is performed by M5 BEFORE any corpus candidate discovery.
        The effective scope (base + per-grant atomic scopes) is enumerated into
        concrete (profile, project, space) tuples, and only units inside that
        authorized scope may become candidates. FTS is used for lexical
        discovery only; unauthorized units are dropped before ranking/scoring/
        fusion/truncation (see src/corpus/retrieval.py).

        `corpus_unit` is a DISTINCT resource type from `corpus_source`; a
        `corpus_source` grant does NOT authorize `corpus_unit` reads and vice
        versa (permanent M6.6 isolation, enforced by `_gate` resource_type check
        and the explicit `resource_type="corpus_unit"` request).

        Returns an ``AuthorizedResult`` whose ``items`` are ``CorpusHit``
        objects (DATA only). Denials/errors yield nothing here.
        """
        eff = self._gate(request, grants)
        if not eff.allow:
            return self._denied(eff)
        # Explicit resource_type gate: corpus_unit reads require corpus_unit
        # authorization; a corpus_source-only scope must not leak corpus_unit.
        if request.resource_type not in (None, "corpus_unit"):
            return self._denied(eff)

        from src.corpus.query_planner import build_query_plan
        from src.corpus.retrieval import (
            AuthorizedCorpusScope,
            CorpusHit,
            retrieve_corpus,
        )

        # Enumerate the authorized corpus scope from the M5 EffectiveReadScope.
        allowed: List[tuple] = []
        for scope in self._ordered_scopes(eff):
            # Unowned/default (NULL profile) scope is authorized only when
            # global_read_allowed; represented as (None, None, None) so NULL
            # unit rows match. Profile/project/space grants enumerate their own
            # authorized dimensions.
            profiles = list(scope.allowed_profile_ids)
            projects = list(scope.allowed_project_ids)
            spaces = list(scope.allowed_knowledge_space_ids)
            if scope.global_read_allowed:
                profiles = profiles + [self._requester] if self._requester else profiles
                # NULL-profile default rows are authorizable under global read.
                allowed.append((None, None, None))
            # DEF-028 (DEF-A1): a base/policy scope is ALWAYS requester-scoped —
            # only per-grant atomic scopes may be profile-unrestricted. Without
            # this, a base scope with a KS filter enumerated (None, None, K),
            # authorizing every profile's units in K.
            if not scope.is_grant and self._requester is not None:
                if self._requester not in profiles:
                    profiles = profiles + [self._requester]
            if not profiles and not projects and not spaces:
                # Implicit-local base scope (own profile only).
                if self._requester is not None:
                    allowed.append((self._requester, None, None))
                continue
            # Cartesian combination of authorized dimensions for this scope.
            p_set = profiles or [None]
            j_set = projects or [None]
            k_set = spaces or [None]
            for p in p_set:
                for j in j_set:
                    for k in k_set:
                        allowed.append((p, j, k))
        # De-duplicate while preserving order.
        seen = set()
        deduped = []
        for triple in allowed:
            if triple not in seen:
                seen.add(triple)
                deduped.append(triple)
        auth_scope = AuthorizedCorpusScope(allowed_scopes=tuple(deduped))

        try:
            plan = build_query_plan(text, metadata=metadata, limit=limit or 100)
        except Exception as exc:
            return self._downstream(eff, f"corpus_query_plan_error:{type(exc).__name__}")

        try:
            hits = retrieve_corpus(self._store.conn, auth_scope, plan, semantic=semantic)
        except Exception as exc:
            return self._downstream(eff, f"corpus_retrieval_error:{type(exc).__name__}")

        return AuthorizedResult(
            allowed=True,
            denied=False,
            reason_code=eff.reason_code,
            items=[h for h in hits if isinstance(h, CorpusHit)],
            query=plan.as_dict(),
            decision=eff,
        )


__all__ = ["AuthorizedReadService", "AuthorizedResult",
           "_profile_predicate", "_project_predicate", "_scope_allows"]
