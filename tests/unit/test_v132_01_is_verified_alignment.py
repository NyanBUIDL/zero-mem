"""V132-01 — is_verified enum alignment contract tests (D-01 Option A).

Contract (RED before fix):
  * An event with verification_status="direct_tool_output" + lifecycle active
    MUST be classified PRIMARY (currently FAILS: eligibility.py:178 compares
    against "verified"/"confirmed", values that belong to no
    VerificationStatus member).
  * verification_status="none" stays SUPPORTING (fail-closed preserved).
  * Full matrix: every VerificationStatus value x active lifecycle, with a
    memory type that is NOT otherwise promoted (so classification depends on
    the verification branch alone).
  * Lifecycle check at the adjacent line ("confirmed" lifecycle) must remain
    intact — that branch keeps its own taxonomy.

Regression triple-log evidence:
  zero-mem-dev-data/evidence/v132/wp1-red.log        (pre-fix, expected FAIL)
  zero-mem-dev-data/evidence/v132/wp1-reverted.log   (fix reverted, FAIL)
  zero-mem-dev-data/evidence/v132/wp1-green.log      (fix applied, PASS)
"""
from __future__ import annotations

from src.capture.event_types import VerificationStatus
from src.integration.m7.eligibility import is_eligible
from src.retrieval.models import EventView


def _event(verification: str, *, event_type: str = "observation",
           lifecycle: str = "active") -> EventView:
    """Minimal M3 event view; memory type deliberately NOT auto-promoted."""
    return EventView(
        event_id="E-V132-1", trace_id="T1", event_type=event_type,
        source="terminal", schema_version=1,
        created_at="2026-08-01T00:00:00Z", observed_at="2026-08-01T00:00:00Z",
        sequence=1, session_id="S", profile_id="PR1", project_id="P",
        task_id=None, turn_id=None, parent_trace_id=None,
        lifecycle_status=lifecycle, verification_status=verification,
        confidence="high", sensitivity="internal", retention="persistent",
        content_hash="h" * 8,
    )


# Values of VerificationStatus that mean "verified by some real mechanism".
_VERIFIED_VALUES = tuple(
    v.value for v in VerificationStatus if v.value != "none"
)


class TestV132Wp1IsVerifiedAlignment:
    def test_direct_tool_output_active_is_primary(self):
        res = is_eligible(_event("direct_tool_output"), "project_memory")
        assert res.eligible
        assert res.as_primary

    def test_none_stays_supporting(self):
        res = is_eligible(_event("none"), "project_memory")
        assert res.eligible
        assert not res.as_primary

    def test_matrix_every_verified_enum_value_promotes_active(self):
        for value in _VERIFIED_VALUES:
            res = is_eligible(_event(value), "project_memory")
            assert res.eligible, value
            assert res.as_primary, f"{value} must classify primary"

    def test_matrix_none_never_primary(self):
        res = is_eligible(_event("none"), "project_memory")
        assert not res.as_primary

    def test_legacy_lifecycle_confirmed_still_primary(self):
        # The adjacent lifecycle check ("confirmed" is a LifecycleStatus) must
        # keep working even when verification is none.
        res = is_eligible(
            _event("none", lifecycle="confirmed"), "project_memory"
        )
        assert res.eligible
        assert res.as_primary

    def test_superseded_not_promoted_by_verification(self):
        res = is_eligible(
            _event("deterministic_verification", lifecycle="superseded"),
            "project_memory",
        )
        if res.eligible:
            assert not res.as_primary
