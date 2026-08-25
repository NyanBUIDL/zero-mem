"""M5.3 — in-memory pre-authorized cross-profile READ contract + scope composition.

Implements the EXACT pre-authorized read-authorization contract defined by the
approved M5 plan (§11.1 grant shape) WITHOUT persistent state.

Persistent grants belong to M5.4 (canonical JSONL `access_grant` events + derived
`zm_access_grants` / migration v8). M5.3 MUST NOT create those. Instead, an
authorizer (the future grant-resolution layer) supplies already-validated
``AuthorizedReadGrant`` (GrantView) objects for the current request. M5.3
validates only the fields the plan assigns to the contract and composes them
into an ``EffectiveReadScope``.

CRITICAL SAFETY PROPERTIES (directive):
- No caller self-authorization. Validity is derived from the grant's OWN fields,
  never from a raw boolean such as ``cross_profile_allowed``. A caller cannot pass
  ``authorized=True`` to widen scope.
- READ != WRITE. A WRITE grant is never treated as a READ grant.
- Grant scope is narrow: profile=B/project=P does NOT authorize B/Q or all B spaces.
- Relations / source-events / artifact links never expand the effective scope.
- No persistent write, no migration v8, no audit event.

Decomposition model: ``EffectiveReadScope`` carries a ``base`` AllowedScope (the
M5.1 policy result, profile+project AND-restrictive) plus a list of per-grant
atomic ``AllowedScope`` objects (each grant is one independently-restricted
scope). The facade issues a restrictive query per scope and merges authorized
results. This prevents base and grant scopes from being unioned incorrectly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .contracts import AccessDecision, AccessRequest, AllowedScope, READ, ReasonCode

# Closed lifecycle enum (lifecycle_status). `revoked` is a DOMAIN state, never a
# lifecycle value (plan §11.4); revoked or deleted grants are non-authorizing.
_AUTHORIZING_LIFECYCLE = {
    "raw", "observed", "candidate", "confirmed",
    "active", "superseded", "conflicted", "archived",
}


@dataclass(frozen=True)
class AuthorizedReadGrant:
    """In-memory, pre-validated cross-profile READ authorization (plan §11.1 shape).

    Supplied by the caller as ALREADY-validated authorization for this request.
    M5.3 does NOT query persistent grant state (it does not exist yet). Validity
    is recomputed from the grant's own fields so a caller cannot forge scope by
    passing an ad-hoc flag.
    """

    grant_id: str
    subject_profile: str
    operation: str                       # "READ" | "WRITE"
    target_type: str                    # "profile" | "project" | "knowledge_space" | "global"
    target_id: str                      # profile/project/space id, or "*"
    resource_types: Optional[List[str]] = None   # None = all
    state: Optional[str] = None         # generic domain state; "revoked" => non-authorizing
    lifecycle_status: str = "active"
    supersedes: Optional[str] = None
    verification_ref: Optional[str] = None
    source_event_id: Optional[str] = None
    created_at: Optional[str] = None

    def is_read(self) -> bool:
        return self.operation == READ

    def is_authorizing(self) -> bool:
        if self.state == "revoked":
            return False
        if self.lifecycle_status == "deleted":
            return False
        return self.lifecycle_status in _AUTHORIZING_LIFECYCLE

    def covers_resource(self, resource_type: Optional[str]) -> bool:
        if self.resource_types is None:
            return True
        if resource_type is None:
            return True
        return resource_type in self.resource_types


@dataclass(frozen=True)
class EffectiveReadScope:
    """Composed authorization for one request.

    - ``allow``: whether ANY requested scope is authorized (partial-allow exposes
      ``denied_scopes`` explicitly; an all-denied request is ``allow=False``).
    - ``base``: the M5.1 policy AllowedScope (profile+project AND-restrictive).
    - ``grant_scopes``: one independently-restrictive AllowedScope per authorizing
      READ grant (profile grant => profile IN(...); project grant => project IN(...)
      with profile unrestricted; knowledge-space grant => space IN(...)).
    - ``denied_scopes``: explicitly requested scopes that were NOT authorized.
    - ``grant_resource_types``: per-project READ resource-type restriction carried by
      project grants (None / absent key = unrestricted for that project).
    """

    allow: bool
    base: AllowedScope
    grant_scopes: List[AllowedScope] = field(default_factory=list)
    denied_scopes: List[str] = field(default_factory=list)
    reason_code: str = ""
    grant_refs: List[str] = field(default_factory=list)
    grant_resource_types: Dict[str, Optional[frozenset]] = field(default_factory=dict)

    @property
    def normalized_scope(self) -> AllowedScope:
        return self.base

    # Facade-compat shim (AccessDecision shape)
    @property
    def decision_id(self):
        return None


def _grant_scopes(grants: List[AuthorizedReadGrant], requesting_profile: Optional[str]
                  ) -> tuple:
    """Flatten authorizing READ grants into (profs, projs, spaces, grant_global).

    Only grants whose subject_profile == requesting_profile and operation == READ
    and still authorizing contribute. No broadening beyond the grant's own target.
    A profile grant with target_id='*' is an explicit global grant (grant_global).
    """
    profs: set = set()
    projs: set = set()
    spaces: set = set()
    grant_global = False
    for g in grants:
        if not g.is_authorizing() or not g.is_read():
            continue
        if requesting_profile is not None and g.subject_profile != requesting_profile:
            continue
        if g.target_type == "profile":
            if g.target_id == "*":
                grant_global = True
            else:
                profs.add(g.target_id)
        elif g.target_type == "project":
            projs.add(g.target_id)
        elif g.target_type == "knowledge_space":
            spaces.add(g.target_id)
    return profs, projs, spaces, grant_global


def compose_effective_scope(request: AccessRequest,
                             grants: Optional[List[AuthorizedReadGrant]] = None
                             ) -> EffectiveReadScope:
    """Compose EffectiveReadScope = Requested ∩ PolicyAllowed ∩ GrantScopes.

    M5.3 is READ-only: a WRITE request is never authorized via grants (WRITE grant
    resolution is M5.4). WRITE requests fall through to the base M5.1 policy, which
    denies cross-profile WRITE.
    """
    from .policy import evaluate

    if request.operation != READ:
        base = evaluate(request)
        return EffectiveReadScope(
            allow=base.allow, base=base.normalized_scope,
            denied_scopes=base.denied_scopes, reason_code=base.reason_code,
            grant_refs=[])

    base = evaluate(request)
    requester = request.requesting_profile_id
    requested_profiles = set(request.target_profile_ids or [])
    requested_projects = set(request.project_ids or [])
    requested_spaces = set(request.knowledge_space_ids or [])

    base_allowed_profiles = set(base.normalized_scope.allowed_profile_ids)
    if requester is not None:
        base_allowed_profiles.add(requester)
    base_allowed_projects = set(base.normalized_scope.allowed_project_ids)
    base_allowed_spaces = set(base.normalized_scope.allowed_knowledge_space_ids)
    global_read_allowed = base.normalized_scope.global_read_allowed

    g_profs, g_projs, g_spaces, grant_global = _grant_scopes(list(grants or []), requester)

    # No effective explicit READ grant: preserve the base M5.1/M5.2 policy decision
    # (including its canonical reason codes) unchanged. This keeps M5.2 behavior
    # stable and only diverges from the base policy when a grant ACTIVELY expands
    # the authorized scope.
    if not (g_profs or g_projs or g_spaces or grant_global):
        return EffectiveReadScope(
            allow=base.allow, base=base.normalized_scope,
            denied_scopes=base.denied_scopes, reason_code=base.reason_code,
            grant_refs=[])

    # Determine authorized vs denied for each explicitly requested dimension.
    allowed_profiles: set = set()
    denied_profiles: set = set()
    for p in requested_profiles:
        if p == "*":
            # Explicit global grant ("*") is covered by grant_global; not a literal
            # profile id.
            if grant_global:
                continue
            denied_profiles.add(p)
            continue
        if (p in base_allowed_profiles or p in g_profs or ("*" in g_profs)
                or (requested_projects & g_projs)):
            allowed_profiles.add(p)
        else:
            denied_profiles.add(p)

    allowed_projects: set = set()
    denied_projects: set = set()
    for p in requested_projects:
        if p in base_allowed_projects or p in g_projs:
            allowed_projects.add(p)
        else:
            denied_projects.add(p)

    allowed_spaces: set = set()
    denied_spaces: set = set()
    for s in requested_spaces:
        if s in base_allowed_spaces or s in g_spaces:
            allowed_spaces.add(s)
        else:
            denied_spaces.add(s)

    # Implicit request (nothing explicitly asked): use base scope as-is.
    if not requested_profiles and not requested_projects and not requested_spaces:
        return EffectiveReadScope(
            allow=base.allow, base=base.normalized_scope,
            denied_scopes=base.denied_scopes, reason_code=base.reason_code,
            grant_refs=[g.grant_id for g in (grants or [])
                        if g.is_authorizing() and g.is_read()])

    # Any requested cross-profile target lacking a valid grant => DENY the request
    # (cross-profile base rule). Allowed data is served only when every requested
    # cross-profile target is covered by base or an explicit grant.
    if denied_profiles or denied_projects or denied_spaces:
        return EffectiveReadScope(
            allow=False,
            base=AllowedScope(operation=READ,
                              allowed_profile_ids=sorted(allowed_profiles),
                              allowed_project_ids=sorted(allowed_projects),
                              allowed_knowledge_space_ids=sorted(allowed_spaces),
                              global_read_allowed=global_read_allowed,
                              isolated=request.isolated_mode),
            denied_scopes=sorted(denied_profiles | denied_projects | denied_spaces),
            reason_code=ReasonCode.DENY_UNAUTHORIZED_CROSS_PROFILE_READ.value,
            grant_refs=[])

    # Fully authorized: build base + per-grant atomic scopes.
    base_scope = AllowedScope(
        operation=READ,
        allowed_profile_ids=sorted(base_allowed_profiles & (requested_profiles or base_allowed_profiles)),
        allowed_project_ids=sorted(base_allowed_projects | allowed_projects),
        allowed_knowledge_space_ids=sorted(base_allowed_spaces | allowed_spaces),
        global_read_allowed=global_read_allowed or grant_global,
        isolated=request.isolated_mode,
    )
    grant_scopes: List[AllowedScope] = []
    grant_resource_types: Dict[str, Optional[frozenset]] = {}
    for g in (grants or []):
        if not g.is_authorizing() or not g.is_read():
            continue
        if requester is not None and g.subject_profile != requester:
            continue
        if g.target_type == "profile" and g.target_id != "*":
            grant_scopes.append(AllowedScope(
                operation=READ, allowed_profile_ids=[g.target_id],
                global_read_allowed=False, isolated=request.isolated_mode,
                is_grant=True))  # DEF-028: explicit per-grant atomic scope
        elif g.target_type == "project":
            # Project grant: authorize the project across profiles (no profile filter).
            grant_scopes.append(AllowedScope(
                operation=READ, allowed_profile_ids=[],
                allowed_project_ids=[g.target_id],
                global_read_allowed=False, isolated=request.isolated_mode,
                is_grant=True))  # DEF-028: explicit per-grant atomic scope
            grant_resource_types[g.target_id] = (
                frozenset(g.resource_types) if g.resource_types is not None else None)
        elif g.target_type == "knowledge_space":
            grant_scopes.append(AllowedScope(
                operation=READ, allowed_profile_ids=[],
                allowed_knowledge_space_ids=[g.target_id],
                global_read_allowed=False, isolated=request.isolated_mode,
                is_grant=True))  # DEF-028: explicit per-grant atomic scope

    return EffectiveReadScope(
        allow=True,
        base=base_scope,
        grant_scopes=grant_scopes,
        denied_scopes=[],
        reason_code=ReasonCode.ALLOW_EXPLICIT_CROSS_PROFILE_READ.value,
        grant_refs=[g.grant_id for g in (grants or [])
                    if g.is_authorizing() and g.is_read()],
        grant_resource_types=grant_resource_types)


__all__ = ["AuthorizedReadGrant", "EffectiveReadScope", "compose_effective_scope"]
