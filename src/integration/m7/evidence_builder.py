"""M7.3 — authorized evidence eligibility + bounded EvidenceSet construction.

Pipeline (no Hermes context mutation, no LLM, no network, no writes):

    MemoryRouteDecision
      -> route-to-retrieval mapping (M5 AuthorizedReadService; authorization BEFORE retrieval)
      -> eligible authorized candidates (eligibility.py)
      -> conflict grouping
      -> deterministic bounded selection (budget.py)
      -> EvidenceSet

The authorized read boundary is the VERIFIED M5 AuthorizedReadService. M7.3 never
touches raw SQLite/FTS/JSONL or M4 tables directly, and never calls the grant
administration service or any write path. Resource-type isolation and linked-resource
re-checks are already enforced by M5; M7.3 reuses them unchanged. M7.3 produces only a
structured EvidenceSet for a later increment to consume; it performs no context mutation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

from src.access import AccessRequest
from src.access.authorized_read import AuthorizedReadService, AuthorizedResult

from .contracts import (
    EvidenceItem, EvidenceRole, EvidenceSet, MemoryRoute, MemoryRouteDecision, RouterRequest,
)
from .eligibility import DEFAULT_SENSITIVITY_CEILING, is_eligible
from .budget import select_evidence, estimate_tokens

# M4 resource_type mapping (M5.2 _M4_RESOURCE_TYPE mirror).
_M4_RT = {
    "charter": "charter",
    "requirement": "requirement",
    "decision": "decision",
    "state": "state",
    "verification": "verification",
    "artifact": "artifact",
}

_MAX_PRIMARY = 5
_MAX_SUPPORTING = 3
_TOKEN_BUDGET = 6000  # ~3k-6k target envelope


def _item_attr(item: Any, *names: str, default: Any = None) -> Any:
    for n in names:
        if hasattr(item, n):
            return getattr(item, n)
    return default


def _to_evidence_item(item: Any, route: MemoryRoute, resource_type: str,
                      role: EvidenceRole, eligibility_reason: str) -> EvidenceItem:
    # CorpusHit (M10.5) carries its own identity/summary fields.
    if resource_type == "corpus_unit":
        hit = item  # type: ignore[assignment]
        summary = (getattr(hit, "normalized_text", None) or "")[:280] or None
        return EvidenceItem(
            evidence_id=getattr(hit, "unit_id", "unknown"),
            resource_type="corpus_unit",
            memory_type="corpus_unit",
            trace_id=getattr(hit, "source_id", None),
            route=route.value,
            content_source="metadata_only",
            summary=summary,
            source=getattr(hit, "source_ref", None),
            created_at=None,
            lifecycle=getattr(hit, "lifecycle_status", None),
            verification=None,
            confidence=None,
            sensitivity=getattr(hit, "sensitivity", None),
            profile_id=getattr(hit, "profile_id", None),
            project_id=getattr(hit, "project_id", None),
            knowledge_space_ids=tuple(
                [k] if (k := getattr(hit, "knowledge_space_id", None)) else ()
            ),
            provenance=f"corpus_unit:{getattr(hit, 'unit_id', 'unknown')}",
            role=role,
            eligibility_reason=eligibility_reason,
        )
    evidence_id = str(_item_attr(item, "event_id", "requirement_id", "decision_id",
                             "verification_id", "artifact_id", "charter_id", "id") or "unknown")
    summary = _item_attr(item, "statement", "title", "summary", "content",
                        "verification_summary", "decision_summary")
    # Redaction: do not surface raw secret bodies; M3 view is metadata_only.
    return EvidenceItem(
        evidence_id=evidence_id,
        resource_type=resource_type,
        memory_type=_item_attr(item, "event_type", "memory_type") or resource_type,
        trace_id=_item_attr(item, "trace_id"),
        route=route.value,
        content_source="metadata_only",
        summary=(str(summary)[:280] if summary else None),
        source=_item_attr(item, "source"),
        created_at=_item_attr(item, "created_at", "effective_at", "timestamp"),
        lifecycle=_item_attr(item, "lifecycle_status", "lifecycle"),
        verification=_item_attr(item, "verification_status", "verification"),
        confidence=_item_attr(item, "confidence"),
        sensitivity=_item_attr(item, "sensitivity"),
        profile_id=_item_attr(item, "profile_id"),
        project_id=_item_attr(item, "project_id"),
        knowledge_space_ids=tuple(_item_attr(item, "knowledge_space_ids", default=()) or ()),
        provenance=f"trace:{_item_attr(item, 'trace_id') or evidence_id}",
        role=role,
        eligibility_reason=eligibility_reason,
    )


def _authorized_retrieve(svc: AuthorizedReadService, decision: MemoryRouteDecision,
                         request: AccessRequest, router: RouterRequest,
                         grants: Optional[list] = None) -> List[Tuple[Any, str]]:
    """Route -> authorized retrieval. Returns (raw_item, resource_type) pairs for
    authorized, non-error results only. Denials/errors yield nothing here (the
    EvidenceSet marks insufficient_evidence later if needed)."""
    out: List[Tuple[Any, str]] = []
    route = decision.route

    if route is MemoryRoute.NO_MEMORY:
        return out
    if route is MemoryRoute.EXTERNAL_CURRENT:
        return out  # no current-data retrieval from Zero-Mem

    project_id = (request.project_ids or [None])[0]

    if route is MemoryRoute.PROJECT:
        if project_id:
            for rt, method in (
                ("charter", svc.m4_charter),
                ("requirement", svc.m4_requirements),
                ("decision", svc.m4_decisions),
                ("state", svc.m4_current_state),
                ("verification", svc.m4_verifications),
                ("artifact", svc.m4_artifacts),
            ):
                res = method(request, project_id, grants=grants)
                if res.allowed and not res.denied:
                    for it in res.items:
                        out.append((it, rt))

    elif route is MemoryRoute.USER:
        res = svc.query_events(request, profile_filter=request.requesting_profile_id, grants=grants)
        if res.allowed and not res.denied:
            for it in res.items:
                out.append((it, "event"))

    elif route is MemoryRoute.SESSION:
        if router.session_id:
            res = svc.query_events(request, session_filter=router.session_id, grants=grants)
            if res.allowed and not res.denied:
                for it in res.items:
                    out.append((it, "event"))

    elif route is MemoryRoute.RESEARCH:
        text = router.normalized_text or ""
        res = svc.search_text(request, text, grants=grants)
        if res.allowed and not res.denied:
            for it in res.items:
                out.append((it, "event"))

    elif route is MemoryRoute.GLOBAL:
        res = svc.query_events(request, grants=grants)
        if res.allowed and not res.denied:
            for it in res.items:
                out.append((it, "event"))

    return out


def _conflict_groups(items: List[EvidenceItem]) -> List[dict]:
    """Deterministic conflict representation. Group items that share a trace but
    disagree on a current value; preserve IDs/provenance; never invent a winner."""
    groups: dict = {}
    for it in items:
        key = it.trace_id or it.evidence_id
        groups.setdefault(key, []).append(it)
    conflicts = []
    for key, grp in groups.items():
        if len(grp) > 1:
            statuses = {(_item_attr(i, "lifecycle_status", "lifecycle") or "") for i in grp}
            if len(statuses) > 1 or any(
                (_item_attr(i, "lifecycle_status", "lifecycle") or "") == "conflicted" for i in grp
            ):
                conflicts.append({
                    "trace_id": key,
                    "items": [i.evidence_id for i in grp],
                    "resolved": False,
                })
    return conflicts


def build_evidence_set(
    decision: MemoryRouteDecision,
    svc: AuthorizedReadService,
    router: RouterRequest,
    *,
    grants: Optional[list] = None,
    sensitivity_ceiling: str = DEFAULT_SENSITIVITY_CEILING,
    max_primary: int = _MAX_PRIMARY,
    max_supporting: int = _MAX_SUPPORTING,
    token_budget: int = _TOKEN_BUDGET,
    semantic: Optional[Any] = None,
) -> EvidenceSet:
    """Construct a bounded EvidenceSet from an authorized route decision.

    Authorization is performed by `svc` (M5) BEFORE any item is eligible. M7.3 adds
    a second independent eligibility gate, deterministic selection, conflict grouping,
    and an immutable EvidenceSet. No injection, no writes, no LLM, no network.

    M10.5: authorized CORPUS evidence (resource_type="corpus_unit") is retrieved
    through the SAME M5 authorization-first stack and fused into the SAME bounded
    budget (5 primary / 3 supporting / 8 total) as memory evidence. Corpus units
    are DATA only and never gain authority. The permanent 8-total bound is
    preserved: corpus items compete for the same primary/supporting slots.

    Identity (requesting_profile_id) is taken from the explicit RouterRequest field;
    it is never inferred from route/project/session.
    """
    route = decision.route
    requesting_profile_id = router.requesting_profile_id
    # Same-profile default: M5/M6 require the requesting profile to appear in
    # target_profile_ids for same-profile project access (M6.6 semantics). We never
    # widen scope — only default to the caller's own profile when none supplied.
    target_profiles = list(router.target_profile_ids) or (
        [requesting_profile_id] if requesting_profile_id else None
    )
    # Build the M5 AccessRequest from explicit RouterRequest fields (verbatim, no
    # inference). Route is NOT authorization; M5 decides.
    request = AccessRequest(
        operation="READ",
        requesting_profile_id=requesting_profile_id,
        target_profile_ids=target_profiles,
        project_ids=[router.project_id] if router.project_id else None,
        knowledge_space_ids=list(router.knowledge_space_ids) or None,
        resource_type=_route_resource_type(route),
        include_global=True,
    )

    # no_memory: zero retrieval, zero candidates, zero tokens.
    if route is MemoryRoute.NO_MEMORY:
        return EvidenceSet(
            route=route, memory_needed=False, used_scopes=frozenset(),
            primary_evidence=(), supporting_evidence=(), conflicts=(),
            insufficient_evidence=False, external_current_required=False,
            omitted_count=0, estimated_tokens=0, reason_code="NO_MEMORY",
        )

    # external_current: no current-data retrieval; historical memory is insufficient.
    if route is MemoryRoute.EXTERNAL_CURRENT:
        return EvidenceSet(
            route=route, memory_needed=True, used_scopes=frozenset(),
            primary_evidence=(), supporting_evidence=(), conflicts=(),
            insufficient_evidence=True, external_current_required=True,
            omitted_count=0, estimated_tokens=0, reason_code="EXTERNAL_CURRENT_REQUIRED",
        )

    raw = _authorized_retrieve(svc, decision, request, router, grants=grants)

    # ---- M10.5: authorized corpus retrieval (same M5 auth stack) ---------
    # Runs for any route that carries query text (RESEARCH explicitly; also
    # when explicit research intent is present), and is authorization-first:
    # corpus_unit_search() performs the M5 policy gate before discovery, so
    # unauthorized corpus units can never become candidates. Corpus hits are
    # represented as EvidenceItem(resource_type="corpus_unit") and fused with
    # memory candidates into the SAME bounded budget below.
    corpus_items: List[Any] = []
    if router.normalized_text and router.normalized_text.strip():
        try:
            from src.access import AccessRequest as _AR
            cres = svc.corpus_unit_search(
                _AR(
                    operation="READ",
                    requesting_profile_id=requesting_profile_id,
                    target_profile_ids=target_profiles,
                    project_ids=[router.project_id] if router.project_id else None,
                    knowledge_space_ids=list(router.knowledge_space_ids) or None,
                    resource_type="corpus_unit",
                    include_global=True,
                ),
                router.normalized_text,
                metadata={
                    "project_id": router.project_id,
                    "knowledge_space_id": (
                        router.knowledge_space_ids[0] if router.knowledge_space_ids else None
                    ),
                },
                semantic=semantic,
                grants=grants,
            )
            if cres.allowed and not cres.denied:
                for hit in cres.items:
                    corpus_items.append((hit, "corpus_unit"))
        except Exception:
            # Corpus retrieval failures must NEVER broaden or leak memory
            # evidence; degrade gracefully to memory-only (fail safe).
            corpus_items = []

    # Eligibility gate (authorization already done by M5).
    eligible: List[Tuple[EvidenceItem, Any]] = []
    for item, rt in (raw + corpus_items):
        res = is_eligible(item, route.value, sensitivity_ceiling=sensitivity_ceiling,
                          resource_type=rt,
                          promote_state_in_project=(route is MemoryRoute.PROJECT))
        if not res.eligible:
            continue
        ev = _to_evidence_item(item, route, rt,
                                EvidenceRole.PRIMARY if res.as_primary else EvidenceRole.SUPPORTING,
                                res.reason)
        eligible.append((ev, res))

    if not eligible:
        # Memory needed but no authorized eligible evidence -> insufficient.
        return EvidenceSet(
            route=route, memory_needed=True, used_scopes=frozenset(),
            primary_evidence=(), supporting_evidence=(), conflicts=(),
            insufficient_evidence=True, external_current_required=False,
            omitted_count=0, estimated_tokens=0, reason_code="INSUFFICIENT_EVIDENCE",
        )

    conflicts = _conflict_groups([e for e, _ in eligible])
    sel = select_evidence(eligible, max_primary=max_primary,
                          max_supporting=max_supporting, token_budget=token_budget,
                          route=route)

    used_scopes = frozenset(
        s for s in (
            (router.project_id and [router.project_id] or []) +
            list(router.target_profile_ids) +
            list(router.knowledge_space_ids)
        )
    )

    # M10.5: convenience mirror of the corpus items selected into the bounded
    # primary/supporting sets (they already share the same 5/3/8 budget).
    corpus_selected = tuple(
        e for e in (list(sel.primary) + list(sel.supporting))
        if e.resource_type == "corpus_unit"
    )

    es = EvidenceSet(
        route=route,
        memory_needed=True,
        used_scopes=used_scopes,
        primary_evidence=tuple(sel.primary),
        supporting_evidence=tuple(sel.supporting),
        corpus_evidence=corpus_selected,
        conflicts=tuple(conflicts),
        insufficient_evidence=False,
        external_current_required=False,
        omitted_count=sel.omitted_count,
        estimated_tokens=sel.estimated_tokens,
        reason_code="EVIDENCE_READY",
    )

    # M8.6 — integrate VERIFIED M8.3/M8.4/M8.5 into the M7 EvidenceSet.
    # Authorization-first: only already-authorized candidates are enriched. The
    # store (svc._store) is passed for OPTIONAL bounded M8.3 graph enrichment,
    # which runs ONLY when an explicit authorized relation seed is supplied (it is
    # not here, so no graph expansion fires on the standard M7 path). The
    # enrichment is wrapped so any failure degrades gracefully to the validated
    # M7 EvidenceSet (never more visible evidence).
    try:
        from .m8_integration import enrich_evidence_set as _enrich
        store = getattr(svc, "_store", None)
        es = _enrich(es, router, store=store)
    except Exception:
        # Fail closed: keep the upstream validated EvidenceSet untouched.
        pass

    # V130-04 — bounded temporal annotation (annotation-only, fail-open).
    # as_of validated via M8.1 normalize_timestamp; malformed raises (fail closed).
    # Internal read failures keep the validated EvidenceSet with temporal=None.
    as_of = getattr(router, "as_of", None)
    if as_of is not None:
        try:
            from .temporal_annotation import annotate_temporal
            conn = getattr(store, "conn", None) if store is not None else None
            ks = tuple(getattr(router, "knowledge_space_ids", ()) or ())
            es = annotate_temporal(
                es, svc, conn,
                requesting_profile_id=getattr(router, "requesting_profile_id", None),
                project_id=getattr(router, "project_id", None),
                knowledge_space_id=ks[0] if ks else None,
                as_of_raw=as_of,
            )
        except Exception:
            # Fail closed on request validation errors (malformed as_of).
            raise

    return es


def _route_resource_type(route: MemoryRoute) -> Optional[str]:
    """Exact resource_type for routes that imply one (preserves M6.6 isolation).
    None otherwise; M5 base policy / per-call M4 gates handle those."""
    if route is MemoryRoute.SESSION:
        return "relation"  # session evidence leans on event/relation retrieval
    if route is MemoryRoute.USER:
        return "event"
    if route is MemoryRoute.RESEARCH:
        return "event"
    return None
