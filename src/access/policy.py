"""M5.1 deterministic base policy evaluation (no grants, no integration).

Implements the corrected M5.1 subset of the authoritative precedence (approved
M5 plan §8, restricted to the base rules because persistent grants are NOT part
of M5.1):

    1. invalid request                       -> DENY_INVALID_REQUEST
    2. isolated implicit scope escape        -> DENY_ISOLATED_SCOPE_ESCAPE
    3. cross-profile boundary (no grants)    -> DENY_CROSS_PROFILE_*
    4. cross-project protected boundary      -> DENY_CROSS_PROJECT
    5. permitted same-profile local scope    -> ALLOW_LOCAL_*
    6. permitted global READ                 -> ALLOW_GLOBAL_READ
    7. otherwise                             -> DENY_*   (fail closed)

Architecture boundaries enforced here:
- NO retrieval / ranking / context injection.
- NO identity inference (null stays null).
- NO persistent grants, NO schema v8, NO audit writes.
- Deterministic: same (request) + same inputs -> same AccessDecision.
  No LLM, no network, no wall-clock logic, no random ids in semantics.
"""

from __future__ import annotations

from typing import Optional

from .contracts import (
    READ, WRITE,
    AccessDecision, AccessRequest, AllowedScope, ReasonCode,
)

# Safe default reason when an allow cannot be more specific.
_ALLOW_LOCAL_READ = ReasonCode.ALLOW_LOCAL_PROFILE_READ
_ALLOW_GLOBAL_READ = ReasonCode.ALLOW_GLOBAL_READ


def _deny(reason: ReasonCode, operation: str,
          denied: Optional[list] = None) -> AccessDecision:
    return AccessDecision(
        allow=False,
        normalized_scope=AllowedScope(operation=operation),
        denied_scopes=list(denied or []),
        reason_code=reason.value,
    )


def _allow(operation: str, *,
           profiles: Optional[list] = None,
           projects: Optional[list] = None,
           spaces: Optional[list] = None,
           global_read: bool = False,
           reason: ReasonCode) -> AccessDecision:
    return AccessDecision(
        allow=True,
        normalized_scope=AllowedScope(
            operation=operation,
            allowed_profile_ids=list(profiles or []),
            allowed_project_ids=list(projects or []),
            allowed_knowledge_space_ids=list(spaces or []),
            global_read_allowed=global_read,
            isolated=False,
        ),
        denied_scopes=[],
        reason_code=reason.value,
        grant_refs=[],
    )


def evaluate(request: AccessRequest) -> AccessDecision:
    """Evaluate an ``AccessRequest`` and return a deterministic ``AccessDecision``.

    Pure function of (request). Raises nothing: structural validation failures
    are converted to a ``DENY_INVALID_REQUEST`` decision (no raw exceptions leak).
    """
    # 1. invalid request (structured validation)
    try:
        req = request.validate()
    except ValueError:
        return _deny(ReasonCode.DENY_INVALID_REQUEST,
                     operation=str(getattr(request, "operation", "")))

    op = req.operation
    requester = req.requesting_profile_id
    target_profiles = list(req.target_profile_ids or [])
    projects = list(req.project_ids or [])
    spaces = list(req.knowledge_space_ids or [])

    # ---- unbound caller (requesting_profile_id is None) ----
    if requester is None:
        # Any explicit protected scope without identity => deny.
        if target_profiles or projects or spaces:
            return _deny(ReasonCode.DENY_UNBOUND_PROTECTED, op,
                         denied=(target_profiles + projects + spaces))
        if op == WRITE:
            return _deny(ReasonCode.DENY_UNBOUND_PROTECTED, op)
        # READ: only permitted global read; isolation removes implicit global.
        if req.isolated_mode:
            return _deny(ReasonCode.DENY_ISOLATED_SCOPE_ESCAPE, op,
                         denied=["global"]) if req.include_global \
                else _deny(ReasonCode.DENY_UNBOUND_PROTECTED, op)
        if req.include_global:
            return _allow(op, global_read=True, reason=_ALLOW_GLOBAL_READ)
        return _deny(ReasonCode.DENY_UNBOUND_PROTECTED, op)

    # ---- bound caller ----
    # 2. isolated: implicit global fallback removed; an all-implicit request
    #    (nothing explicitly selected) under isolation is a scope escape.
    if req.isolated_mode:
        if not target_profiles and not projects and not spaces:
            return _deny(ReasonCode.DENY_ISOLATED_SCOPE_ESCAPE, op,
                         denied=["global", "implicit"])
        # A knowledge space (or project) selected under isolation without an
        # explicit profile scope cannot be resolved to authorized profiles; that
        # is an implicit expansion -> scope escape.
        if spaces and not (target_profiles or projects):
            return _deny(ReasonCode.DENY_ISOLATED_SCOPE_ESCAPE, op,
                         denied=list(spaces))
        global_allowed = False  # isolation removes implicit global
    else:
        global_allowed = bool(req.include_global)

    # 3. cross-profile boundary (no grants in M5.1)
    if any(p != requester for p in target_profiles):
        reason = (ReasonCode.DENY_CROSS_PROFILE_WRITE
                  if op == WRITE else ReasonCode.DENY_CROSS_PROFILE_READ)
        return _deny(reason, op, denied=target_profiles)

    # explicit same-profile request
    same_profile_explicit = (target_profiles == [requester])

    # 4. cross-project protected boundary (fail closed when project is scoped
    #    but no same-profile ownership can be confirmed).
    if not same_profile_explicit and projects:
        return _deny(ReasonCode.DENY_CROSS_PROJECT, op, denied=projects)

    # 5. permitted same-profile local scope
    if same_profile_explicit:
        allowed_profiles = [requester]
    else:
        # implicit local (own scope); no explicit profile in scope
        allowed_profiles = []

    # Project / space permissions are LOCAL ONLY and add nothing to profiles.
    # Relations never expand scope (nothing here widens scope).
    allowed_projects = list(projects)
    allowed_spaces = list(spaces)

    if op == WRITE:
        # WRITE requires an explicitly targeted same-profile local scope.
        # Global/ambiguous write (no explicit same-profile target) is denied.
        if same_profile_explicit:
            return _allow(WRITE,
                          profiles=allowed_profiles,
                          projects=allowed_projects,
                          spaces=allowed_spaces,
                          reason=ReasonCode.ALLOW_LOCAL_WRITE)
        return _deny(ReasonCode.DENY_GLOBAL_WRITE, WRITE)

    # READ
    if same_profile_explicit:
        return _allow(READ,
                      profiles=allowed_profiles,
                      projects=allowed_projects,
                      spaces=allowed_spaces,
                      global_read=global_allowed,
                      reason=_ALLOW_LOCAL_READ)
    # implicit local + global read
    return _allow(READ,
                  profiles=allowed_profiles,
                  projects=allowed_projects,
                  spaces=allowed_spaces,
                  global_read=global_allowed,
                  reason=_ALLOW_GLOBAL_READ if global_allowed else _ALLOW_LOCAL_READ)


__all__ = ["evaluate"]
