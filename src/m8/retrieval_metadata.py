"""M8.5 — internal retrieval candidate metadata integration.

A thin, INTERNAL adapter that attaches deterministic calibration metadata to
retrieval candidates that M5 has ALREADY authorized. It is not a new tool, not
a new read path, and not a retrieval redesign:

* it issues **no** query, opens **no** connection, and reads **no** table;
* it makes, caches, widens, and infers **no** access decision — M5 remains the
  sole authorization authority and this module cannot reach a policy, grant, or
  write surface, because it imports none of them;
* it **never mutates** the candidates handed to it, nor any store, projection,
  grant, lifecycle, verification, or project state;
* it does **not** change existing M3 ordering or result limits. Calibration
  ordering is returned ALONGSIDE the authorized candidates as separate
  metadata, for a caller that explicitly opts in.

Authorization-first, structurally
---------------------------------

The only accepted input is the typed result of an M5 authorized read. A denied
result yields empty metadata: no score, no count, no ordering, no explanation.
Because every candidate is calibrated independently (see
:mod:`src.m8.calibration`), and because a candidate whose scope falls outside
the explicitly authorized scope is EXCLUDED before any factor is computed, an
unauthorized or hidden record cannot influence a visible score, factor value,
ordering position, tie-break, count, or explanation.

Order of operations (docs/plans/plan-m8.md §22.1.8)::

    request
      -> M5 authorization                (upstream; consumed here, never made)
      -> lifecycle / sensitivity gates   (upstream)
      -> authorized candidate domain     (the input to this module)
      -> M8.3 / M8.4 authorized metadata (explicitly supplied by the caller)
      -> factor derivation
      -> calibration
      -> deterministic ordering

Nothing here reads a wall clock. When the caller supplies an explicit temporal
reference it is used through the M8.4 predicate; otherwise valid-time is
classified as present-or-unknown and unknown stays unknown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Mapping, Optional, Sequence, Tuple

from .calibration import (
    CalibrationCandidate,
    CalibrationDecision,
    CalibrationError,
    PROVENANCE_COMPLETE,
    PROVENANCE_INCOMPLETE,
    PROVENANCE_REQUIRED_ONLY,
    SCOPE_COMPOSED,
    SCOPE_EXACT,
    SCOPE_GLOBAL_FALLBACK,
    SCOPE_UNAUTHORIZED,
    TEMPORAL_INVALID,
    TEMPORAL_UNKNOWN,
    TEMPORAL_VALID,
    calibrate_candidate,
    calibrate_candidates,
    included_results,
)
from .calibration_contract import CalibrationResult
from .temporal_read import TemporalDimension, as_of_match
from .vocabulary import RESOURCE_TYPES

#: Frozen version of this internal metadata adapter.
RETRIEVAL_METADATA_VERSION: Final[str] = "m8.5"

#: Attribute names, in priority order, that carry a candidate's stable identity
#: in the existing M3/M4 result shapes. Identity is READ, never minted.
_IDENTITY_ATTRS: Final[Tuple[str, ...]] = (
    "event_id",
    "requirement_id",
    "decision_id",
    "verification_id",
    "artifact_id",
    "charter_id",
    "id",
)

#: Attribute names carrying the candidate's memory/evidence type.
_MEMORY_TYPE_ATTRS: Final[Tuple[str, ...]] = ("event_type", "memory_type")

#: Attribute names carrying transaction (record) time.
_TRANSACTION_TIME_ATTRS: Final[Tuple[str, ...]] = (
    "created_at",
    "timestamp",
    "observed_at",
)

#: Attribute names carrying explicit valid/effective time (M8.4 valid dimension).
_VALID_TIME_ATTRS: Final[Tuple[str, ...]] = ("effective_at", "valid_from")


def _attr(item: Any, *names: str) -> Any:
    """Read the first present attribute (or mapping key). Never writes."""
    for name in names:
        if isinstance(item, Mapping):
            if name in item and item[name] is not None:
                return item[name]
            continue
        value = getattr(item, name, None)
        if value is not None:
            return value
    return None


def _nonempty_str(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value.strip() else None


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetrievalMetadataRequest:
    """The authorized scope context for one calibration pass.

    Every identifier is supplied EXPLICITLY by the caller and carried verbatim;
    nothing is inferred, and no identity is derived from the candidates
    themselves. ``authorized_*`` sets describe the scope M5 actually granted, so
    a candidate outside them fails closed instead of being scored.

    ``as_of`` is an explicit temporal reference. When it is ``None`` no clock is
    read and no timestamp is invented.
    """

    requesting_profile_id: Optional[str] = None
    project_id: Optional[str] = None
    knowledge_space_id: Optional[str] = None
    authorized_profile_ids: Tuple[str, ...] = ()
    authorized_project_ids: Tuple[str, ...] = ()
    authorized_knowledge_space_ids: Tuple[str, ...] = ()
    global_read_allowed: bool = False
    as_of: Optional[str] = None
    #: Explicit authorized M8.3 relation distances, keyed by
    #: ``"<resource_type>:<resource_id>"``. Supplied by the caller from an
    #: authorized bounded graph read. This module performs NO traversal of its
    #: own and never derives a distance from an unauthorized edge.
    relation_distances: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "requesting_profile_id", "project_id", "knowledge_space_id", "as_of",
        ):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise CalibrationError(name, "invalid_identifier")
        for name in (
            "authorized_profile_ids",
            "authorized_project_ids",
            "authorized_knowledge_space_ids",
        ):
            value = getattr(self, name)
            if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
                raise CalibrationError(name, "not_a_sequence")
            for entry in value:
                if not isinstance(entry, str) or not entry.strip():
                    raise CalibrationError(name, "invalid_identifier")
            object.__setattr__(self, name, tuple(value))
        if not isinstance(self.global_read_allowed, bool):
            raise CalibrationError("global_read_allowed", "not_a_boolean")
        if not isinstance(self.relation_distances, Mapping):
            raise CalibrationError("relation_distances", "not_a_mapping")
        for key, distance in self.relation_distances.items():
            if not isinstance(key, str) or not key.strip():
                raise CalibrationError("relation_distances", "invalid_identifier")
            if isinstance(distance, bool) or not isinstance(distance, int):
                raise CalibrationError("relation_distances", "not_an_integer")
        object.__setattr__(self, "relation_distances", dict(self.relation_distances))


@dataclass(frozen=True)
class RetrievalMetadataResult:
    """Calibration metadata for one authorized retrieval read.

    ``authorized`` mirrors the upstream M5 decision verbatim. On a denial every
    field is empty: no score, no ordering, no count, no explanation, and no hint
    that anything exists.

    ``ordered`` is calibration ORDERING METADATA. It does not replace, reorder,
    or truncate the caller's own authorized result, and it carries no authority.
    ``excluded`` reports only candidates the caller was ALREADY authorized to
    see that were removed by an eligibility rule — never a hidden record.
    """

    authorized: bool
    ordered: Tuple[CalibrationResult, ...] = ()
    decisions: Tuple[CalibrationDecision, ...] = ()
    metadata_version: str = RETRIEVAL_METADATA_VERSION

    @property
    def excluded(self) -> Tuple[CalibrationDecision, ...]:
        return tuple(d for d in self.decisions if not d.included)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorized": self.authorized,
            "metadata_version": self.metadata_version,
            "ordered": [r.to_dict() for r in self.ordered],
            "decisions": [d.to_dict() for d in self.decisions],
        }


# ---------------------------------------------------------------------------
# Deterministic classification of one authorized candidate
# ---------------------------------------------------------------------------


def classify_scope(
    item: Any, request: RetrievalMetadataRequest
) -> str:
    """Classify a candidate's scope against the EXPLICIT authorized scope.

    Exact requested scope -> ``exact``; an explicitly authorized composed or
    cross-space scope -> ``composed``; an authorized global/unbound record ->
    ``global_fallback``. Anything else fails closed as ``unauthorized`` and is
    excluded before calibration rather than scored as zero.
    """
    profile = _nonempty_str(_attr(item, "profile_id"))
    project = _nonempty_str(_attr(item, "project_id"))
    space = _nonempty_str(_attr(item, "knowledge_space_id"))

    requested = (
        request.requesting_profile_id,
        request.project_id,
        request.knowledge_space_id,
    )
    actual = (profile, project, space)

    # Exact: every scope dimension the caller specified matches, and the
    # candidate declares nothing outside it.
    exact = True
    for want, got in zip(requested, actual):
        if want is None:
            if got is not None:
                exact = False
                break
        elif want != got:
            exact = False
            break
    if exact:
        return SCOPE_EXACT

    # Composed: every declared dimension lies inside the explicitly authorized
    # sets (a cross-space or multi-project read the grant actually covers).
    authorized_sets = (
        request.authorized_profile_ids,
        request.authorized_project_ids,
        request.authorized_knowledge_space_ids,
    )
    composed = False
    for got, want, allowed in zip(actual, requested, authorized_sets):
        if got is None:
            continue
        if got == want:
            continue
        if got in allowed:
            composed = True
            continue
        return SCOPE_UNAUTHORIZED
    if composed:
        return SCOPE_COMPOSED

    # Global/unbound fallback: the record declares no scope at all and the
    # caller holds an explicit global read.
    if actual == (None, None, None) and request.global_read_allowed:
        return SCOPE_GLOBAL_FALLBACK
    return SCOPE_UNAUTHORIZED


def classify_candidate_provenance(item: Any) -> str:
    """Classify retrieval-candidate provenance completeness.

    Consumes the EXISTING authoritative provenance rule already enforced by the
    M7.3 eligibility gate: an identity plus at least one of record time or
    source event id is REQUIRED. Optional provenance (``trace_id`` and
    ``source_event_id``) merely distinguishes complete from required-only. No
    field is ever fabricated or backfilled to raise a score.
    """
    identity = _nonempty_str(_attr(item, *_IDENTITY_ATTRS))
    created_at = _nonempty_str(_attr(item, *_TRANSACTION_TIME_ATTRS))
    source_event_id = _nonempty_str(_attr(item, "source_event_id"))
    trace_id = _nonempty_str(_attr(item, "trace_id"))
    if identity is None or (created_at is None and source_event_id is None):
        return PROVENANCE_INCOMPLETE
    if trace_id is None or source_event_id is None:
        return PROVENANCE_REQUIRED_ONLY
    return PROVENANCE_COMPLETE


def classify_temporal_validity(
    item: Any, request: RetrievalMetadataRequest
) -> str:
    """Classify valid-time using M8.4 semantics only.

    No explicit valid-time signal -> ``unknown`` (never invented, never
    penalised into exclusion). With a signal and an explicit ``as_of``
    reference, the M8.4 valid-dimension predicate decides valid vs invalid.
    With a signal and no reference, no clock is read and the declared validity
    stands. Transaction time is never conflated with valid time.
    """
    valid_signal = _nonempty_str(_attr(item, *_VALID_TIME_ATTRS))
    if valid_signal is None:
        return TEMPORAL_UNKNOWN
    if request.as_of is None:
        return TEMPORAL_VALID
    fact = {
        "created_at": _attr(item, *_TRANSACTION_TIME_ATTRS),
        "effective_at": _attr(item, "effective_at"),
        "valid_from": _attr(item, "valid_from"),
        "valid_until": _attr(item, "valid_until"),
    }
    if as_of_match(fact, TemporalDimension.VALID, request.as_of):
        return TEMPORAL_VALID
    return TEMPORAL_INVALID


def build_candidate(
    item: Any,
    resource_type: str,
    request: RetrievalMetadataRequest,
) -> CalibrationCandidate:
    """Describe ONE already-authorized retrieval item in calibration terms.

    ``resource_type`` is supplied by the authorized read that produced the item
    and is carried through verbatim — the permanent M6.6 invariant means a
    highly scored artifact never becomes an event, a relation, or a generic
    resource. Nothing about any other candidate is consulted.
    """
    if resource_type not in RESOURCE_TYPES:
        raise CalibrationError("resource_type", "unknown_resource_type")
    identity = _nonempty_str(_attr(item, *_IDENTITY_ATTRS))
    if identity is None:
        raise CalibrationError("resource_id", "missing_required_field")

    memory_type = _nonempty_str(_attr(item, *_MEMORY_TYPE_ATTRS)) or resource_type
    lifecycle = _nonempty_str(_attr(item, "lifecycle_status", "lifecycle")) or "active"
    verification = _nonempty_str(_attr(item, "verification_status", "verification"))
    if verification == "":
        verification = None

    key = f"{resource_type}:{identity}"
    distance = request.relation_distances.get(key)
    return CalibrationCandidate(
        resource_type=resource_type,
        resource_id=identity,
        memory_type=memory_type,
        lifecycle_status=lifecycle,
        scope_match=classify_scope(item, request),
        provenance_class=classify_candidate_provenance(item),
        temporal_validity=classify_temporal_validity(item, request),
        has_valid_time=_nonempty_str(_attr(item, *_VALID_TIME_ATTRS)) is not None,
        has_transaction_time=(
            _nonempty_str(_attr(item, *_TRANSACTION_TIME_ATTRS)) is not None
        ),
        has_conflict=bool(_attr(item, "has_conflict") or False),
        relation_distance=distance,
        retrieval_relevance=_attr(item, "retrieval_relevance"),
        profile_id=_nonempty_str(_attr(item, "profile_id")),
        project_id=_nonempty_str(_attr(item, "project_id")),
        knowledge_space_id=_nonempty_str(_attr(item, "knowledge_space_id")),
        # V130-03 (D-2026-08-22-06): the item's own authoritative verification
        # observation, for the verification-strength fallback of memory types
        # absent from the closed memory-type strength table.
        verification_status=verification,
    )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def calibrate_authorized_items(
    items: Sequence[Any],
    resource_type: str,
    request: RetrievalMetadataRequest,
) -> RetrievalMetadataResult:
    """Calibrate a sequence of ALREADY-AUTHORIZED items of one resource_type.

    The caller is responsible for having obtained ``items`` from an M5
    authorized read. This function performs no authorization and no I/O; it
    only describes and orders what it was given.
    """
    if isinstance(items, (str, bytes)) or not isinstance(items, Sequence):
        raise CalibrationError("items", "not_a_sequence")
    if not isinstance(request, RetrievalMetadataRequest):
        raise CalibrationError("request", "not_a_retrieval_metadata_request")
    decisions = tuple(
        calibrate_candidate(
            build_candidate(i, resource_type, request),
            verification_status_echo=_nonempty_str(
                _attr(i, "verification_status", "verification")
            )
            or None,
        )
        for i in items
    )
    return RetrievalMetadataResult(
        authorized=True,
        ordered=included_results(decisions),
        decisions=decisions,
    )


def calibrate_authorized_result(
    authorized_result: Any,
    resource_type: str,
    request: RetrievalMetadataRequest,
) -> RetrievalMetadataResult:
    """Calibrate the items of an M5 ``AuthorizedResult``, honouring the decision.

    The upstream decision is CONSUMED, never re-made or second-guessed: a
    denial (or a downstream error) produces an empty, unauthorized metadata
    result that leaks no existence, no count, and no ordering. Revocation is
    therefore honoured immediately, because nothing is cached between calls.

    The result object is duck-typed on purpose: this module deliberately
    imports no ``src.access`` symbol, so it has no path to a policy, grant, or
    write surface even by accident.
    """
    denied = bool(getattr(authorized_result, "denied", True))
    allowed = bool(getattr(authorized_result, "allowed", False))
    error = getattr(authorized_result, "error", None)
    if denied or not allowed or error is not None:
        return RetrievalMetadataResult(authorized=False, ordered=(), decisions=())
    items = getattr(authorized_result, "items", None) or []
    return calibrate_authorized_items(items, resource_type, request)


def describe_retrieval_metadata() -> dict[str, Any]:
    """Introspectable description of this internal integration boundary."""
    return {
        "retrieval_metadata_version": RETRIEVAL_METADATA_VERSION,
        "schema_version": 11,
        "authorization_first": True,
        "makes_authorization_decisions": False,
        "consumes_m5_decision": True,
        "performs_io": False,
        "performs_traversal": False,
        "mutates_input": False,
        "persists_scores": False,
        "changes_m3_ordering": False,
        "changes_result_limits": False,
        "adds_tool_surface": False,
        "reads_wall_clock": False,
        "cross_candidate_normalization": False,
        "preserves_resource_type": True,
    }


__all__ = [
    "RETRIEVAL_METADATA_VERSION",
    "RetrievalMetadataRequest",
    "RetrievalMetadataResult",
    "classify_scope",
    "classify_candidate_provenance",
    "classify_temporal_validity",
    "build_candidate",
    "calibrate_authorized_items",
    "calibrate_authorized_result",
    "describe_retrieval_metadata",
]
