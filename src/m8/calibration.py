"""M8.5 — deterministic calibration engine (pure; no I/O, no authorization).

This module implements the calibration formula approved by the owner and
recorded in ``plan-m8.md`` §22.1 (resolution of M8-OQ-6 and M8-OQ-7). It
computes deterministic, bounded, explainable ORDERING METADATA for candidates
that have ALREADY passed M5 authorization and lifecycle/sensitivity
eligibility upstream.

What this module is
-------------------

A pure function of its typed input. Given the same candidate it returns the
same result, byte for byte. There is no clock read, no randomness, no hash
ordering, no database, no network, and no model call. It holds no mutable
module state and no cache.

What this module is NOT
-----------------------

- **Not authorization.** Nothing here consults, caches, widens, or infers an
  access decision. M5 remains the sole authorization authority. An
  unauthorized candidate must never reach this module; when a caller marks a
  candidate's scope ``unauthorized`` it is EXCLUDED before any factor is
  computed, never scored as zero and kept.
- **Not verification.** ``verification_status`` is echoed through unchanged.
  A high result never sets, upgrades, or substitutes for it.
- **Not truth.** A result never resolves a conflict, never picks a winner,
  never infers supersession, and never promotes an ``assistant_claim``.
- **Not lifecycle authority.** Lifecycle is consumed as authoritative input.
  Calibration never promotes, demotes, or redefines it.
- **Not recency.** A newer timestamp earns nothing. ``temporal_validity``
  distinguishes explicitly-valid from genuinely-unknown time only; unknown
  time stays unknown and no timestamp is ever invented.
- **Not centrality.** There is no degree, path-count, link-count, or
  repetition input. ``relation_relevance`` reflects only the distance of an
  explicitly requested, already-authorized M8.3 relation.

The approved formula (plan-m8.md §22.1.2), multiplicative, no weights::

    final_score = retrieval_match
                * scope_priority
                * verification_strength
                * provenance_completeness
                * temporal_validity
                * lifecycle_eligibility
                * conflict_penalty
                * relation_relevance

Every factor is in ``[0.0, 1.0]``, so the product is too. Malformed input
(NaN, infinity, out of range, unknown enum member) FAILS CLOSED and is never
clamped: clamping would hide a defective factor derivation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Mapping, Optional, Sequence, Tuple

from .calibration_contract import (
    ALLOWED_FACTOR_NAMES,
    CALIBRATION_CONTRACT_VERSION,
    CalibrationResult,
    SCORE_MAX,
    SCORE_MIN,
)
from .graph_bounds import MAX_TRAVERSAL_DEPTH
from .vocabulary import (
    validate_lifecycle_status,
    validate_resource_type,
    VocabularyError,
)

#: Frozen M8.5 calibration-engine version. A result is comparable only to
#: another result produced by the same engine version AND the same M8.1
#: contract version.
CALIBRATION_ENGINE_VERSION: Final[str] = "m8.5"

#: Canonical multiplication order. Fixed so the floating-point product is
#: reproducible bit for bit, independent of dict/set iteration.
FACTOR_ORDER: Final[Tuple[str, ...]] = (
    "retrieval_match",
    "scope_priority",
    "verification_strength",
    "provenance_completeness",
    "temporal_validity",
    "lifecycle_eligibility",
    "conflict_penalty",
    "relation_relevance",
)

_POSITIVE_INFINITY: Final[float] = float("inf")
_NEGATIVE_INFINITY: Final[float] = float("-inf")


# ---------------------------------------------------------------------------
# Closed input vocabularies (plan-m8.md §22.1.3)
# ---------------------------------------------------------------------------

#: How the candidate's own scope relates to the authorized request scope.
#: ``unauthorized`` is an EXCLUSION marker, never a zero-valued factor.
SCOPE_EXACT: Final[str] = "exact"
SCOPE_COMPOSED: Final[str] = "composed"
SCOPE_GLOBAL_FALLBACK: Final[str] = "global_fallback"
SCOPE_UNAUTHORIZED: Final[str] = "unauthorized"

SCOPE_MATCHES: Final[frozenset[str]] = frozenset({
    SCOPE_EXACT, SCOPE_COMPOSED, SCOPE_GLOBAL_FALLBACK, SCOPE_UNAUTHORIZED,
})

#: Approved ``scope_priority`` contributions. ``unauthorized`` has no value on
#: purpose: it is excluded before calibration.
SCOPE_PRIORITY_VALUES: Final[Mapping[str, float]] = {
    SCOPE_EXACT: 1.0,
    SCOPE_COMPOSED: 0.9,
    SCOPE_GLOBAL_FALLBACK: 0.8,
}

#: Approved ``verification_strength`` contributions, keyed by the EXISTING
#: memory/evidence type names (``src.capture.event_types.EventType`` values and
#: the M5 resource-type literals). This table is CLOSED: an unrecognized type
#: fails closed rather than receiving a guessed value.
VERIFICATION_STRENGTH_VALUES: Final[Mapping[str, float]] = {
    "verified_state": 1.0,
    "verification": 1.0,
    "decision": 0.9,
    "tool_observation": 0.9,
    "user_statement": 0.8,
    "assistant_claim": 0.6,
    "inference": 0.5,
}

#: Provenance completeness classification.
PROVENANCE_COMPLETE: Final[str] = "complete"
PROVENANCE_REQUIRED_ONLY: Final[str] = "required_only"
PROVENANCE_INCOMPLETE: Final[str] = "incomplete"

PROVENANCE_CLASSES: Final[frozenset[str]] = frozenset({
    PROVENANCE_COMPLETE, PROVENANCE_REQUIRED_ONLY, PROVENANCE_INCOMPLETE,
})

PROVENANCE_COMPLETENESS_VALUES: Final[Mapping[str, float]] = {
    PROVENANCE_COMPLETE: 1.0,
    PROVENANCE_REQUIRED_ONLY: 0.75,
}

#: Optional provenance fields. Their absence lowers the factor to 0.75; it
#: never excludes, and it is never backfilled.
OPTIONAL_PROVENANCE_FIELDS: Final[Tuple[str, ...]] = (
    "source_event_id",
    "trace_id",
)

#: Temporal validity classification, in M8.4 terms. ``unknown`` means the
#: source declares no valid-time signal — it is NOT an invented timestamp and
#: NOT a recency reward.
TEMPORAL_VALID: Final[str] = "valid"
TEMPORAL_UNKNOWN: Final[str] = "unknown"
TEMPORAL_INVALID: Final[str] = "invalid"

TEMPORAL_VALIDITIES: Final[frozenset[str]] = frozenset({
    TEMPORAL_VALID, TEMPORAL_UNKNOWN, TEMPORAL_INVALID,
})

TEMPORAL_VALIDITY_VALUES: Final[Mapping[str, float]] = {
    TEMPORAL_VALID: 1.0,
    TEMPORAL_UNKNOWN: 0.75,
}

#: Lifecycle values that are NOT eligible evidence. Mirrors the existing
#: authoritative M7.3 rule (``_INELIGIBLE_LIFECYCLE``) without importing the M7
#: injection package. Calibration consumes this rule; it never redefines it.
INELIGIBLE_LIFECYCLE: Final[frozenset[str]] = frozenset({"deleted"})

#: The authoritative M4 lifecycle marker for a preserved, unresolved conflict.
CONFLICTED_LIFECYCLE: Final[str] = "conflicted"

#: Approved ``conflict_penalty`` contributions.
CONFLICT_PENALTY_NONE: Final[float] = 1.0
CONFLICT_PENALTY_UNRESOLVED: Final[float] = 0.5

#: Approved ``relation_relevance`` contributions, keyed by authorized relation
#: distance in hops. ``None`` (no relation context requested) is 1.0. Anything
#: beyond the frozen M8.3 traversal bound is NOT ELIGIBLE.
RELATION_RELEVANCE_VALUES: Final[Mapping[int, float]] = {
    0: 1.0,
    1: 0.9,
    2: 0.8,
}

#: Neutral value used when the upstream authorized candidate carries no
#: approved normalized retrieval-relevance signal. No normalization function is
#: invented, and normalization never consults other candidates.
RETRIEVAL_MATCH_NEUTRAL: Final[float] = 1.0


# ---------------------------------------------------------------------------
# Closed exclusion vocabulary
# ---------------------------------------------------------------------------

EXCLUDED_UNAUTHORIZED_SCOPE: Final[str] = "excluded_unauthorized_scope"
EXCLUDED_PROVENANCE_INCOMPLETE: Final[str] = "excluded_provenance_incomplete"
EXCLUDED_TEMPORAL_INVALID: Final[str] = "excluded_temporal_invalid"
EXCLUDED_LIFECYCLE_INELIGIBLE: Final[str] = "excluded_lifecycle_ineligible"
EXCLUDED_RELATION_BEYOND_BOUNDS: Final[str] = "excluded_relation_beyond_bounds"

EXCLUSION_CODES: Final[Tuple[str, ...]] = (
    EXCLUDED_LIFECYCLE_INELIGIBLE,
    EXCLUDED_PROVENANCE_INCOMPLETE,
    EXCLUDED_RELATION_BEYOND_BOUNDS,
    EXCLUDED_TEMPORAL_INVALID,
    EXCLUDED_UNAUTHORIZED_SCOPE,
)


class CalibrationError(ValueError):
    """Sanitized calibration-engine violation.

    Names the offending field and a stable reason code only. It never echoes
    candidate content, SQL, filesystem paths, or any hidden-resource detail.
    """

    def __init__(self, field_name: str, reason: str) -> None:
        super().__init__(f"calibration_error: {reason}: {field_name}")
        self.field_name = field_name
        self.reason = reason


# ---------------------------------------------------------------------------
# Typed candidate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CalibrationCandidate:
    """One ALREADY-AUTHORIZED candidate, described in observational terms.

    Every field is an observation of authoritative state, never a judgement.
    There is deliberately no grant field, no allow/deny field, and no weight
    field: there is nowhere for an access decision or a caller-tuned formula to
    be smuggled in.

    ``scope_match`` describes the candidate's own scope relative to the
    authorized request scope; ``unauthorized`` triggers exclusion. Scope
    identifiers are carried verbatim so profile / project / knowledge-space and
    ``resource_type`` identity survive calibration intact (permanent M6.6
    invariant); they are never aggregated across candidates.
    """

    resource_type: str
    resource_id: str
    memory_type: str
    lifecycle_status: str
    scope_match: str
    provenance_class: str
    temporal_validity: str
    has_valid_time: bool = False
    has_transaction_time: bool = False
    has_conflict: bool = False
    relation_distance: Optional[int] = None
    retrieval_relevance: Optional[float] = None
    profile_id: Optional[str] = None
    project_id: Optional[str] = None
    knowledge_space_id: Optional[str] = None

    def __post_init__(self) -> None:
        # Cross-module vocabulary errors are re-raised as this domain's own
        # sanitized error type (M8.1 sanitization contract): the message names
        # the field and the failure reason, never echoing raw upstream content.
        try:
            validated_rt = validate_resource_type(self.resource_type)
        except VocabularyError as exc:
            raise CalibrationError("resource_type", str(exc).split(":")[-1].strip()) from exc
        object.__setattr__(self, "resource_type", validated_rt)
        if not isinstance(self.resource_id, str) or not self.resource_id.strip():
            raise CalibrationError("resource_id", "missing_required_field")
        if not isinstance(self.memory_type, str) or not self.memory_type.strip():
            raise CalibrationError("memory_type", "missing_required_field")
        try:
            validated_ls = validate_lifecycle_status(self.lifecycle_status)
        except VocabularyError as exc:
            raise CalibrationError("lifecycle_status", str(exc).split(":")[-1].strip()) from exc
        object.__setattr__(self, "lifecycle_status", validated_ls)
        if self.scope_match not in SCOPE_MATCHES:
            raise CalibrationError("scope_match", "unknown_scope_match")
        if self.provenance_class not in PROVENANCE_CLASSES:
            raise CalibrationError("provenance_class", "unknown_provenance_class")
        if self.temporal_validity not in TEMPORAL_VALIDITIES:
            raise CalibrationError("temporal_validity", "unknown_temporal_validity")
        for flag in ("has_valid_time", "has_transaction_time", "has_conflict"):
            if not isinstance(getattr(self, flag), bool):
                raise CalibrationError(flag, "not_a_boolean")
        distance = self.relation_distance
        if distance is not None:
            if isinstance(distance, bool) or not isinstance(distance, int):
                raise CalibrationError("relation_distance", "not_an_integer")
            if distance < 0:
                raise CalibrationError("relation_distance", "below_minimum")
        for name in ("profile_id", "project_id", "knowledge_space_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise CalibrationError(name, "invalid_scope_identifier")


@dataclass(frozen=True)
class CalibrationDecision:
    """Outcome for one candidate: either a calibrated result or an exclusion.

    An excluded candidate carries NO result and NO score. It was removed from
    the scoring domain before any factor was computed, so it can never
    contribute to another candidate's value, ordering, or explanation.
    """

    resource_type: str
    resource_id: str
    included: bool
    result: Optional[CalibrationResult] = None
    exclusion_code: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "included": self.included,
            "result": None if self.result is None else self.result.to_dict(),
            "exclusion_code": self.exclusion_code,
        }


# ---------------------------------------------------------------------------
# Bounded-value helpers (fail closed; never clamp)
# ---------------------------------------------------------------------------


def _bounded_unit_value(value: Any, field_name: str) -> float:
    """Validate a factor value is a finite number within ``[0.0, 1.0]``.

    NaN, infinity, booleans, non-numbers, and out-of-range values all raise.
    Nothing is clamped: a clamp would silently hide a defective derivation.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CalibrationError(field_name, "not_a_number")
    numeric = float(value)
    if numeric != numeric:
        raise CalibrationError(field_name, "not_a_number")
    if numeric == _POSITIVE_INFINITY or numeric == _NEGATIVE_INFINITY:
        raise CalibrationError(field_name, "not_finite")
    if numeric < SCORE_MIN or numeric > SCORE_MAX:
        raise CalibrationError(field_name, "out_of_bounds")
    return numeric


# ---------------------------------------------------------------------------
# Factor derivation (plan-m8.md §22.1.3) — pure, one candidate at a time
# ---------------------------------------------------------------------------


def derive_retrieval_match(candidate: CalibrationCandidate) -> float:
    """Use the upstream normalized relevance verbatim, else the neutral 1.0.

    No BM25 / FTS / distance / rank normalization function is invented, and no
    other candidate is consulted — so a hidden candidate can never move this
    value.
    """
    if candidate.retrieval_relevance is None:
        return RETRIEVAL_MATCH_NEUTRAL
    return _bounded_unit_value(candidate.retrieval_relevance, "retrieval_match")


def derive_scope_priority(candidate: CalibrationCandidate) -> float:
    """Exact 1.0 / composed 0.9 / authorized global fallback 0.8.

    An ``unauthorized`` scope never reaches here: it is excluded upstream in
    :func:`calibrate_candidate`.
    """
    try:
        value = SCOPE_PRIORITY_VALUES[candidate.scope_match]
    except KeyError:
        raise CalibrationError("scope_priority", "unauthorized_scope_not_scorable") from None
    return _bounded_unit_value(value, "scope_priority")


def derive_verification_strength(candidate: CalibrationCandidate) -> float:
    """Look the memory/evidence type up in the CLOSED approved table.

    An unrecognized type fails closed. Calibration never guesses a value for a
    type the owner has not approved, and never promotes a claim by scoring it.
    """
    try:
        value = VERIFICATION_STRENGTH_VALUES[candidate.memory_type]
    except KeyError:
        raise CalibrationError("verification_strength", "unknown_memory_type") from None
    return _bounded_unit_value(value, "verification_strength")


def derive_provenance_completeness(candidate: CalibrationCandidate) -> float:
    """Complete 1.0 / required-only 0.75. Incomplete is excluded upstream."""
    try:
        value = PROVENANCE_COMPLETENESS_VALUES[candidate.provenance_class]
    except KeyError:
        raise CalibrationError(
            "provenance_completeness", "incomplete_provenance_not_scorable"
        ) from None
    return _bounded_unit_value(value, "provenance_completeness")


def derive_temporal_validity(candidate: CalibrationCandidate) -> float:
    """Explicitly valid 1.0 / genuinely unknown 0.75. Invalid is excluded.

    Unknown time stays unknown: it is neither invented nor penalised into
    exclusion, and a newer timestamp is never rewarded.
    """
    try:
        value = TEMPORAL_VALIDITY_VALUES[candidate.temporal_validity]
    except KeyError:
        raise CalibrationError(
            "temporal_validity", "invalid_temporal_state_not_scorable"
        ) from None
    return _bounded_unit_value(value, "temporal_validity")


def derive_lifecycle_eligibility(candidate: CalibrationCandidate) -> float:
    """Eligible lifecycle is 1.0. Ineligible lifecycle is excluded upstream."""
    if candidate.lifecycle_status in INELIGIBLE_LIFECYCLE:
        raise CalibrationError(
            "lifecycle_eligibility", "ineligible_lifecycle_not_scorable"
        )
    return 1.0


def has_unresolved_conflict(candidate: CalibrationCandidate) -> bool:
    """Consume authoritative M4 conflict state; never decide it.

    A conflict is unresolved when the candidate carries an explicit unresolved
    conflict marker, or when its authoritative lifecycle IS ``conflicted``.
    Where M4 already resolved a conflict, the authoritative lifecycle it wrote
    is what is read here — calibration adds no independent resolution.
    """
    return bool(candidate.has_conflict) or (
        candidate.lifecycle_status == CONFLICTED_LIFECYCLE
    )


def derive_conflict_penalty(candidate: CalibrationCandidate) -> float:
    """0.5 while an authoritative conflict is unresolved, else 1.0.

    The penalty marks that a conflict EXISTS. It never resolves it, never
    names a winner, and never converts the higher value into truth.
    """
    if has_unresolved_conflict(candidate):
        return CONFLICT_PENALTY_UNRESOLVED
    return CONFLICT_PENALTY_NONE


def derive_relation_relevance(candidate: CalibrationCandidate) -> float:
    """No relation context 1.0 / root 1.0 / one hop 0.9 / two hops 0.8.

    Only an explicitly requested, already-authorized M8.3 relation distance is
    accepted, and only within the frozen M8.3 traversal bound. This is not a
    degree, path-count, or centrality signal: a hidden node or edge cannot
    change it, because a hidden neighbour never becomes an authorized
    candidate in the first place.
    """
    distance = candidate.relation_distance
    if distance is None:
        return 1.0
    if distance > MAX_TRAVERSAL_DEPTH:
        raise CalibrationError(
            "relation_relevance", "relation_beyond_bounds_not_scorable"
        )
    try:
        value = RELATION_RELEVANCE_VALUES[distance]
    except KeyError:
        raise CalibrationError(
            "relation_relevance", "relation_beyond_bounds_not_scorable"
        ) from None
    return _bounded_unit_value(value, "relation_relevance")


#: Fixed derivation table, in canonical multiplication order.
_FACTOR_DERIVATIONS: Final[Tuple[Tuple[str, Any], ...]] = (
    ("retrieval_match", derive_retrieval_match),
    ("scope_priority", derive_scope_priority),
    ("verification_strength", derive_verification_strength),
    ("provenance_completeness", derive_provenance_completeness),
    ("temporal_validity", derive_temporal_validity),
    ("lifecycle_eligibility", derive_lifecycle_eligibility),
    ("conflict_penalty", derive_conflict_penalty),
    ("relation_relevance", derive_relation_relevance),
)


# ---------------------------------------------------------------------------
# Exclusion (BEFORE any factor is computed)
# ---------------------------------------------------------------------------


def exclusion_for(candidate: CalibrationCandidate) -> Optional[str]:
    """Return the exclusion code for a candidate, or ``None`` if it is scorable.

    Exclusion happens BEFORE calibration, in a fixed deterministic order. An
    excluded candidate is removed from the scoring domain outright; it is never
    scored as zero and retained, because a retained zero would still occupy a
    position, a count, and an explanation slot.
    """
    if candidate.scope_match == SCOPE_UNAUTHORIZED:
        return EXCLUDED_UNAUTHORIZED_SCOPE
    if candidate.lifecycle_status in INELIGIBLE_LIFECYCLE:
        return EXCLUDED_LIFECYCLE_INELIGIBLE
    if candidate.provenance_class == PROVENANCE_INCOMPLETE:
        return EXCLUDED_PROVENANCE_INCOMPLETE
    if candidate.temporal_validity == TEMPORAL_INVALID:
        return EXCLUDED_TEMPORAL_INVALID
    distance = candidate.relation_distance
    if distance is not None and (
        distance > MAX_TRAVERSAL_DEPTH or distance not in RELATION_RELEVANCE_VALUES
    ):
        return EXCLUDED_RELATION_BEYOND_BOUNDS
    return None


# ---------------------------------------------------------------------------
# Explainability
# ---------------------------------------------------------------------------


def _temporal_basis(candidate: CalibrationCandidate) -> str:
    """Descriptive M8.1 temporal-basis label. Never an ordering key."""
    if candidate.has_valid_time:
        return "valid_time_present"
    if candidate.has_transaction_time:
        return "transaction_time_only"
    return "no_temporal_data"


def _reason_codes(
    candidate: CalibrationCandidate, factor_values: Mapping[str, float]
) -> Tuple[str, ...]:
    """Stable reason codes from the M8.1 closed vocabulary only.

    Every code describes a VISIBLE factor contribution of THIS candidate. No
    code carries a hidden count, a hidden relation, or another candidate's
    state, so an explanation can never leak protected existence.
    """
    codes: list[str] = []
    if factor_values["verification_strength"] >= 1.0:
        codes.append("VERIFIED_SOURCE")
    else:
        codes.append("UNVERIFIED_SOURCE")
    if candidate.memory_type == "assistant_claim":
        codes.append("ASSISTANT_CLAIM_NOT_PROMOTED")
    if candidate.provenance_class == PROVENANCE_COMPLETE:
        codes.append("EXPLICIT_PROVENANCE_COMPLETE")
    if candidate.temporal_validity == TEMPORAL_VALID:
        codes.append("TEMPORAL_VALID_TIME_PRESENT")
    else:
        codes.append("TEMPORAL_VALID_TIME_ABSENT")
    codes.append("LIFECYCLE_ELIGIBLE")
    if has_unresolved_conflict(candidate):
        codes.append("CONFLICT_PRESENT")
    return tuple(sorted(codes))


# ---------------------------------------------------------------------------
# The approved formula
# ---------------------------------------------------------------------------


def combine_factors(factor_values: Mapping[str, float]) -> float:
    """Multiply the eight approved factors in canonical order.

    Requires exactly the eight approved factor names — an arbitrary factor
    injected by a caller, or a missing one, fails closed. Multiplication order
    is fixed by :data:`FACTOR_ORDER` so the floating-point product is
    reproducible.
    """
    if not isinstance(factor_values, Mapping):
        raise CalibrationError("factor_values", "not_a_mapping")
    names = set(factor_values)
    if names != set(FACTOR_ORDER):
        raise CalibrationError("factor_values", "factor_set_mismatch")
    product = 1.0
    for name in FACTOR_ORDER:
        product = product * _bounded_unit_value(factor_values[name], name)
    return _bounded_unit_value(product, "score")


def calibrate_candidate(
    candidate: CalibrationCandidate,
    *,
    verification_status_echo: Optional[str] = None,
) -> CalibrationDecision:
    """Calibrate ONE already-authorized candidate. Pure and deterministic.

    Order of operations is fixed and security-relevant: exclusion first, then
    factor derivation, then the product. Nothing about any other candidate is
    read at any step, so the result for this candidate is identical whether it
    is calibrated alone or alongside a thousand others — authorized or not.

    ``verification_status_echo`` is the authoritative M8.1 verification value
    observed on the upstream item, carried through UNCHANGED into the result.
    It participates in NO factor: calibration never sets, upgrades, or infers
    verification. When the authoritative value is ``None`` (no verification
    recorded) the echo stays ``None``.
    """
    if not isinstance(candidate, CalibrationCandidate):
        raise CalibrationError("candidate", "not_a_calibration_candidate")

    excluded = exclusion_for(candidate)
    if excluded is not None:
        return CalibrationDecision(
            resource_type=candidate.resource_type,
            resource_id=candidate.resource_id,
            included=False,
            result=None,
            exclusion_code=excluded,
        )

    factor_values: dict[str, float] = {}
    for name, derive in _FACTOR_DERIVATIONS:
        factor_values[name] = _bounded_unit_value(derive(candidate), name)

    final_score = combine_factors(factor_values)

    result = CalibrationResult(
        candidate_resource_type=candidate.resource_type,
        candidate_resource_id=candidate.resource_id,
        score=final_score,
        factor_values=factor_values,
        reason_codes=_reason_codes(candidate, factor_values),
        # Authoritative state echoed UNCHANGED: a maximal result never sets
        # verification and never promotes lifecycle. ``verification_status`` is
        # the M8.1 closed verification echo, NOT the calibration memory-type
        # axis; it is threaded through verbatim and never feeds a factor.
        verification_status=verification_status_echo,
        lifecycle_status=candidate.lifecycle_status,
        temporal_basis=_temporal_basis(candidate),
        conflict_basis=has_unresolved_conflict(candidate),
    )
    return CalibrationDecision(
        resource_type=candidate.resource_type,
        resource_id=candidate.resource_id,
        included=True,
        result=result,
        exclusion_code=None,
    )


def calibrate_candidates(
    candidates: Sequence[CalibrationCandidate],
) -> Tuple[CalibrationDecision, ...]:
    """Calibrate each candidate INDEPENDENTLY.

    There is no cross-candidate normalization of any kind: no mean, median,
    min/max, percentile, rank denominator, or frequency term. That is what
    makes a hidden candidate structurally incapable of moving a visible one.
    """
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise CalibrationError("candidates", "not_a_sequence")
    return tuple(calibrate_candidate(c) for c in candidates)


# ---------------------------------------------------------------------------
# Deterministic ordering (plan-m8.md §22.1.5)
# ---------------------------------------------------------------------------


def ordering_key(result: CalibrationResult) -> Tuple[float, str, str]:
    """Approved tie-break key: score DESC, resource_type ASC, identity ASC.

    Score is negated so a single ascending sort yields the approved order.
    Insertion order, SQLite row order, Python hash order, and wall-clock time
    are never consulted. This is the M8.5 calibration contract; M7's own
    ordering key remains owned by M7 and is deliberately not reused.
    """
    if not isinstance(result, CalibrationResult):
        raise CalibrationError("result", "not_a_calibration_result")
    return (
        -float(result.score),
        result.candidate_resource_type,
        result.candidate_resource_id,
    )


def order_calibrated(
    results: Sequence[CalibrationResult],
) -> Tuple[CalibrationResult, ...]:
    """Deterministically order calibrated results by the approved tie-break."""
    if isinstance(results, (str, bytes)) or not isinstance(results, Sequence):
        raise CalibrationError("results", "not_a_sequence")
    return tuple(sorted(results, key=ordering_key))


def included_results(
    decisions: Sequence[CalibrationDecision],
) -> Tuple[CalibrationResult, ...]:
    """Extract the results of INCLUDED decisions, in approved order."""
    kept = [d.result for d in decisions if d.included and d.result is not None]
    return order_calibrated(kept)


# ---------------------------------------------------------------------------
# Provenance classification helper
# ---------------------------------------------------------------------------

#: Retrieve-candidate provenance is governed by the M7.3 eligibility rule
#: (re-applied here as an observational classifier, NOT as a new gate): an
#: identity plus at least one of record time / source event id is REQUIRED.
#: The optional fields that distinguish complete from required-only are the
#: same ones the M7.3 rule treats as optional (see ``OPTIONAL_PROVENANCE_FIELDS``
#: below). This is intentionally NOT the M8.1 *derived-record* provenance
#: contract (relation_source / source_ref / ...), which applies to M8's
#: rebuildable projection rows, not to retrieval candidates. Calibration only
#: reads candidate provenance; it never writes a derived record.
REQUIRED_RETRIEVAL_PROVENANCE_FIELDS: Final[Tuple[str, ...]] = (
    "identity",
    "record_time_or_source_event_id",
)
RETRIEVAL_PROVENANCE_OPTIONAL_FIELDS = OPTIONAL_PROVENANCE_FIELDS


def classify_provenance(provenance: Any) -> str:
    """Classify a retrieval-candidate provenance as complete / required-only / incomplete.

    Required retrieval provenance (identity plus record time or source event
    id) missing or invalid -> ``incomplete`` and the candidate is EXCLUDED
    before calibration. Absent OPTIONAL provenance lowers the factor to 0.75 —
    it is never fabricated, never backfilled from a sibling record, and never
    inflated.
    """
    if isinstance(provenance, Mapping):
        payload = provenance
    else:
        return PROVENANCE_INCOMPLETE
    identity = payload.get("identity")
    if not isinstance(identity, str) or not identity.strip():
        return PROVENANCE_INCOMPLETE
    record_time = payload.get("record_time")
    source_event_id_req = payload.get("source_event_id")
    if not (
        (isinstance(record_time, str) and record_time.strip())
        or (isinstance(source_event_id_req, str) and source_event_id_req.strip())
    ):
        return PROVENANCE_INCOMPLETE
    for name in RETRIEVAL_PROVENANCE_OPTIONAL_FIELDS:
        value = payload.get(name)
        if not isinstance(value, str) or not value.strip():
            return PROVENANCE_REQUIRED_ONLY
    return PROVENANCE_COMPLETE


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------


def describe_calibration() -> dict[str, Any]:
    """Introspectable description of the approved M8.5 calibration engine."""
    return {
        "calibration_engine_version": CALIBRATION_ENGINE_VERSION,
        "calibration_contract_version": CALIBRATION_CONTRACT_VERSION,
        "scoring_implemented": True,
        "combination": "multiplicative_product",
        "independent_weights": False,
        "factor_order": list(FACTOR_ORDER),
        "allowed_factor_names": sorted(ALLOWED_FACTOR_NAMES),
        "score_min": SCORE_MIN,
        "score_max": SCORE_MAX,
        "clamps_out_of_range": False,
        "fails_closed": True,
        "tie_break": ["score_desc", "resource_type_asc", "resource_id_asc"],
        "exclusion_codes": list(EXCLUSION_CODES),
        "persisted": False,
        "request_time_only": True,
        "schema_version": 10,
        "confidence_threshold_implemented": False,
        "cross_candidate_normalization": False,
        "grants_authorization": False,
        "performs_verification": False,
        "resolves_conflicts": False,
        "overrides_lifecycle": False,
        "infers_supersession": False,
        "promotes_assistant_claim": False,
        "recency_is_not_authority": True,
        "uses_centrality": False,
        "reads_wall_clock": False,
    }


__all__ = [
    "CALIBRATION_ENGINE_VERSION",
    "FACTOR_ORDER",
    "SCOPE_EXACT",
    "SCOPE_COMPOSED",
    "SCOPE_GLOBAL_FALLBACK",
    "SCOPE_UNAUTHORIZED",
    "SCOPE_MATCHES",
    "SCOPE_PRIORITY_VALUES",
    "VERIFICATION_STRENGTH_VALUES",
    "PROVENANCE_COMPLETE",
    "PROVENANCE_REQUIRED_ONLY",
    "PROVENANCE_INCOMPLETE",
    "PROVENANCE_CLASSES",
    "PROVENANCE_COMPLETENESS_VALUES",
    "OPTIONAL_PROVENANCE_FIELDS",
    "TEMPORAL_VALID",
    "TEMPORAL_UNKNOWN",
    "TEMPORAL_INVALID",
    "TEMPORAL_VALIDITIES",
    "TEMPORAL_VALIDITY_VALUES",
    "INELIGIBLE_LIFECYCLE",
    "CONFLICTED_LIFECYCLE",
    "CONFLICT_PENALTY_NONE",
    "CONFLICT_PENALTY_UNRESOLVED",
    "RELATION_RELEVANCE_VALUES",
    "RETRIEVAL_MATCH_NEUTRAL",
    "EXCLUDED_UNAUTHORIZED_SCOPE",
    "EXCLUDED_PROVENANCE_INCOMPLETE",
    "EXCLUDED_TEMPORAL_INVALID",
    "EXCLUDED_LIFECYCLE_INELIGIBLE",
    "EXCLUDED_RELATION_BEYOND_BOUNDS",
    "EXCLUSION_CODES",
    "CalibrationError",
    "CalibrationCandidate",
    "CalibrationDecision",
    "derive_retrieval_match",
    "derive_scope_priority",
    "derive_verification_strength",
    "derive_provenance_completeness",
    "derive_temporal_validity",
    "derive_lifecycle_eligibility",
    "derive_conflict_penalty",
    "derive_relation_relevance",
    "has_unresolved_conflict",
    "exclusion_for",
    "combine_factors",
    "calibrate_candidate",
    "calibrate_candidates",
    "ordering_key",
    "order_calibrated",
    "included_results",
    "classify_provenance",
    "describe_calibration",
]
