"""M8.5 — retrieval-metadata integration tests (internal adapter).

These tests exercise :mod:`src.m8.retrieval_metadata` and assert the
authorization-first boundary end to end WITHOUT importing the M5 facade: the
integration layer is duck-typed on an ``AuthorizedResult`` and consumes the
upstream decision verbatim. A denied/errored result yields empty, unauthorized
metadata that leaks no existence, count, score, or ordering.

The zero-influence rule and the EXCLUSION-before-calibration behaviour are
asserted here at the integration boundary, confirming that calibration is
structurally incapable of leaking a hidden or unauthorized candidate into a
visible result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence, Tuple

import pytest

from src.m8.calibration import CalibrationCandidate, CalibrationError
from src.m8.retrieval_metadata import (
    RetrievalMetadataRequest,
    RetrievalMetadataResult,
    calibrate_authorized_items,
    calibrate_authorized_result,
    classify_candidate_provenance,
    classify_scope,
    classify_temporal_validity,
    describe_retrieval_metadata,
)
from src.m8.calibration import (
    PROVENANCE_COMPLETE,
    PROVENANCE_INCOMPLETE,
    PROVENANCE_REQUIRED_ONLY,
    SCOPE_COMPOSED,
    SCOPE_EXACT,
    SCOPE_GLOBAL_FALLBACK,
    SCOPE_UNAUTHORIZED,
    TEMPORAL_UNKNOWN,
    TEMPORAL_VALID,
)


@dataclass
class FakeItem:
    """Minimal duck-typed retrieval item (mimics M3/M4 result shapes)."""
    event_id: Optional[str] = None
    event_type: Optional[str] = None
    lifecycle_status: Optional[str] = None
    verification_status: Optional[str] = None
    profile_id: Optional[str] = None
    project_id: Optional[str] = None
    knowledge_space_id: Optional[str] = None
    created_at: Optional[str] = None
    effective_at: Optional[str] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    source_event_id: Optional[str] = None
    trace_id: Optional[str] = None
    has_conflict: bool = False
    retrieval_relevance: Optional[float] = None


@dataclass
class FakeAuthorizedResult:
    """Duck-typed M5 result surface consumed by the integration layer."""
    items: Sequence[FakeItem]
    allowed: bool = True
    denied: bool = False
    error: Optional[Exception] = None


def _req(**kw) -> RetrievalMetadataRequest:
    base = dict(
        requesting_profile_id="PR1", project_id="P1",
        knowledge_space_id=None, authorized_profile_ids=("PR1",),
        authorized_project_ids=("P1",), authorized_knowledge_space_ids=(),
        global_read_allowed=False, as_of=None, relation_distances={},
    )
    base.update(kw)
    return RetrievalMetadataRequest(**base)


# ---------------------------------------------------------------------------
# Scope classification (docs/plans/plan-m8.md §22.1.3)
# ---------------------------------------------------------------------------


class TestScopeClassification:
    def test_exact_requested_scope(self):
        item = FakeItem(event_id="E1", event_type="verified_state",
                        profile_id="PR1", project_id="P1")
        assert classify_scope(item, _req()) == SCOPE_EXACT

    def test_unscoped_exact_when_caller_defines_none(self):
        item = FakeItem(event_id="E1", event_type="verified_state")
        req = _req(requesting_profile_id=None, project_id=None,
                   knowledge_space_id=None)
        assert classify_scope(item, req) == SCOPE_EXACT

    def test_composed_cross_space_when_authorized(self):
        item = FakeItem(event_id="E1", event_type="verified_state",
                        profile_id="PR1", project_id="P2")
        req = _req(authorized_project_ids=("P1", "P2"))
        # P2 is in the explicitly authorized project set but differs from the
        # requested project P1, so it is an authorized COMPOSED scope (0.9),
        # never the exact-requested scope.
        assert classify_scope(item, req) == SCOPE_COMPOSED

    def test_unauthorized_when_outside_grant(self):
        item = FakeItem(event_id="E1", event_type="verified_state",
                        profile_id="PR1", project_id="PX")
        req = _req(authorized_project_ids=("P1",))
        assert classify_scope(item, req) == SCOPE_UNAUTHORIZED

    def test_global_fallback_when_no_scope_and_granted(self):
        item = FakeItem(event_id="E1", event_type="verified_state")
        req = _req(global_read_allowed=True)
        assert classify_scope(item, req) == SCOPE_GLOBAL_FALLBACK


# ---------------------------------------------------------------------------
# Provenance + temporal classification
# ---------------------------------------------------------------------------


class TestProvenanceTemporalClassification:
    def test_complete_when_all_present(self):
        item = FakeItem(event_id="E1", created_at="2026-01-01T00:00:00Z",
                        source_event_id="S1", trace_id="T1")
        assert classify_candidate_provenance(item) == PROVENANCE_COMPLETE

    def test_required_only_when_optional_absent(self):
        item = FakeItem(event_id="E1", created_at="2026-01-01T00:00:00Z",
                        source_event_id="S1")
        assert classify_candidate_provenance(item) == PROVENANCE_REQUIRED_ONLY

    def test_incomplete_when_required_missing(self):
        item = FakeItem(created_at="2026-01-01T00:00:00Z",
                        source_event_id="S1")
        assert classify_candidate_provenance(item) == PROVENANCE_INCOMPLETE

    def test_temporal_unknown_without_signal(self):
        item = FakeItem(event_id="E1")
        assert classify_temporal_validity(item, _req()) == TEMPORAL_UNKNOWN

    def test_temporal_valid_with_signal_no_reference(self):
        item = FakeItem(event_id="E1", effective_at="2026-01-01T00:00:00Z")
        assert classify_temporal_validity(item, _req()) == TEMPORAL_VALID

    def test_temporal_valid_with_signal_and_reference_in_window(self):
        # An explicit valid envelope (valid_from..valid_until) covering the
        # as_of reference is explicitly valid -> 1.0.
        item = FakeItem(event_id="E1", valid_from="2025-01-01T00:00:00Z",
                        valid_until="2027-01-01T00:00:00Z")
        assert classify_temporal_validity(item, _req(as_of="2026-06-01T00:00:00Z")) \
            == TEMPORAL_VALID

    def test_temporal_invalid_outside_window(self):
        item = FakeItem(event_id="E1", effective_at="2025-01-01T00:00:00Z",
                        valid_until="2025-12-01T00:00:00Z")
        assert classify_temporal_validity(item, _req(as_of="2026-06-01T00:00:00Z")) \
            == "invalid"


# ---------------------------------------------------------------------------
# Authorization-first integration
# ---------------------------------------------------------------------------


class TestAuthorizationFirst:
    def _visible_items(self):
        return [
            FakeItem(event_id="A", event_type="verified_state",
                     profile_id="PR1", project_id="P1",
                     created_at="2026-01-01T00:00:00Z",
                     source_event_id="S1", trace_id="T1"),
            FakeItem(event_id="B", event_type="user_statement",
                     profile_id="PR1", project_id="P1",
                     created_at="2026-01-01T00:00:00Z",
                     source_event_id="S2", trace_id="T2"),
        ]

    def test_authorized_items_calibrate(self):
        items = self._visible_items()
        res = calibrate_authorized_items(items, "event", _req())
        assert res.authorized is True
        assert len(res.ordered) == 2
        # verified_state (1.0) must outrank user_statement (0.8).
        assert res.ordered[0].candidate_resource_id == "A"

    def test_denied_result_yields_unauthorized_empty(self):
        denied = FakeAuthorizedResult(items=self._visible_items(),
                                      allowed=False, denied=True)
        res = calibrate_authorized_result(denied, "event", _req())
        assert res.authorized is False
        assert res.ordered == ()
        assert res.decisions == ()

    def test_errored_result_yields_unauthorized_empty(self):
        errored = FakeAuthorizedResult(
            items=self._visible_items(), error=RuntimeError("denied"))
        res = calibrate_authorized_result(errored, "event", _req())
        assert res.authorized is False
        assert res.ordered == ()

    def test_no_authorization_decision_made(self):
        # The module consumes the upstream decision; it never computes one.
        d = describe_retrieval_metadata()
        assert d["makes_authorization_decisions"] is False
        assert d["consumes_m5_decision"] is True
        assert d["performs_io"] is False

    def test_revocation_honoured_no_cache(self):
        # Calling with a denied result after a prior allowed call must not
        # leak the earlier allowed output — there is no cached state.
        allowed = FakeAuthorizedResult(items=self._visible_items())
        first = calibrate_authorized_result(allowed, "event", _req())
        assert first.authorized is True
        denied = FakeAuthorizedResult(items=[], allowed=False, denied=True)
        second = calibrate_authorized_result(denied, "event", _req())
        assert second.authorized is False
        assert second.ordered == ()


# ---------------------------------------------------------------------------
# Zero-influence rule (docs/plans/plan-m8.md §22.1.9)
# ---------------------------------------------------------------------------


class TestZeroInfluence:
    def _authorized_item(self, rid):
        return FakeItem(
            event_id=rid, event_type="verified_state",
            profile_id="PR1", project_id="P1",
            created_at="2026-01-01T00:00:00Z",
            source_event_id="S1", trace_id="T1",
            retrieval_relevance=0.9,
        )

    def test_hidden_unauthorized_cannot_touch_visible_scores(self):
        visible = [self._authorized_item("A"), self._authorized_item("B")]
        # Hidden item lives OUTSIDE the authorized set -> it never enters the
        # scoring domain. Calibrate the visible set alone and confirm scores.
        alone = calibrate_authorized_items(visible, "event", _req())
        # A hidden item would only be representable as an out-of-scope input
        # that is EXCLUDED; its presence therefore cannot move A or B.
        hidden = FakeItem(event_id="H", event_type="verified_state",
                          profile_id="PR1", project_id="PX")
        with_hidden = visible + [hidden]
        combined = calibrate_authorized_items(with_hidden, "event", _req())
        a_alone = {r.candidate_resource_id: r.score for r in alone.ordered}
        a_combined = {r.candidate_resource_id: r.score for r in combined.ordered}
        assert a_alone == a_combined
        # The hidden item was excluded, not scored and retained.
        excluded = [d for d in combined.decisions if not d.included]
        assert len(excluded) == 1 and excluded[0].resource_id == "H"

    def test_visible_order_identical_with_or_without_hidden(self):
        visible = [self._authorized_item("A"), self._authorized_item("B")]
        alone_order = [r.candidate_resource_id
                       for r in calibrate_authorized_items(visible, "event", _req()).ordered]
        hidden = FakeItem(event_id="H", event_type="verified_state",
                          profile_id="PR1", project_id="PX")
        comb_order = [r.candidate_resource_id for r in
                      calibrate_authorized_items(visible + [hidden], "event", _req()).ordered]
        assert alone_order == comb_order

    def test_explanation_carries_no_hidden_marker(self):
        # Reason codes are drawn only from the M8.1 closed vocabulary over this
        # candidate; no hidden-existence code can appear.
        res = calibrate_authorized_items([self._authorized_item("A")], "event", _req())
        for r in res.ordered:
            assert set(r.reason_codes) <= {
                "VERIFIED_SOURCE", "UNVERIFIED_SOURCE",
                "ASSISTANT_CLAIM_NOT_PROMOTED",
                "EXPLICIT_PROVENANCE_COMPLETE",
                "TEMPORAL_VALID_TIME_PRESENT", "TEMPORAL_VALID_TIME_ABSENT",
                "LIFECYCLE_ELIGIBLE", "CONFLICT_PRESENT",
            }


# ---------------------------------------------------------------------------
# Read-only / no persistence / no M5 surface
# ---------------------------------------------------------------------------


class TestReadOnlyNoPersistence:
    def test_calibrate_authorized_items_is_pure(self):
        items = [FakeItem(event_id="A", event_type="verified_state",
                          created_at="2026-01-01T00:00:00Z",
                          source_event_id="S1", trace_id="T1")]
        req = _req()
        before = [vars(i).copy() for i in items]
        calibrate_authorized_items(items, "event", req)
        after = [vars(i).copy() for i in items]
        assert before == after  # input objects untouched

    def test_no_persistence_rows(self):
        import inspect
        from src.m8 import retrieval_metadata as mod
        for name, obj in vars(mod).items():
            if inspect.isfunction(obj):
                src = inspect.getsource(obj)
                assert "INSERT" not in src, name
                assert "sqlite3" not in src, name
                assert "zm_calibration" not in src, name

    def test_schema_version_nine(self):
        assert describe_retrieval_metadata()["schema_version"] == 12

    def test_request_is_frozen_and_validated(self):
        with pytest.raises(CalibrationError):
            RetrievalMetadataRequest(authorized_profile_ids="PR1")  # not a seq


# ---------------------------------------------------------------------------
# Tie-break stable at integration boundary
# ---------------------------------------------------------------------------


class TestIntegrationTieBreak:
    def test_equal_score_orders_by_identity_regardless_of_input_order(self):
        a = FakeItem(event_id="A", event_type="verified_state",
                     created_at="2026-01-01T00:00:00Z",
                     source_event_id="S", trace_id="T",
                     profile_id="PR1", project_id="P1")
        b = FakeItem(event_id="B", event_type="verified_state",
                     created_at="2026-01-01T00:00:00Z",
                     source_event_id="S", trace_id="T",
                     profile_id="PR1", project_id="P1")
        forward = calibrate_authorized_items([a, b], "event", _req())
        reverse = calibrate_authorized_items([b, a], "event", _req())
        fwd_ids = [r.candidate_resource_id for r in forward.ordered]
        rev_ids = [r.candidate_resource_id for r in reverse.ordered]
        assert fwd_ids == rev_ids == ["A", "B"]
