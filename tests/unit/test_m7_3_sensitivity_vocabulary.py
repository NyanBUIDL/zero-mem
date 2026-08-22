"""M7.3 corrective regression — canonical sensitivity vocabulary.

Guards a defect found after M7.3/M8.6 were marked VERIFIED: the eligibility
sensitivity gate ranked an invented vocabulary (low/medium/high/critical) while
canonical events persist public/internal/private/secret. Every real event fell
into the unknown => fail-closed branch, so NO M3 event could ever become
evidence, and the original ceiling test passed vacuously (it asserted only that
an event was absent, which was true for all events).

These tests are deliberately POSITIVE as well as negative: they prove allowed
canonical events ARE included, so this class of vacuous-green cannot recur.

A second defect is also covered: a malformed ceiling previously compared
99 > 99 == False and admitted EVERYTHING including `secret` (fail-open).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.capture.event_types import Sensitivity
from src.integration.m7.eligibility import (
    DEFAULT_SENSITIVITY_CEILING,
    _SENSITIVITY_ORDER,
    is_eligible,
)
from src.retrieval.models import EventView

CANONICAL_VALUES = ("public", "internal", "private", "secret")


def _event(sensitivity, *, event_id="E1", lifecycle="active",
           event_type="verified_state") -> EventView:
    """A fully-provenanced, authorized-shape M3 event view."""
    return EventView(
        event_id=event_id, trace_id="T1", event_type=event_type, source="terminal",
        schema_version=1, created_at="2026-08-01T00:00:00Z",
        observed_at="2026-08-01T00:00:00Z", sequence=1, session_id="S",
        profile_id="PR1", project_id="P", task_id=None, turn_id=None,
        parent_trace_id=None, lifecycle_status=lifecycle,
        verification_status="direct_tool_output", confidence="high",
        sensitivity=sensitivity, retention="persistent", content_hash="h" * 8,
    )


# ---------------------------------------------------------------------------
# vocabulary alignment
# ---------------------------------------------------------------------------
class TestCanonicalVocabulary:
    def test_order_uses_exactly_the_canonical_enum(self):
        assert set(_SENSITIVITY_ORDER) == {s.value for s in Sensitivity}
        assert set(_SENSITIVITY_ORDER) == set(CANONICAL_VALUES)

    def test_ordering_is_public_lt_internal_lt_private_lt_secret(self):
        o = _SENSITIVITY_ORDER
        assert o["public"] < o["internal"] < o["private"] < o["secret"]

    def test_no_invented_vocabulary_remains(self):
        for invented in ("low", "medium", "high", "critical"):
            assert invented not in _SENSITIVITY_ORDER

    def test_default_ceiling_is_a_canonical_value(self):
        assert DEFAULT_SENSITIVITY_CEILING in _SENSITIVITY_ORDER
        assert DEFAULT_SENSITIVITY_CEILING == Sensitivity.PRIVATE.value


# ---------------------------------------------------------------------------
# POSITIVE inclusion — the regression that makes vacuous green impossible
# ---------------------------------------------------------------------------
class TestPositiveEligibility:
    def test_public_event_is_eligible(self):
        res = is_eligible(_event("public"), "project_memory")
        assert res.eligible is True, res.reason
        assert res.reason == "eligible"

    def test_internal_event_is_eligible(self):
        """The exact value from the defect report (E1/E3 were 'internal')."""
        res = is_eligible(_event("internal"), "project_memory")
        assert res.eligible is True, res.reason

    def test_private_event_is_eligible_at_default_ceiling(self):
        res = is_eligible(_event("private"), "project_memory")
        assert res.eligible is True, res.reason

    def test_every_non_secret_canonical_value_can_be_eligible(self):
        for value in ("public", "internal", "private"):
            res = is_eligible(_event(value), "project_memory")
            assert res.eligible is True, f"{value} rejected: {res.reason}"

    def test_eligible_event_can_be_primary(self):
        """Proves the gate does not merely admit-then-demote everything."""
        res = is_eligible(_event("internal"), "project_memory")
        assert res.eligible is True and res.as_primary is True


# ---------------------------------------------------------------------------
# ceiling enforcement
# ---------------------------------------------------------------------------
class TestCeilingEnforcement:
    def test_private_excluded_when_ceiling_is_internal(self):
        res = is_eligible(_event("private"), "project_memory",
                          sensitivity_ceiling="internal")
        assert res.eligible is False
        assert res.reason == "sensitivity_ceiling_exceeded"

    def test_internal_excluded_when_ceiling_is_public(self):
        res = is_eligible(_event("internal"), "project_memory",
                          sensitivity_ceiling="public")
        assert res.eligible is False

    def test_public_still_allowed_at_public_ceiling(self):
        assert is_eligible(_event("public"), "project_memory",
                           sensitivity_ceiling="public").eligible is True

    def test_ceiling_is_inclusive_at_each_level(self):
        for value in ("public", "internal", "private"):
            res = is_eligible(_event(value), "project_memory",
                              sensitivity_ceiling=value)
            assert res.eligible is True, f"{value} at own ceiling: {res.reason}"


# ---------------------------------------------------------------------------
# secret — never evidence, at any ceiling
# ---------------------------------------------------------------------------
class TestSecretNeverEligible:
    def test_secret_excluded_at_default_ceiling(self):
        res = is_eligible(_event("secret"), "project_memory")
        assert res.eligible is False
        assert res.reason == "sensitivity_ceiling_exceeded"

    def test_secret_excluded_even_when_ceiling_is_secret(self):
        """Spec 14.1/14.2: secret is never persisted, so never evidence."""
        res = is_eligible(_event("secret"), "project_memory",
                          sensitivity_ceiling="secret")
        assert res.eligible is False

    def test_secret_excluded_for_every_possible_ceiling(self):
        for ceiling in CANONICAL_VALUES:
            res = is_eligible(_event("secret"), "project_memory",
                              sensitivity_ceiling=ceiling)
            assert res.eligible is False, f"secret leaked at ceiling={ceiling}"

    def test_secret_rejected_at_capture_boundary(self):
        """The corrective fix must not weaken never-store enforcement."""
        from src.redaction.redactor import redact_payload
        try:
            redact_payload({"x": "y"}, event_id="E", trace_id="T",
                           observed_at="2026-08-01T00:00:00Z",
                           sensitivity="secret", retention="persistent")
        except Exception as exc:
            assert "never_store" in str(exc)
        else:
            raise AssertionError("secret payload was not rejected at capture")


# ---------------------------------------------------------------------------
# fail-closed on unknown / malformed input
# ---------------------------------------------------------------------------
class TestFailClosed:
    def test_unknown_sensitivity_excluded(self):
        res = is_eligible(_event("banana"), "project_memory")
        assert res.eligible is False
        assert res.reason == "sensitivity_ceiling_exceeded"

    def test_retired_vocabulary_is_not_silently_accepted(self):
        for stale in ("low", "medium", "high", "critical"):
            res = is_eligible(_event(stale), "project_memory")
            assert res.eligible is False, f"stale value {stale} accepted"

    def test_none_sensitivity_excluded(self):
        assert is_eligible(_event(None), "project_memory").eligible is False

    def test_empty_and_whitespace_sensitivity_excluded(self):
        for value in ("", "   "):
            assert is_eligible(_event(value), "project_memory").eligible is False

    def test_non_string_sensitivity_excluded(self):
        for value in (0, 1, True, [], {}, object()):
            assert is_eligible(_event(value), "project_memory").eligible is False

    def test_malformed_ceiling_excludes_everything(self):
        """Regression: `99 > 99` was False, admitting everything (fail-open)."""
        for value in CANONICAL_VALUES:
            res = is_eligible(_event(value), "project_memory",
                              sensitivity_ceiling="banana")
            assert res.eligible is False, f"{value} admitted by malformed ceiling"

    def test_none_ceiling_excludes_everything(self):
        for value in CANONICAL_VALUES:
            assert is_eligible(_event(value), "project_memory",
                               sensitivity_ceiling=None).eligible is False

    def test_case_and_padding_normalized(self):
        for variant in ("INTERNAL", "Internal", " internal ", "\tinternal\n"):
            res = is_eligible(_event(variant), "project_memory")
            assert res.eligible is True, f"{variant!r} rejected: {res.reason}"


# ---------------------------------------------------------------------------
# other gates remain independent (fix must not widen anything else)
# ---------------------------------------------------------------------------
class TestOtherGatesUnchanged:
    def test_deleted_lifecycle_still_excluded_regardless_of_sensitivity(self):
        res = is_eligible(_event("public", lifecycle="deleted"), "project_memory")
        assert res.eligible is False
        assert res.reason.startswith("lifecycle_excluded")

    def test_incomplete_provenance_still_excluded(self):
        res = is_eligible(_event("public", event_id=""), "project_memory")
        assert res.eligible is False
        assert res.reason == "provenance_incomplete"

    def test_assistant_claim_eligible_but_never_primary(self):
        res = is_eligible(_event("internal", event_type="assistant_claim"),
                          "project_memory")
        assert res.eligible is True
        assert res.as_primary is False

    def test_m4_items_without_sensitivity_still_pass(self):
        """M4 rows carry no sensitivity and are governed by M5; unchanged."""
        class M4Row:
            decision_id = "DEC-1"
            effective_at = "2026-08-01T00:00:00Z"
            lifecycle_status = "active"
            verification_status = "verified"
        res = is_eligible(M4Row(), "project_memory")
        assert res.eligible is True, res.reason


# ---------------------------------------------------------------------------
# end-to-end: a real event actually reaches the EvidenceSet
# ---------------------------------------------------------------------------
class TestEventReachesEvidenceSet:
    def test_canonical_internal_event_reaches_evidence_set(self):
        """The functional consequence of the defect: no M3 event could EVER be
        selected. This proves an authorized canonical event now can be."""
        import tests.unit.test_m3_query as m3base
        import tests.unit.test_m4_rebuild as m4base
        from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
        from src.storage.ingest import rebuild_from_jsonl
        from src.retrieval.db import open_readonly
        from src.access.authorized_read import AuthorizedReadService
        from src.access.contracts import AccessRequest

        tmp = Path(tempfile.mkdtemp()).resolve()
        sp = tmp / "m7fix.sqlite"
        store = SQLiteStore(SQLiteStoreConfig(path=sp))
        store.ensure_schema()
        m4base._seed_m2_artifacts(store._conn)
        jl = tmp / "events.jsonl"
        m3base._write_jsonl(jl, [
            m3base._make_env("EV1", trace_id="TV1", project_id="P",
                             profile_id="PR1", subject="canonical internal event"),
        ])
        report = rebuild_from_jsonl(store, [jl])
        # Guard the fixture itself: a silently-rejected envelope would make the
        # eligibility assertion below vacuous.
        assert all(r.counts["new_event"] == 1 for r in report.values()), report
        store._conn.commit()
        store.close()

        ro = open_readonly(sp)
        svc = AuthorizedReadService(ro, requesting_profile_id="PR1")
        res = svc.query_events(AccessRequest(
            operation="READ", requesting_profile_id="PR1",
            target_profile_ids=["PR1"],
        ))
        assert res.allowed is True
        assert res.items, "fixture produced no authorized events"

        # The persisted value must be canonical, and it must now be eligible.
        selected = [e for e in res.items
                    if is_eligible(e, "session_memory").eligible]
        assert all(e.sensitivity in CANONICAL_VALUES for e in res.items)
        assert selected, (
            "no authorized canonical event passed eligibility — the M7.3 "
            "vocabulary defect has regressed"
        )
