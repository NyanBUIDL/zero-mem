"""M8.6 — M7 EvidenceSet integration of VERIFIED M8 graph/temporal/calibration.

This is the FINAL M8 increment. It integrates the already-VERIFIED M8.1–M8.5
capabilities into the existing M7.3 authorized EvidenceSet pipeline. It does NOT
redesign M7, does NOT introduce a second retrieval/authorization/injection
system, and does NOT widen the 5+3 EvidenceSet budget.

Conceptual pipeline (authoritative order, preserved):

    ZERO_MEM_ENABLED
        -> M7 route
        -> M5 authorization                       (sole authority; consumed, never made)
        -> authorized candidate domain            (M7.3 eligibility result)
        -> lifecycle / sensitivity eligibility    (M7.3, unchanged)
        -> M8.3 authorized graph metadata         (optional, explicit seed only)
        -> M8.4 authorized temporal metadata      (per-candidate valid-time classification)
        -> M8.5 deterministic calibration         (ordering / explanation metadata ONLY)
        -> existing M7 primary/supporting role    (M7.3 role authority preserved)
        -> bounded ordering / budget              (5 primary + 3 supporting, unchanged)
        -> EvidenceSet
        -> existing M7 safe DATA envelope

What this module does
---------------------

1. Re-orders each role pool (primary / supporting) by the VERIFIED M8.5
   calibration score, deterministically, within the role. A high-scoring
   supporting item never becomes primary (role authority preserved).
2. Attaches ``m8_metadata`` — bounded, deterministic, DATA-ONLY observation
   metadata (calibration score, reason codes, M8.4 temporal validity, M8.3
   relation distance, scope match, conflict presence, resource_type verbatim).
   It carries NO authority: no verification, no truth, no lifecycle, no conflict
   resolution, no supersession. It is escaped by M7.5 hardening before render.
3. Optionally enriches with M8.3 authorized relation distances when an explicit
   authorized relation seed is supplied (default: none — M7 routes carry no seed,
   so no graph expansion runs and no hidden graph material can influence output).

Invariants enforced (owner-frozen for M8.6)
-------------------------------------------

- M5 remains the SOLE authorization authority; this module makes no grant/deny
  decision and reaches no policy/writer surface.
- No numeric confidence threshold: calibration score is ORDERING / EXPLANATION
  metadata only. Eligibility is decided BEFORE calibration by M5 + lifecycle +
  sensitivity + M7.3. Low score alone never excludes, authorizes, or verifies.
- Authorization-first: only ALREADY-authorized candidates are described/calibrated.
- Unauthorized / hidden evidence has ZERO influence: each candidate is calibrated
  independently, so an added hidden candidate cannot move a visible score,
  ordering, count, or factor decomposition (M8.5 contract).
- Existence-leak safe: M8.3 graph read is authorization-first and bounded; edges
  to unauthorized nodes are withheld, so hidden neighbours never change degree,
  relation relevance, or any visible aggregate.
- M6.6 resource_type preserved verbatim (never flattened).
- Read-only, zero LLM, zero network, zero embedding operations, zero vector index.
- Graceful degradation: ANY failure during enrichment returns the UNCHANGED
  upstream EvidenceSet (safe M7 ordering). Degradation NEVER produces MORE
  visible evidence than the validated path.
"""

from __future__ import annotations

from dataclasses import field
from typing import Any, Mapping, Optional, Sequence, Tuple

from .contracts import EvidenceItem, EvidenceRole, EvidenceSet, MemoryRoute

# VERIFIED M8.5 public API (request-time only, no I/O, no authorization of its own).
from src.m8.calibration import (
    CalibrationError,
    order_calibrated,
)
from src.m8.retrieval_metadata import (
    RetrievalMetadataRequest,
    calibrate_authorized_items,
)


# Frozen M8.6 adapter version (diagnostic only; never consulted for logic).
M8_INTEGRATION_VERSION: str = "m8.6"


def _resource_type_of(item: Any) -> str:
    return getattr(item, "resource_type", "") or ""


def _evidence_id_of(item: Any) -> str:
    return getattr(item, "evidence_id", "") or ""


# EvidenceItem uses ``evidence_id`` as its stable identity; the VERIFIED M8.5
# ``build_candidate`` reads resource-type-specific identity attributes
# (event_id / decision_id / requirement_id / verification_id / artifact_id /
# charter_id). Rather than modify the frozen M8.5 module, the M8.6 adapter maps
# each EvidenceItem into a read-only calibration view (a Mapping) exposing the
# attributes ``build_candidate`` expects. This keeps src/m8 untouched.
_IDENTITY_ATTR_FOR_RESOURCE_TYPE: Mapping[str, str] = {
    "event": "event_id",
    "decision": "decision_id",
    "requirement": "requirement_id",
    "verification": "verification_id",
    "artifact": "artifact_id",
    "project_artifact": "artifact_id",
    "charter": "charter_id",
}


def _calibration_view(item: EvidenceItem, resource_type: str) -> Mapping[str, Any]:
    """Project an EvidenceItem into the attribute shape M8.5 build_candidate reads.

    Pure observation mapping; never forwards hidden/authorization material. All
    values are taken verbatim from the already-authorized EvidenceItem.
    """
    identity_attr = _IDENTITY_ATTR_FOR_RESOURCE_TYPE.get(resource_type, "id")
    ks = tuple(getattr(item, "knowledge_space_ids", ()) or ())
    knowledge_space_id = ks[0] if ks else None
    return {
        identity_attr: item.evidence_id,
        "id": item.evidence_id,
        "memory_type": getattr(item, "memory_type", None) or resource_type,
        "lifecycle_status": getattr(item, "lifecycle", None) or "active",
        "verification_status": getattr(item, "verification", None),
        "profile_id": getattr(item, "profile_id", None),
        "project_id": getattr(item, "project_id", None),
        "knowledge_space_id": knowledge_space_id,
        "knowledge_space_ids": ks,
        "created_at": getattr(item, "created_at", None),
        "trace_id": getattr(item, "trace_id", None),
        "source_event_id": None,  # EvidenceItem does not carry this; provenance stays required-only
        "has_conflict": False,
        "retrieval_relevance": None,
    }


def _build_metadata_request(router: Any) -> RetrievalMetadataRequest:
    """Construct an authorization-first M8.5 metadata request from the router.

    Every identifier is carried VERBATIM from the explicit router request; nothing
    is inferred. Authorized sets reflect the explicit target scope only. No
    wall-clock is read (``as_of`` is None), so M8.4 valid-time stays
    present-or-unknown and unknown stays unknown. No relation distances are
    asserted here — those come from the explicit optional M8.3 seed read below.
    """
    requesting = getattr(router, "requesting_profile_id", None) or None
    project = getattr(router, "project_id", None) or None
    ks_ids = tuple(getattr(router, "knowledge_space_ids", ()) or ())
    target_profiles = tuple(getattr(router, "target_profile_ids", ()) or ())
    knowledge_space_id = ks_ids[0] if ks_ids else None

    authorized_profiles: Tuple[str, ...]
    if target_profiles:
        authorized_profiles = tuple(target_profiles)
    elif requesting is not None:
        authorized_profiles = (requesting,)
    else:
        authorized_profiles = ()

    authorized_projects: Tuple[str, ...] = (project,) if project is not None else ()
    authorized_spaces: Tuple[str, ...] = tuple(ks_ids)

    return RetrievalMetadataRequest(
        requesting_profile_id=requesting,
        project_id=project,
        knowledge_space_id=knowledge_space_id,
        authorized_profile_ids=authorized_profiles,
        authorized_project_ids=authorized_projects,
        authorized_knowledge_space_ids=authorized_spaces,
        global_read_allowed=False,
        as_of=None,
        relation_distances={},
    )


def _optional_relation_distances(
    store: Any,
    router: Any,
    relation_seed: Optional[Tuple[str, str]],
) -> Mapping[str, int]:
    """Compute M8.3 authorized relation distances for eligible candidate ids.

    Runs ONLY when an explicit authorized relation seed is supplied. The read is
    authorization-first (M5 re-checks every candidate's own scope) and bounded
    (frozen M8.3 bounds). Edges to unauthorized nodes are withheld, so a hidden
    neighbour can never become an authorized candidate and therefore can never
    change a visible relation distance. Returns {} when no seed is supplied —
    which is the normal M7 path (no seed) — so no graph expansion runs.
    """
    if relation_seed is None or store is None:
        return {}
    try:
        from src.m8.graph_access import (
            DEFAULT_BOUNDS,
            GraphAccessService,
            GraphReadRequest,
        )
        from src.access import AuthorizedReadService

        if not isinstance(store, AuthorizedReadService):
            # The service wraps the store; rebuild one keyed to the same store so
            # the read inherits identical read-only + authorization guarantees.
            auth = AuthorizedReadService(
                store,
                requesting_profile_id=getattr(router, "requesting_profile_id", None) or None,
            )
        else:
            auth = store

        svc = GraphAccessService(auth)
        req = GraphReadRequest(
            resource_id=relation_seed[1],
            resource_type=relation_seed[0],
            requesting_profile_id=getattr(router, "requesting_profile_id", None) or None,
            project_id=getattr(router, "project_id", None) or None,
            knowledge_space_id=(
                getattr(router, "knowledge_space_ids", ()) or (None,)
            )[0] if getattr(router, "knowledge_space_ids", ()) else None,
            bounds=DEFAULT_BOUNDS,
        )
        result = svc.read_subgraph(req)
        if not result.authorized:
            return {}
        distances: dict[str, int] = {}
        for node in result.nodes:
            rid = getattr(node, "resource_id", None) or (
                node.get("resource_id") if isinstance(node, Mapping) else None
            )
            rtype = getattr(node, "resource_type", None) or (
                node.get("resource_type") if isinstance(node, Mapping) else None
            )
            depth = getattr(node, "depth", None)
            if rid is None or rtype is None or depth is None:
                continue
            distances[f"{rtype}:{rid}"] = int(depth)
        return distances
    except Exception:
        # Fail closed: no relation distances rather than a partial/leaky view.
        return {}


def _calibrate_pool(
    items: Sequence[EvidenceItem],
    request: RetrievalMetadataRequest,
) -> Tuple[EvidenceItem, ...]:
    """Order one role pool (primary or supporting) by M8.5 calibration score.

    Calibration is ORDERING metadata only. It must NEVER add or drop an item:
    every authorized candidate passed in is returned in the output, just
    re-ordered by deterministic calibration score. Role is preserved by the
    caller (primary pool in, primary pool out).

    Per resource_type (calibration is per-resource_type), each group is scored;
    a candidate flagged ``included=False`` by M8.5 is NOT dropped — it is
    assigned a neutral score (0.5) and its role/existence is preserved. Only a
    true ``CalibrationError`` (malformed input) falls back to upstream order.
    """
    if not items:
        return tuple(items)

    # Stable index so we can always recover the original EvidenceItem even if the
    # view mutates identity, and so we never lose an item.
    indexed = list(enumerate(items))

    # Group by resource_type; preserve original index for deterministic mapping.
    by_type: dict[str, list[tuple[int, EvidenceItem]]] = {}
    for idx, it in indexed:
        by_type.setdefault(_resource_type_of(it), []).append((idx, it))

    scores: dict[int, float] = {}
    for rtype, group in by_type.items():
        views = [_calibration_view(it, rtype) for _, it in group]
        try:
            res = calibrate_authorized_items(views, rtype, request)
        except CalibrationError:
            # Malformed group: assign neutral scores and keep upstream order.
            for idx, _ in group:
                scores.setdefault(idx, 0.5)
            continue
        by_view = {v["id"]: v for v in views}
        for cal in res.decisions:
            orig_idx = next(
                (i for i, it in group if _evidence_id_of(it) == cal.resource_id),
                None,
            )
            if orig_idx is None:
                continue
            # included=False -> keep the item but with neutral score (no authority).
            scores[orig_idx] = cal.result.score if (cal.included and cal.result is not None) else 0.5

    # Any index not scored (shouldn't happen) gets neutral.
    for idx, _ in indexed:
        scores.setdefault(idx, 0.5)

    # Deterministic global ordering across resource types:
    # score desc, resource_type asc, evidence_id asc. NEVER drops an item.
    ordered = sorted(
        indexed,
        key=lambda iv: (
            -scores[iv[0]],
            _resource_type_of(iv[1]),
            _evidence_id_of(iv[1]),
        ),
    )
    return tuple(it for _, it in ordered)


def _attach_m8_metadata(
    es: EvidenceSet,
    router: Any,
) -> EvidenceSet:
    """Attach bounded M8 DATA-only metadata keyed by evidence_id.

    Pure observation only. No authority. The M8.5 calibration and M8.4 temporal
    classification are re-derived here from the SAME authorized items (idempotent
    and deterministic) so the metadata reflects exactly what the ordering used.
    """
    request = _build_metadata_request(router)
    metadata: dict[str, Any] = {}

    for item in es.primary_evidence + es.supporting_evidence:
        rtype = _resource_type_of(item)
        entry: dict[str, Any] = {
            "resource_type": rtype,
            "scope_factor": None,
            "temporal_factor": None,
            "conflict_present": False,
            "graph_relation_distance": None,
            "calibration_score": None,
            "calibration_explanation": (),
        }
        try:
            res = calibrate_authorized_items([_calibration_view(item, rtype)], rtype, request)
        except CalibrationError:
            # M8.5 cannot score this resource_type (unknown to the VERIFIED engine).
            # The item is STILL present in the EvidenceSet (role/eligibility are M7's
            # domain). We record a bounded DATA marker with no score rather than
            # silently omitting metadata, so consumers always see the resource_type.
            entry["score_unavailable"] = True
            metadata[_evidence_id_of(item)] = entry
            continue
        decision = res.decisions[0] if res.decisions else None
        if decision is None:
            metadata[_evidence_id_of(item)] = entry
            continue
        if decision.included and decision.result is not None:
            r = decision.result
            factors = r.factor_values or {}
            # scope_priority and temporal_validity are factors; the raw scope_match /
            # temporal_validity classification lives on the candidate, not the result,
            # so we expose the factor-derived observability only (DATA, no authority).
            entry["scope_factor"] = factors.get("scope_priority")
            entry["temporal_factor"] = factors.get("temporal_validity")
            entry["conflict_present"] = bool(
                r.conflict_basis if hasattr(r, "conflict_basis") else False
            )
            entry["calibration_score"] = r.score
            entry["calibration_explanation"] = tuple(
                r.reason_codes if hasattr(r, "reason_codes") else ()
            )
        else:
            entry["exclusion_code"] = decision.exclusion_code
        metadata[_evidence_id_of(item)] = entry

    return EvidenceSet(
        route=es.route,
        memory_needed=es.memory_needed,
        used_scopes=es.used_scopes,
        primary_evidence=es.primary_evidence,
        supporting_evidence=es.supporting_evidence,
        conflicts=es.conflicts,
        insufficient_evidence=es.insufficient_evidence,
        external_current_required=es.external_current_required,
        omitted_count=es.omitted_count,
        estimated_tokens=es.estimated_tokens,
        reason_code=es.reason_code,
        m8_metadata=metadata,
        corpus_evidence=es.corpus_evidence,
    )


def enrich_evidence_set(
    es: EvidenceSet,
    router: Any,
    *,
    store: Any = None,
    relation_seed: Optional[Tuple[str, str]] = None,
) -> EvidenceSet:
    """Integrate VERIFIED M8 capabilities into an M7.3 EvidenceSet.

    Safe by construction:
    - Returns the UNCHANGED ``es`` on any enrichment failure (graceful
      degradation; never more visible evidence than the validated path).
    - Reorders each role pool by M8.5 calibration score, preserving M7 role
      authority (primary stays primary, supporting stays supporting).
    - Attaches DATA-only ``m8_metadata``; carries no authority.
    - Only ALREADY-authorized candidates are described/calibrated (authorization
      first). Hidden evidence cannot influence a visible result (M8.5 contract).
    - M8.3 graph enrichment runs only with an explicit authorized ``relation_seed``;
      otherwise no traversal occurs.
    """
    if not isinstance(es, EvidenceSet) or not es.memory_needed:
        return es

    try:
        request = _build_metadata_request(router)
        if relation_seed is not None:
            # Optional M8.3 authorized relation distances (explicit seed only).
            distances = _optional_relation_distances(store, router, relation_seed)
            if distances:
                object.__setattr__(request, "relation_distances", dict(distances))

        ordered_primary = _calibrate_pool(es.primary_evidence, request)
        ordered_supporting = _calibrate_pool(es.supporting_evidence, request)

        reordered = EvidenceSet(
            route=es.route,
            memory_needed=es.memory_needed,
            used_scopes=es.used_scopes,
            primary_evidence=ordered_primary,
            supporting_evidence=ordered_supporting,
            conflicts=es.conflicts,
            insufficient_evidence=es.insufficient_evidence,
            external_current_required=es.external_current_required,
            omitted_count=es.omitted_count,
            estimated_tokens=es.estimated_tokens,
            reason_code=es.reason_code,
            m8_metadata=es.m8_metadata,
            corpus_evidence=es.corpus_evidence,
        )
        return _attach_m8_metadata(reordered, router)
    except Exception:
        # Fail closed: preserve the upstream validated EvidenceSet untouched.
        return es


def describe_m8_integration() -> dict[str, Any]:
    """Introspectable description of the M8.6 integration boundary."""
    return {
        "m8_integration_version": M8_INTEGRATION_VERSION,
        "schema_version": 10,
        "integrates": ["m8.3_graph", "m8.4_temporal", "m8.5_calibration"],
        "authorization_first": True,
        "makes_authorization_decisions": False,
        "calibration_is_ordering_only": True,
        "numeric_confidence_threshold": False,
        "preserves_m7_roles": True,
        "preserves_evidenceset_budget": True,
        "preserves_resource_type": True,
        "unauthorized_zero_influence": True,
        "existence_leak_safe": True,
        "graceful_degradation": True,
        "performs_io": False,
        "performs_traversal_by_default": False,
        "performs_traversal_with_explicit_seed": True,
        "zero_llm": True,
        "zero_network": True,
        "no_embedding_ops": True,
        "no_vector_ops": True,
        "no_hermes_core_change": True,
        "no_m6_tool_change": True,
    }


__all__ = [
    "M8_INTEGRATION_VERSION",
    "enrich_evidence_set",
    "describe_m8_integration",
]
