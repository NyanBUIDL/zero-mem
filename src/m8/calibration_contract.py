"""M8.1 — frozen calibration input/output contract (NO scoring).

This module freezes the SHAPE of calibration data. It deliberately implements
no factor weights, no formula, no ranking, and no ordering. Scoring is M8.5 and
requires separate approval of the exact factors/weights (plan-m8.md M8-OQ-7).

What calibration IS (plan-m8.md §9): deterministic, bounded, explainable
evidence-ordering METADATA over candidates that have ALREADY passed
authorization and eligibility.

What calibration is NOT, enforced structurally here:

- **Not authorization.** ``CalibrationInput`` has no grant, no allow/deny, no
  ``requesting_profile_id``, and no policy field. A score can never grant
  access. Candidates are authorized BEFORE a calibration object is ever built,
  so unauthorized evidence cannot influence any visible score or explanation.
- **Not verification.** ``verification_status`` is carried through as a
  read-only observed input. A score never sets, upgrades, or substitutes for
  it, and never promotes an ``assistant_claim``.
- **Not truth.** A score never resolves a conflict, selects a winner, or
  overrides lifecycle. ``conflict_basis`` records that a conflict exists; it
  never records a resolution.
- **Not recency.** There is no timestamp weight and no "newer is better" field.
  ``temporal_basis`` is a descriptive label, not an ordering key.
- **Not centrality.** There is no degree, path-count, link-count, or
  repetition field. Those are explicitly forbidden truth factors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Mapping, Optional, Tuple

from .identity import canonical_json, content_hash
from .vocabulary import (
    validate_lifecycle_status,
    validate_resource_type,
    validate_verification_status,
)

#: Frozen calibration-contract version. A score is only comparable to another
#: score produced by the same version.
CALIBRATION_CONTRACT_VERSION: Final[str] = "v1"

#: Bounded score range. Any score outside it is a contract violation, not a
#: value to clamp — clamping would hide a defective factor computation.
SCORE_MIN: Final[float] = 0.0
SCORE_MAX: Final[float] = 1.0

#: Closed factor-name vocabulary. M8.5 may compute values for these; it may not
#: invent new factor names, and may never add centrality/degree/recency factors.
ALLOWED_FACTOR_NAMES: Final[frozenset[str]] = frozenset({
    "retrieval_match",
    "scope_priority",
    "verification_strength",
    "provenance_completeness",
    "temporal_validity",
    "lifecycle_eligibility",
    "conflict_penalty",
    "relation_relevance",
})

#: Closed reason-code vocabulary for explainability. Stable machine-readable
#: codes only; never raw prose as the sole contract.
ALLOWED_REASON_CODES: Final[frozenset[str]] = frozenset({
    "CALIBRATION_NOT_IMPLEMENTED",
    "VERIFIED_SOURCE",
    "UNVERIFIED_SOURCE",
    "ASSISTANT_CLAIM_NOT_PROMOTED",
    "EXPLICIT_PROVENANCE_COMPLETE",
    "PROVENANCE_INCOMPLETE",
    "TEMPORAL_VALID_TIME_PRESENT",
    "TEMPORAL_VALID_TIME_ABSENT",
    "LIFECYCLE_ELIGIBLE",
    "LIFECYCLE_INELIGIBLE",
    "CONFLICT_PRESENT",
    "INSUFFICIENT_EVIDENCE",
})

#: Closed temporal-basis vocabulary. Descriptive labels only — no ordering.
ALLOWED_TEMPORAL_BASIS: Final[frozenset[str]] = frozenset({
    "valid_time_present",
    "valid_time_absent",
    "transaction_time_only",
    "no_temporal_data",
})


class CalibrationContractError(ValueError):
    """Sanitized calibration-contract violation."""

    def __init__(self, field_name: str, reason: str) -> None:
        super().__init__(f"calibration_contract_error: {reason}: {field_name}")
        self.field_name = field_name
        self.reason = reason


@dataclass(frozen=True)
class CalibrationInput:
    """Frozen calibration input for ONE already-authorized candidate.

    Constructing this object presumes authorization already happened upstream.
    It carries no authorization state of its own, by design: there is no field
    in which an access decision could be smuggled into a score.
    """

    candidate_resource_type: str
    candidate_resource_id: str
    lifecycle_status: str
    verification_status: Optional[str] = None
    #: Whether the candidate has explicit valid/effective time. Descriptive.
    has_valid_time: bool = False
    #: Whether the candidate has any transaction/history time. Descriptive.
    has_transaction_time: bool = False
    #: Whether an unresolved conflict is recorded for this candidate. Records
    #: existence only; calibration never resolves it.
    has_conflict: bool = False
    #: Whether the candidate's provenance envelope is complete.
    provenance_complete: bool = False
    #: Relation type when the candidate was reached via an explicitly requested
    #: relation. NOT a centrality, degree, or path-count signal.
    requested_relation_type: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_resource_type",
            validate_resource_type(self.candidate_resource_type),
        )
        if not isinstance(self.candidate_resource_id, str) or not self.candidate_resource_id.strip():
            raise CalibrationContractError("candidate_resource_id", "missing_required_field")
        object.__setattr__(
            self, "lifecycle_status", validate_lifecycle_status(self.lifecycle_status)
        )
        object.__setattr__(
            self, "verification_status", validate_verification_status(self.verification_status)
        )
        for flag in (
            "has_valid_time",
            "has_transaction_time",
            "has_conflict",
            "provenance_complete",
        ):
            if not isinstance(getattr(self, flag), bool):
                raise CalibrationContractError(flag, "not_a_boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "calibration_contract_version": CALIBRATION_CONTRACT_VERSION,
            "candidate_resource_type": self.candidate_resource_type,
            "candidate_resource_id": self.candidate_resource_id,
            "lifecycle_status": self.lifecycle_status,
            "verification_status": self.verification_status,
            "has_valid_time": self.has_valid_time,
            "has_transaction_time": self.has_transaction_time,
            "has_conflict": self.has_conflict,
            "provenance_complete": self.provenance_complete,
            "requested_relation_type": self.requested_relation_type,
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def compute_fingerprint(self) -> str:
        """Deterministic fingerprint: identical inputs fingerprint identically."""
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class CalibrationResult:
    """Frozen calibration output: a bounded score plus its full decomposition.

    The score is ordering metadata. It is never an authorization result, never
    a verification result, and never a truth claim. ``verification_status`` and
    ``lifecycle_status`` are echoed unchanged from the input so a consumer can
    always see that the authoritative state was not altered by scoring.
    """

    candidate_resource_type: str
    candidate_resource_id: str
    score: float
    factor_values: Mapping[str, float] = field(default_factory=dict)
    reason_codes: Tuple[str, ...] = ()
    verification_status: Optional[str] = None
    lifecycle_status: str = "candidate"
    temporal_basis: str = "no_temporal_data"
    conflict_basis: bool = False
    calibration_version: str = CALIBRATION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_resource_type",
            validate_resource_type(self.candidate_resource_type),
        )
        if not isinstance(self.candidate_resource_id, str) or not self.candidate_resource_id.strip():
            raise CalibrationContractError("candidate_resource_id", "missing_required_field")
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise CalibrationContractError("score", "not_a_number")
        if not (SCORE_MIN <= float(self.score) <= SCORE_MAX):
            raise CalibrationContractError("score", "score_out_of_bounds")
        object.__setattr__(self, "score", float(self.score))
        if not isinstance(self.factor_values, Mapping):
            raise CalibrationContractError("factor_values", "not_a_mapping")
        for name, value in self.factor_values.items():
            if name not in ALLOWED_FACTOR_NAMES:
                raise CalibrationContractError("factor_values", f"unknown_factor_{name}")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise CalibrationContractError("factor_values", "factor_not_a_number")
            if not (SCORE_MIN <= float(value) <= SCORE_MAX):
                raise CalibrationContractError("factor_values", "factor_out_of_bounds")
        object.__setattr__(
            self,
            "factor_values",
            {name: float(value) for name, value in sorted(self.factor_values.items())},
        )
        if not isinstance(self.reason_codes, tuple):
            object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        for code in self.reason_codes:
            if code not in ALLOWED_REASON_CODES:
                raise CalibrationContractError("reason_codes", "unknown_reason_code")
        object.__setattr__(
            self, "verification_status", validate_verification_status(self.verification_status)
        )
        object.__setattr__(
            self, "lifecycle_status", validate_lifecycle_status(self.lifecycle_status)
        )
        if self.temporal_basis not in ALLOWED_TEMPORAL_BASIS:
            raise CalibrationContractError("temporal_basis", "unknown_temporal_basis")
        if not isinstance(self.conflict_basis, bool):
            raise CalibrationContractError("conflict_basis", "not_a_boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_resource_type": self.candidate_resource_type,
            "candidate_resource_id": self.candidate_resource_id,
            "score": self.score,
            "factor_values": dict(self.factor_values),
            "reason_codes": list(self.reason_codes),
            "verification_status": self.verification_status,
            "lifecycle_status": self.lifecycle_status,
            "temporal_basis": self.temporal_basis,
            "conflict_basis": self.conflict_basis,
            "calibration_version": self.calibration_version,
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())


def describe_calibration_contract() -> dict[str, Any]:
    """Introspectable description of the frozen contract (no scoring).

    M8.1 freezes structure only. ``scoring_implemented`` is ``False`` and stays
    ``False`` until an approved M8.5 lands explicit factors and weights.
    """
    return {
        "calibration_contract_version": CALIBRATION_CONTRACT_VERSION,
        "scoring_implemented": False,
        "score_min": SCORE_MIN,
        "score_max": SCORE_MAX,
        "allowed_factor_names": sorted(ALLOWED_FACTOR_NAMES),
        "allowed_reason_codes": sorted(ALLOWED_REASON_CODES),
        "allowed_temporal_basis": sorted(ALLOWED_TEMPORAL_BASIS),
        "grants_authorization": False,
        "performs_verification": False,
        "resolves_conflicts": False,
        "overrides_lifecycle": False,
    }


__all__ = [
    "CALIBRATION_CONTRACT_VERSION",
    "SCORE_MIN",
    "SCORE_MAX",
    "ALLOWED_FACTOR_NAMES",
    "ALLOWED_REASON_CODES",
    "ALLOWED_TEMPORAL_BASIS",
    "CalibrationContractError",
    "CalibrationInput",
    "CalibrationResult",
    "describe_calibration_contract",
]
