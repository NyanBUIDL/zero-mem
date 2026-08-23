"""V133 / DEF-001 — RED-first regression: verified items must outrank unverified
in the M7 budget ordering.

Root cause (DEF-001): src/integration/m7/budget.py:51 compared verification
against ("verified", "confirmed") — NEITHER is a VerificationStatus member
(members: none, direct_tool_output, user_confirmation, deterministic_verification,
approval; "confirmed" belongs to LifecycleStatus). So genuinely verified items
never received rank 0 and the verified-priority ordering was dead for all real
memory events.

Expected after fix: verification="direct_tool_output" ranks before
verification="none", for both _order_key and select_evidence output ordering.
"""

from __future__ import annotations

import unittest


def _make_item(evidence_id, verification, lifecycle="active",
               created_at="2026-01-01T00:00:00Z", memory_type="decision"):
    from src.integration.m7.contracts import EvidenceItem

    return EvidenceItem(
        evidence_id=evidence_id,
        resource_type="event",
        memory_type=memory_type,
        summary=f"summary-{evidence_id}",
        source="test",
        created_at=created_at,
        lifecycle=lifecycle,
        verification=verification,
        confidence="high",
        sensitivity="internal",
        trace_id=f"trace-{evidence_id}",
    )


def _elig(item):
    from src.integration.m7.eligibility import is_eligible

    return is_eligible(item, route="SESSION")


class TestVerifiedRankDef001(unittest.TestCase):
    def test_order_key_verified_outranks_none(self):
        from src.integration.m7.budget import _order_key

        verified = _make_item("ev-verified", "direct_tool_output")
        unverified = _make_item("ev-none", "none")
        kv = _order_key(verified, _elig(verified), None)
        kn = _order_key(unverified, _elig(unverified), None)
        self.assertLess(kv, kn, "verified item must sort before unverified item")

    def test_order_key_all_verification_statuses_rank_zero(self):
        from src.integration.m7.budget import _order_key
        from src.capture.event_types import VerificationStatus

        for status in VerificationStatus:
            if status.value == "none":
                continue
            item = _make_item(f"ev-{status.value}", status.value)
            key = _order_key(item, _elig(item), None)
            # verified_rank is the 3rd component (after role_rank, state_rank)
            self.assertEqual(
                key[2], 0, f"verification={status.value!r} must yield verified_rank 0"
            )

    def test_order_key_none_yields_rank_one(self):
        from src.integration.m7.budget import _order_key

        item = _make_item("ev-x", "none")
        key = _order_key(item, _elig(item), None)
        self.assertEqual(key[2], 1)

    def test_select_evidence_orders_verified_first(self):
        from src.integration.m7.budget import select_evidence

        # raw-lifecycle items classify as supporting-only; differing verification
        # must order the verified one first within the supporting pool.
        raw_verified = _make_item("ev-raw-v", "direct_tool_output", lifecycle="raw")
        raw_none = _make_item("ev-raw-n", "none", lifecycle="raw")
        cands = [(raw_none, _elig(raw_none)), (raw_verified, _elig(raw_verified))]
        sel = select_evidence(cands, max_primary=5, max_supporting=3)
        ids = [i.evidence_id for i in sel.supporting]
        self.assertEqual(ids[0], "ev-raw-v",
                         "verified supporting item must be selected first")


if __name__ == "__main__":
    unittest.main()
