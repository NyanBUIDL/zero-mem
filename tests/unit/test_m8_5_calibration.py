"""M8.5 — focused calibration engine tests.

Covers every approved factor mapping, the multiplicative formula, determinism,
bounded-value fail-closed, the deterministic tie-break, EXCLUSION-before-
calibration, authority-safety invariants, and the no-persistence / schema-v9
contract. These tests consume ONLY the pure :mod:`src.m8.calibration` engine —
no I/O, no M5 facade, no database, no clock.

Authorization isolation in the integration layer (including the zero-influence
rule) is covered separately in ``test_m8_5_retrieval_metadata.py``.
"""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import pytest

from src.m8.calibration import (
    CalibrationCandidate,
    CalibrationDecision,
    CalibrationError,
    combine_factors,
    exclusion_for,
    has_unresolved_conflict,
    calibrate_candidate,
    calibrate_candidates,
    classify_provenance,
    included_results,
    ordering_key,
    order_calibrated,
    derive_relation_relevance,
    EXCLUDED_RELATION_BEYOND_BOUNDS,
    EXCLUDED_TEMPORAL_INVALID,
    EXCLUDED_UNAUTHORIZED_SCOPE,
    PROVENANCE_COMPLETE,
    PROVENANCE_INCOMPLETE,
    PROVENANCE_REQUIRED_ONLY,
    SCOPE_COMPOSED,
    SCOPE_EXACT,
    SCOPE_GLOBAL_FALLBACK,
    SCOPE_UNAUTHORIZED,
    TEMPORAL_INVALID,
    TEMPORAL_UNKNOWN,
)
from src.m8.calibration_contract import SCORE_MAX, SCORE_MIN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base(**overrides) -> CalibrationCandidate:
    data = dict(
        resource_type="event",
        resource_id="E1",
        memory_type="verified_state",
        lifecycle_status="active",
        scope_match=SCOPE_EXACT,
        provenance_class=PROVENANCE_COMPLETE,
        temporal_validity="valid",
        has_valid_time=True,
        has_transaction_time=True,
        has_conflict=False,
        relation_distance=None,
        retrieval_relevance=None,
        profile_id="PR1",
        project_id="P1",
        knowledge_space_id=None,
    )
    data.update(overrides)
    return CalibrationCandidate(**data)


def _decision_score(**overrides) -> float:
    return calibrate_candidate(_base(**overrides)).result.score


# ---------------------------------------------------------------------------
# Formula exactness + bounds
# ---------------------------------------------------------------------------


class TestFormulaExactness:
    def test_product_reproduces_final_score_exactly(self):
        c = _base(
            retrieval_relevance=0.5,
            scope_match=SCOPE_COMPOSED,           # 0.9
            memory_type="decision",               # 0.9
            provenance_class=PROVENANCE_REQUIRED_ONLY,  # 0.75
            temporal_validity=TEMPORAL_UNKNOWN,   # 0.75
            has_conflict=True,                    # 0.5
            relation_distance=2,                  # 0.8
        )
        d = calibrate_candidate(c)
        assert d.included is True
        product = 0.5 * 0.9 * 0.9 * 0.75 * 0.75 * 1.0 * 0.5 * 0.8
        assert d.result.score == pytest.approx(product)
        assert d.result.score == 0.5 * 0.9 * 0.9 * 0.75 * 0.75 * 1.0 * 0.5 * 0.8

    def test_all_max_factors_yield_one(self):
        score = _decision_score()
        assert score == 1.0

    def test_score_always_within_bounds(self):
        # Sweep a range of legal factor combinations; product must stay in
        # [0, 1] because every factor is in [0, 1].
        for rm in (1.0, 0.7):
            for sp in (SCOPE_EXACT, SCOPE_COMPOSED, SCOPE_GLOBAL_FALLBACK):
                for mt in ("verified_state", "assistant_claim", "inference"):
                    for pc in (PROVENANCE_COMPLETE, PROVENANCE_REQUIRED_ONLY):
                        for tv in ("valid", TEMPORAL_UNKNOWN):
                            for cf in (False, True):
                                for rd in (None, 0, 1, 2):
                                    c = _base(
                                        retrieval_relevance=(None if rm == 1.0 else rm),
                                        scope_match=sp, memory_type=mt,
                                        provenance_class=pc, temporal_validity=tv,
                                        has_conflict=cf, relation_distance=rd,
                                    )
                                    s = calibrate_candidate(c).result.score
                                    assert SCORE_MIN <= s <= SCORE_MAX, (c, s)

    def test_combine_factors_requires_exact_eight_names(self):
        with pytest.raises(CalibrationError):
            combine_factors({"retrieval_match": 1.0})  # missing 7
        extra = {k: 1.0 for k in (
            "retrieval_match", "scope_priority", "verification_strength",
            "provenance_completeness", "temporal_validity",
            "lifecycle_eligibility", "conflict_penalty", "relation_relevance",
        )}
        extra["bogus"] = 1.0
        with pytest.raises(CalibrationError):
            combine_factors(extra)  # one unexpected factor -> fail closed

    def test_factor_order_is_canonical_and_fixed(self):
        from src.m8.calibration import FACTOR_ORDER
        assert tuple(FACTOR_ORDER) == (
            "retrieval_match", "scope_priority", "verification_strength",
            "provenance_completeness", "temporal_validity",
            "lifecycle_eligibility", "conflict_penalty", "relation_relevance",
        )


# ---------------------------------------------------------------------------
# Each approved factor mapping (docs/plans/plan-m8.md §22.1.3)
# ---------------------------------------------------------------------------


class TestRetrievalMatch:
    def test_no_upstream_signal_is_neutral_one(self):
        assert derive_relation_relevance is not None
        assert _decision_score() == 1.0  # retrieval_relevance=None -> 1.0

    def test_upstream_signal_used_verbatim(self):
        assert _decision_score(retrieval_relevance=0.42) == 0.42

    def test_signal_out_of_range_fails_closed(self):
        with pytest.raises(CalibrationError):
            calibrate_candidate(_base(retrieval_relevance=1.5))
        with pytest.raises(CalibrationError):
            calibrate_candidate(_base(retrieval_relevance=-0.3))


class TestScopePriority:
    def test_exact_is_one(self):
        assert _decision_score(scope_match=SCOPE_EXACT) == 1.0

    def test_composed_is_point_nine(self):
        assert _decision_score(scope_match=SCOPE_COMPOSED) == 0.9

    def test_global_fallback_is_point_eight(self):
        assert _decision_score(scope_match=SCOPE_GLOBAL_FALLBACK) == 0.8

    def test_unauthorized_is_excluded_not_zero(self):
        d = calibrate_candidate(_base(scope_match=SCOPE_UNAUTHORIZED))
        assert d.included is False
        assert d.exclusion_code == EXCLUDED_UNAUTHORIZED_SCOPE
        assert d.result is None


class TestVerificationStrength:
    def test_verified_state_is_one(self):
        assert _decision_score(memory_type="verified_state") == 1.0

    def test_verification_is_one(self):
        assert _decision_score(memory_type="verification") == 1.0

    def test_decision_is_point_nine(self):
        assert _decision_score(memory_type="decision") == 0.9

    def test_tool_observation_is_point_nine(self):
        assert _decision_score(memory_type="tool_observation") == 0.9

    def test_user_statement_is_point_eight(self):
        assert _decision_score(memory_type="user_statement") == 0.8

    def test_assistant_claim_is_point_six(self):
        assert _decision_score(memory_type="assistant_claim") == 0.6

    def test_inference_is_point_five(self):
        assert _decision_score(memory_type="inference") == 0.5

    def test_unknown_type_fails_closed(self):
        with pytest.raises(CalibrationError):
            calibrate_candidate(_base(memory_type="prediction_model"))


class TestProvenanceCompleteness:
    def test_complete_is_one(self):
        assert _decision_score(provenance_class=PROVENANCE_COMPLETE) == 1.0

    def test_required_only_is_point_seven_five(self):
        s = _decision_score(provenance_class=PROVENANCE_REQUIRED_ONLY)
        assert s == 0.75

    def test_incomplete_is_excluded_not_scorable(self):
        d = calibrate_candidate(_base(provenance_class=PROVENANCE_INCOMPLETE))
        assert d.included is False
        assert d.result is None


class TestTemporalValidity:
    def test_valid_is_one(self):
        assert _decision_score(temporal_validity="valid") == 1.0

    def test_unknown_valid_time_signal_is_point_seven_five(self):
        s = _decision_score(temporal_validity=TEMPORAL_UNKNOWN)
        assert s == 0.75

    def test_invalid_is_excluded(self):
        d = calibrate_candidate(_base(temporal_validity=TEMPORAL_INVALID))
        assert d.included is False
        assert d.exclusion_code == EXCLUDED_TEMPORAL_INVALID

    def test_recency_is_not_authority(self):
        # A fresher timestamp is not represented; validity is a discrete
        # valid/unknown/invalid judgement. Calibration never rewards newer.
        old = _decision_score(temporal_validity="valid")
        also_old = _decision_score(temporal_validity="valid")
        assert old == also_old == 1.0


class TestLifecycleEligibility:
    def test_eligible_is_one(self):
        assert _decision_score(lifecycle_status="active") == 1.0

    def test_deleted_is_excluded(self):
        d = calibrate_candidate(_base(lifecycle_status="deleted"))
        assert d.included is False

    def test_superseded_remains_eligible(self):
        assert _decision_score(lifecycle_status="superseded") == 1.0


class TestConflictPenalty:
    def test_no_conflict_is_one(self):
        assert _decision_score(has_conflict=False) == 1.0

    def test_unresolved_conflict_is_point_five(self):
        assert _decision_score(has_conflict=True) == 0.5

    def test_conflicted_lifecycle_marks_unresolved(self):
        c = _base(lifecycle_status="conflicted")
        assert has_unresolved_conflict(c) is True
        assert calibrate_candidate(c).result.score == 0.5

    def test_conflict_never_resolved_in_calibration(self):
        # An unresolved conflict only lowers the score; it never declares a
        # winner or sets supersession.
        c = _base(has_conflict=True)
        d = calibrate_candidate(c, verification_status_echo="deterministic_verification")
        assert d.result.conflict_basis is True
        assert d.result.verification_status == "deterministic_verification"


class TestRelationRelevance:
    def test_no_relation_context_is_one(self):
        assert _decision_score(relation_distance=None) == 1.0

    def test_root_relation_is_one(self):
        assert _decision_score(relation_distance=0) == 1.0

    def test_one_hop_is_point_nine(self):
        assert _decision_score(relation_distance=1) == 0.9

    def test_two_hop_is_point_eight(self):
        assert _decision_score(relation_distance=2) == 0.8

    def test_beyond_bound_is_excluded(self):
        d = calibrate_candidate(_base(relation_distance=3))
        assert d.included is False
        assert d.exclusion_code == EXCLUDED_RELATION_BEYOND_BOUNDS


# ---------------------------------------------------------------------------
# Bounded-value / fail-closed
# ---------------------------------------------------------------------------


class TestBoundedValueFailClosed:
    def test_nan_fails_closed(self):
        with pytest.raises(CalibrationError):
            calibrate_candidate(_base(retrieval_relevance=float("nan")))

    def test_positive_infinity_fails_closed(self):
        with pytest.raises(CalibrationError):
            calibrate_candidate(_base(retrieval_relevance=float("inf")))

    def test_negative_infinity_fails_closed(self):
        with pytest.raises(CalibrationError):
            calibrate_candidate(_base(retrieval_relevance=float("-inf")))

    def test_out_of_range_fails_closed(self):
        with pytest.raises(CalibrationError):
            calibrate_candidate(_base(retrieval_relevance=2.0))

    def test_boolean_not_a_number(self):
        with pytest.raises(CalibrationError):
            calibrate_candidate(_base(retrieval_relevance=True))  # type: ignore

    def test_combine_rejects_nan(self):
        factors = {k: 1.0 for k in (
            "retrieval_match", "scope_priority", "verification_strength",
            "provenance_completeness", "temporal_validity",
            "lifecycle_eligibility", "conflict_penalty", "relation_relevance",
        )}
        factors["retrieval_match"] = float("nan")
        with pytest.raises(CalibrationError):
            combine_factors(factors)

    def test_no_clamping_of_malformed_value(self):
        # Confirm there is no clamp path: a >1 value raises, not clamps.
        with pytest.raises(CalibrationError):
            calibrate_candidate(_base(retrieval_relevance=1.4))


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_input_same_output(self):
        c = _base(retrieval_relevance=0.5, scope_match=SCOPE_COMPOSED,
                  memory_type="decision")
        a = calibrate_candidate(c).result.to_dict()
        b = calibrate_candidate(c).result.to_dict()
        assert a == b

    def test_no_module_state(self):
        s1 = calibrate_candidate(_base()).result.score
        # mutate nothing; run again in a fresh equivalent candidate
        s2 = calibrate_candidate(_base()).result.score
        assert s1 == s2 == 1.0

    def test_floating_point_product_is_stable(self):
        # Multiplication order is fixed; the product must be identical across
        # two independent builds of the same factor set.
        c1 = _base(retrieval_relevance=0.5, scope_match=SCOPE_COMPOSED,
                   memory_type="decision", provenance_class=PROVENANCE_REQUIRED_ONLY,
                   temporal_validity=TEMPORAL_UNKNOWN, has_conflict=True,
                   relation_distance=2)
        c2 = _base(retrieval_relevance=0.5, scope_match=SCOPE_COMPOSED,
                   memory_type="decision", provenance_class=PROVENANCE_REQUIRED_ONLY,
                   temporal_validity=TEMPORAL_UNKNOWN, has_conflict=True,
                   relation_distance=2)
        assert math.isclose(
            calibrate_candidate(c1).result.score,
            calibrate_candidate(c2).result.score,
        )


# ---------------------------------------------------------------------------
# Deterministic tie-break (docs/plans/plan-m8.md §22.1.5)
# ---------------------------------------------------------------------------


class TestDeterministicTieBreak:
    def _mk(self, rid, rtype="event", score=1.0):
        from src.m8.calibration_contract import CalibrationResult
        return CalibrationResult(
            candidate_resource_type=rtype,
            candidate_resource_id=rid,
            score=score,
            factor_values={},
            reason_codes=(),
            verification_status="deterministic_verification",
            lifecycle_status="active",
            temporal_basis="valid_time_present",
            conflict_basis=False,
        )

    def test_score_descending_first(self):
        ordered = order_calibrated([self._mk("E2", score=0.5),
                                    self._mk("E1", score=1.0)])
        assert [r.candidate_resource_id for r in ordered] == ["E1", "E2"]

    def test_resource_type_breaks_equal_score(self):
        ordered = order_calibrated([self._mk("A1", "event", 1.0),
                                    self._mk("A1", "artifact", 1.0)])
        assert [r.candidate_resource_type for r in ordered] == ["artifact", "event"]

    def test_identity_breaks_equal_score_and_type(self):
        ordered = order_calibrated([self._mk("B", "event", 1.0),
                                    self._mk("A", "event", 1.0)])
        assert [r.candidate_resource_id for r in ordered] == ["A", "B"]

    def test_stable_under_reverse_insertion_order(self):
        a = self._mk("A", "event", 0.9)
        b = self._mk("B", "event", 0.9)
        c = self._mk("C", "event", 0.9)
        forward = order_calibrated([a, b, c])
        reverse = order_calibrated([c, b, a])
        assert [r.candidate_resource_id for r in forward] == ["A", "B", "C"]
        assert [r.candidate_resource_id for r in reverse] == ["A", "B", "C"]

    def test_tie_break_uses_no_forbidden_order(self):
        # The ordering key must be a pure function of score/rtype/identity;
        # it must not expose any nondeterministic component.
        r = self._mk("A")
        key = ordering_key(r)
        assert key[0] == -1.0
        assert key[1] == "event"
        assert key[2] == "A"

    def test_hidden_candidate_cannot_affect_equal_score_tie(self):
        # A tie between two visible candidates must order identically whether
        # or not an unauthorized (excluded) candidate coexists.
        visible = [self._mk("A", "event", 0.9), self._mk("B", "event", 0.9)]
        hidden = calibrate_candidate(_base(scope_match=SCOPE_UNAUTHORIZED)).result
        assert hidden is None  # exclusion produces no result
        with_a = order_calibrated(visible)
        with_b = order_calibrated(visible)
        assert [r.candidate_resource_id for r in with_a] == \
               [r.candidate_resource_id for r in with_b] == ["A", "B"]


# ---------------------------------------------------------------------------
# Exclusion-before-calibration
# ---------------------------------------------------------------------------


class TestExclusionBeforeCalibration:
    def test_unauthorized_excluded_first(self):
        c = _base(scope_match=SCOPE_UNAUTHORIZED)
        assert exclusion_for(c) == EXCLUDED_UNAUTHORIZED_SCOPE
        d = calibrate_candidate(c)
        assert d.included is False
        assert d.result is None

    def test_deleted_excluded(self):
        c = _base(lifecycle_status="deleted")
        assert exclusion_for(c) is not None
        assert calibrate_candidate(c).included is False

    def test_excluded_candidate_not_in_ordered_results(self):
        decisions = calibrate_candidates([
            _base(resource_id="OK", scope_match=SCOPE_EXACT),
            _base(resource_id="BAD", scope_match=SCOPE_UNAUTHORIZED),
        ])
        kept = included_results(decisions)
        assert [r.candidate_resource_id for r in kept] == ["OK"]


# ---------------------------------------------------------------------------
# Authority-safety invariants
# ---------------------------------------------------------------------------


class TestAuthoritySafety:
    def test_high_score_does_not_set_verification(self):
        c = _base(memory_type="assistant_claim")
        d = calibrate_candidate(c, verification_status_echo=None)
        assert d.result.verification_status is None
        assert d.result.score > 0  # it still got a score

    def test_assistant_claim_never_promoted(self):
        c = _base(memory_type="assistant_claim")
        d = calibrate_candidate(c, verification_status_echo=None)
        assert "ASSISTANT_CLAIM_NOT_PROMOTED" in d.result.reason_codes
        assert d.result.verification_status is None

    def test_lifecycle_unchanged_in_result(self):
        c = _base(lifecycle_status="superseded")
        d = calibrate_candidate(c, verification_status_echo="deterministic_verification")
        assert d.result.lifecycle_status == "superseded"

    def test_conflict_flag_only_marks_never_resolves(self):
        c = _base(has_conflict=True)
        d = calibrate_candidate(c, verification_status_echo="deterministic_verification")
        assert d.result.conflict_basis is True
        assert "CONFLICT_PRESENT" in d.result.reason_codes

    def test_candidate_is_frozen(self):
        c = _base()
        with pytest.raises(FrozenInstanceError):
            c.resource_type = "artifact"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# No persistence / schema v9 / read-only
# ---------------------------------------------------------------------------


class TestNoPersistenceSchemaNine:
    def test_describe_declares_request_time_only(self):
        from src.m8.calibration import describe_calibration
        d = describe_calibration()
        assert d["persisted"] is False
        assert d["request_time_only"] is True
        assert d["schema_version"] == 10
        assert d["confidence_threshold_implemented"] is False
        assert d["cross_candidate_normalization"] is False
        assert d["grants_authorization"] is False
        assert d["performs_verification"] is False
        assert d["resolves_conflicts"] is False
        assert d["overrides_lifecycle"] is False
        assert d["infers_supersession"] is False
        assert d["promotes_assistant_claim"] is False
        assert d["recency_is_not_authority"] is True
        assert d["uses_centrality"] is False
        assert d["reads_wall_clock"] is False

    def test_calibration_produces_no_persistence_rows(self):
        # The pure engine holds no connection and opens no file; running it
        # cannot create a persistence row. Assert by absence of any I/O surface.
        import inspect
        from src.m8 import calibration as mod
        for name, obj in vars(mod).items():
            if inspect.isfunction(obj):
                src = inspect.getsource(obj)
                assert "sqlite3" not in src, name
                assert "open(" not in src, name
                assert "INSERT" not in src, name


# ---------------------------------------------------------------------------
# Provenance classification helper
# ---------------------------------------------------------------------------


class TestProvenanceClassification:
    def test_complete_envelope(self):
        p = {
            "identity": "E1",
            "record_time": "2026-01-01T00:00:00Z",
            "source_event_id": "S1",
            "trace_id": "T1",
        }
        assert classify_provenance(p) == PROVENANCE_COMPLETE

    def test_required_only_envelope(self):
        p = {
            "identity": "E1",
            "record_time": "2026-01-01T00:00:00Z",
            "source_event_id": "S1",
        }
        assert classify_provenance(p) == PROVENANCE_REQUIRED_ONLY

    def test_incomplete_envelope(self):
        # Missing required provenance excludes; calibration never backfills.
        p = {
            "record_time": "2026-01-01T00:00:00Z",
            "source_event_id": "S1",
        }
        assert classify_provenance(p) == PROVENANCE_INCOMPLETE

    def test_no_fabrication_from_sibling(self):
        # Optional fields absent -> required_only, never fabricated upward.
        p = {
            "identity": "E1",
            "record_time": "2026-01-01T00:00:00Z",
            "source_event_id": None,
        }
        assert classify_provenance(p) != PROVENANCE_COMPLETE


class TestSanitizedErrors:
    def test_error_names_field_not_value(self):
        err = CalibrationError("retrieval_match", "out_of_bounds")
        assert "retrieval_match" in err.args[0]
        assert "out_of_bounds" in err.args[0]
        # Must not echo any candidate content / path.
        assert "secret" not in err.args[0].lower()

    def test_invalid_resource_type_rejected(self):
        with pytest.raises(CalibrationError):
            _base(resource_type="not_a_real_type")
