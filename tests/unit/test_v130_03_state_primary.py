"""V130-03 — State-as-primary promotion in PROJECT route (contract-first test frame).

Contract (docs/v1.3.0/plans/V130-03-SPEC.md + APPROVE-V130-03.md invariants 1–6):
- is_eligible gains optional route param (MemoryRoute); promotion rule placed AFTER
  all existing guards: primary |= PROJECT and state and lifecycle active.
- assistant_claim NEVER primary via this path; non-PROJECT routes byte-for-byte unchanged.
- Budget 5/3/8 preserved.

RED until V130-03 implemented.
"""
from __future__ import annotations

import pytest

from src.integration.m7.contracts import MemoryRoute
from src.integration.m7.eligibility import EligibilityResult, is_eligible


class _Item:
    """Minimal evidence-like item for eligibility classification."""
    def __init__(self, **kw):
        self.event_id = kw.get("event_id", "ev-1")
        self.lifecycle_status = kw.get("lifecycle_status", "active")
        self.verification_status = kw.get("verification_status", "none")
        self.memory_type = kw.get("memory_type", "state")
        self.sensitivity = kw.get("sensitivity", "public")
        self.created_at = kw.get("created_at", "2026-08-22T00:00:00Z")


# --- invariant 1+6: active state promotes in PROJECT ------------------------

def test_active_state_primary_in_project_route():
    res = is_eligible(_Item(), MemoryRoute.PROJECT.value, resource_type="state",
                      promote_state_in_project=True)
    assert res.eligible and res.as_primary


def test_active_state_not_primary_without_flag():
    # default behavior (route passed but promotion flag off) must stay as before
    res = is_eligible(_Item(), MemoryRoute.PROJECT.value, resource_type="state")
    assert res.eligible and not res.as_primary


# --- invariant 1: guards still win ------------------------------------------

def test_superseded_state_never_primary_even_in_project():
    res = is_eligible(_Item(lifecycle_status="superseded"), MemoryRoute.PROJECT.value,
                      resource_type="state", promote_state_in_project=True)
    assert not res.as_primary


def test_archived_state_never_primary_even_in_project():
    res = is_eligible(_Item(lifecycle_status="archived"), MemoryRoute.PROJECT.value,
                      resource_type="state", promote_state_in_project=True)
    assert not res.as_primary


# --- invariant 2: assistant_claim never promoted via this path ---------------

def test_assistant_claim_never_promoted_in_project():
    res = is_eligible(_Item(memory_type="assistant_claim"),
                      MemoryRoute.PROJECT.value, resource_type="event",
                      promote_state_in_project=True)
    assert not res.as_primary


# --- invariant 3: non-PROJECT routes byte-for-byte unchanged -----------------

@pytest.mark.parametrize("route", [MemoryRoute.SESSION, MemoryRoute.USER,
                                   MemoryRoute.RESEARCH])
def test_non_project_routes_unchanged(route):
    res = is_eligible(_Item(), route.value, resource_type="state",
                      promote_state_in_project=True)
    assert res.eligible and not res.as_primary


def test_route_none_unchanged():
    res = is_eligible(_Item(), None, resource_type="state",
                      promote_state_in_project=True)
    assert res.eligible and not res.as_primary


# --- budget-level: selection keeps 5/3/8 with promoted state ------------------

def _build_items(n_states=2, n_decisions=5, n_requirements=4):
    items = []
    for i in range(n_states):
        items.append((_Item(event_id=f"S{i}", memory_type="state"), "state"))
    for i in range(n_decisions):
        items.append((_Item(event_id=f"D{i}",
                            memory_type="decision",
                            verification_status="deterministic_verification"), "decision"))
    for i in range(n_requirements):
        items.append((_Item(event_id=f"R{i}", memory_type="requirement",
                            verification_status="user_confirmation"), "requirement"))
    return items


def test_artifact_view_lifecycle_never_none():
    """D-2026-08-22-05: ProjectArtifactView always carries a concrete lifecycle
    ('active') — EvidenceItem.lifecycle must never be None from the artifact path.
    Regression for the latent bug exposed by V130-03 promotion."""
    from src.project_memory.reader import ProjectArtifactView
    v = ProjectArtifactView(
        artifact_id="ART1", project_id="P", artifact_type=None, version=None,
        safe_reference=None, source_event_id=None, created_at="2026-08-07T00:00:00Z",
        verification_status="none", linked_requirement_ids=None,
        linked_decision_ids=None, linked_state_keys=None,
    )
    assert v.lifecycle_status == "active"


def test_artifact_evidence_item_lifecycle_well_formed():
    """End-to-end: an artifact EvidenceItem built from the view has a lifecycle in
    the closed enum, never None."""
    from src.integration.m7.evidence_builder import _to_evidence_item
    from src.integration.m7.contracts import MemoryRoute, EvidenceRole

    class _FakeArtifactView:
        artifact_id = "ART1"
        project_id = "P"
        artifact_type = "report"
        version = None
        safe_reference = None
        source_event_id = "E50"
        created_at = "2026-08-07T00:00:00Z"
        verification_status = "none"
        linked_requirement_ids = None
        linked_decision_ids = None
        linked_state_keys = None
        lifecycle_status = "active"

    ev = _to_evidence_item(_FakeArtifactView(), MemoryRoute.PROJECT, "artifact",
                           EvidenceRole.SUPPORTING, "eligible")
    assert ev.lifecycle is not None
    assert ev.lifecycle in ("active", "candidate", "conflicted", "superseded",
                            "archived", "deleted", "none")


def test_budget_bounds_preserved_with_promotion():
    from src.integration.m7.budget import select_evidence
    from src.integration.m7.evidence_builder import _to_evidence_item

    candidates = []
    for item, rt in _build_items():
        res = is_eligible(item, MemoryRoute.PROJECT.value, resource_type=rt,
                          promote_state_in_project=True)
        assert res.eligible
        ev = _to_evidence_item(item, MemoryRoute.PROJECT, rt,
                               __import__("src.integration.m7.contracts", fromlist=["EvidenceRole"]).EvidenceRole.PRIMARY if res.as_primary else __import__("src.integration.m7.contracts", fromlist=["EvidenceRole"]).EvidenceRole.SUPPORTING,
                               res.reason)
        candidates.append((ev, res))
    sel = select_evidence(candidates, route=MemoryRoute.PROJECT)
    total = len(sel.primary) + len(sel.supporting)
    assert len(sel.primary) <= 5
    assert len(sel.supporting) <= 3
    assert total <= 8
    # at least one promoted state made it into the bounded set
    ids = {i.evidence_id for i in sel.primary + sel.supporting}
    assert any(s.startswith("S") for s in ids)
