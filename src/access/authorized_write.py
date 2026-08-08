"""M5.4 — WRITE authorization (persistent WRITE grants) + authorization-before-mutation.

HARD SECURITY BOUNDARY (directive "Authorization-before-mutation"):

    WriteRequest -> AccessRequest(operation=WRITE)
                 -> base M5.1 policy
                 -> persistent grant resolution
                 -> AccessDecision
                 -> ONLY if ALLOW: canonical/domain mutation

The writer/projector is NEVER invoked before the policy decision. Tests prove a
denied write never reaches the target writer/projector.

Grant resolution is delegated to ``resolver.resolve_write_grant`` which enforces
the full predicate set including the WRITE verification predicate (resolved
READ-ONLY from M4). A normal WRITE request can NEVER administer grants: the
grant-admin surface is a separate module (``admin``) reachable only via
``GrantAdminService``. There is no code path from an ``AccessRequest`` to
``GrantAdminService``.

No LLM, no network. Deterministic.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from .contracts import WRITE, AccessDecision, AccessRequest, AllowedScope, ReasonCode
from .policy import evaluate
from .resolver import resolve_write_grant


# ---------------------------------------------------------------------------
# WRITE authorization
# ---------------------------------------------------------------------------

def authorize_write(request: AccessRequest, store,
                    verification_lookup: Callable[[str], Optional[object]]) -> AccessDecision:
    """Authorize a WRITE request.

    Order (plan §11.8 / M5.1 WRITE base policy preserved):
      1. Base M5.1 policy. Same-profile local WRITE is allowed within the
         explicitly authorized local scope.
      2. Cross-profile WRITE falls through the base policy as DENY.
      3. Persistent WRITE grant resolution: if exactly one active, non-revoked,
         target-matching, verification-verified WRITE grant exists, ALLOW with the
         grant's exact scope.
      4. Conflict (multiple matching WRITE grants, no deterministic narrowing) ->
         DENY_POLICY_CONFLICT (fail closed; no timestamp/most-permissive winner).
      5. Otherwise -> DENY_CROSS_PROFILE_WRITE (default deny).

    The decision never mutates anything; it only reads derived grant state and the
    M4 verification substrate (read-only).
    """
    try:
        req = request.validate()
    except ValueError:
        return AccessDecision(
            allow=False,
            normalized_scope=AllowedScope(operation=WRITE),
            reason_code=ReasonCode.DENY_INVALID_REQUEST.value)

    base = evaluate(req)
    # Same-profile local WRITE: base policy already allows within local scope.
    if base.allow and not _requires_grant(req):
        return base

    # Cross-profile (or otherwise base-denied) WRITE: try persistent WRITE grant.
    target_type, target_id = _primary_target(req)
    if target_type is None:
        # No explicit single grant target (ambiguous/implicit global write): defer to
        # the base policy's already-computed specific reason (e.g. DENY_GLOBAL_WRITE).
        return base

    resolved = resolve_write_grant(
        store.conn if hasattr(store, "conn") else store,
        req.requesting_profile_id,
        verification_lookup,
        target_type,
        target_id,
        resource_type=req.resource_type,
    )

    if resolved is None:
        return AccessDecision(
            allow=False,
            normalized_scope=AllowedScope(operation=WRITE),
            reason_code=ReasonCode.DENY_CROSS_PROFILE_WRITE.value)
    if resolved.get("conflict"):
        return AccessDecision(
            allow=False,
            normalized_scope=AllowedScope(operation=WRITE),
            denied_scopes=[target_type + ":" + target_id],
            reason_code=ReasonCode.DENY_POLICY_CONFLICT.value,
            grant_refs=resolved.get("grant_ids", []))

    # Authorize the EXACT grant scope only (no broadening).
    scope = AllowedScope(
        operation=WRITE,
        allowed_profile_ids=[target_id] if target_type == "profile" else [],
        allowed_project_ids=[target_id] if target_type == "project" else [],
        allowed_knowledge_space_ids=[target_id] if target_type == "knowledge_space" else [],
        global_read_allowed=False,
        resource_types=resolved.get("resource_types"),
        isolated=req.isolated_mode,
    )
    return AccessDecision(
        allow=True,
        normalized_scope=scope,
        reason_code=ReasonCode.ALLOW_EXPLICIT_CROSS_PROFILE_WRITE.value,
        grant_refs=[resolved["grant_id"]])


def _requires_grant(req: AccessRequest) -> bool:
    """True if the request targets a scope the base policy denies (cross-profile)."""
    requester = req.requesting_profile_id
    target_profiles = list(req.target_profile_ids or [])
    projects = list(req.project_ids or [])
    spaces = list(req.knowledge_space_ids or [])
    if any(p != requester for p in target_profiles):
        return True
    if projects or spaces:
        # Cross-project / knowledge-space WRITE is not same-profile local.
        return True
    return False


def _primary_target(req: AccessRequest) -> tuple:
    """Single (target_type, target_id) the WRITE targets; None if ambiguous/empty."""
    target_profiles = list(req.target_profile_ids or [])
    projects = list(req.project_ids or [])
    spaces = list(req.knowledge_space_ids or [])
    # Prefer the most specific explicit target; grants are scoped to ONE target_type.
    if len(target_profiles) == 1 and not projects and not spaces:
        return ("profile", target_profiles[0])
    if len(projects) == 1 and not target_profiles and not spaces:
        return ("project", projects[0])
    if len(spaces) == 1 and not target_profiles and not projects:
        return ("knowledge_space", spaces[0])
    if not target_profiles and not projects and not spaces:
        # Implicit local write: base policy handles same-profile local; for grant
        # resolution we have no explicit cross-profile target -> deny.
        return (None, None)
    # Multiple/ambiguous target dimensions: cannot resolve a single grant scope.
    return (None, None)


# ---------------------------------------------------------------------------
# Authorization-before-mutation proof
# ---------------------------------------------------------------------------

def authorize_then_write(request: AccessRequest, store,
                         verification_lookup: Callable[[str], Optional[object]],
                         writer_fn: Callable[[AccessRequest], Any]) -> tuple:
    """Authorize first, THEN mutate. Returns (decision, mutation_result|None).

    The ``writer_fn`` is invoked ONLY when the decision is ALLOW. A denied write
    never invokes the writer/projector. This is the structural guarantee tested
    by the "denied writer not invoked" / "allowed writer invoked exactly once"
    acceptance items.
    """
    decision = authorize_write(request, store, verification_lookup)
    if not decision.allow:
        return decision, None
    result = writer_fn(request)
    return decision, result


class AuthorizedWriteService:
    """Thin facade for WRITE authorization (mirrors AuthorizedReadService)."""

    def __init__(self, store, verification_lookup: Callable[[str], Optional[object]]) -> None:
        self._store = store
        self._verify = verification_lookup

    def authorize(self, request: AccessRequest) -> AccessDecision:
        return authorize_write(request, self._store, self._verify)

    def authorize_then_write(self, request: AccessRequest,
                             writer_fn: Callable[[AccessRequest], Any]) -> tuple:
        return authorize_then_write(request, self._store, self._verify, writer_fn)


__all__ = [
    "authorize_write",
    "authorize_then_write",
    "AuthorizedWriteService",
]
