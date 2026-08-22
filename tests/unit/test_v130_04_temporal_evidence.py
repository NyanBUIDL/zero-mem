"""V130-04 — Temporal/as-of read (M8.4) wired into EvidenceSet (contract-first frame).

Contract (docs/v1.3.0/plans/V130-04-SPEC.md):
- build_evidence_set / RouterRequest gain optional as_of (ISO-8601). Malformed
  as_of fails closed at the request boundary.
- When as_of is set, AFTER the validated EvidenceSet is built, read_temporal() runs
  for each authorized resource; results attach to the NEW additive field
  EvidenceSet.temporal (None when no as_of or on graceful degradation).
- Annotation-only: selection/order/budget unchanged. Authorization-first: an
  unauthorized resource never appears in temporal info. Bounded <= MAX_HISTORY_VERSIONS.

RED until V130-04 implemented.
"""
from __future__ import annotations

import pytest


# --- contract: request accepts/validates as_of -------------------------------

def test_router_request_accepts_as_of():
    from src.integration.m7.contracts import RouterRequest

    r = RouterRequest(requesting_profile_id="PR1", project_id="P", as_of="2026-08-01T00:00:00Z")
    assert r.as_of == "2026-08-01T00:00:00Z"


def test_evidence_set_has_temporal_field_default_none():
    from src.integration.m7.contracts import EvidenceSet

    assert "temporal" in EvidenceSet.__dataclass_fields__


# --- contract: no as_of -> byte-giống hiện tại (temporal None) ---------------

def test_no_as_of_temporal_is_none():
    from tests.unit.test_m8_6_integration import _build_store, _router, _es

    es = _es(_build_store())
    assert es.temporal is None


# --- contract: malformed as_of fails closed ----------------------------------

def test_malformed_as_of_fails_closed():
    from src.integration.m7.evidence_builder import build_evidence_set
    from src.integration.m7.memory_router import route as m7route
    from src.integration.m7.contracts import RouterRequest
    from src.access.authorized_read import AuthorizedReadService
    from tests.unit.test_m8_6_integration import _build_store

    store = _build_store()
    svc = AuthorizedReadService(store, requesting_profile_id="PR1")
    rr = RouterRequest(normalized_text="Continue the project.", project_id="P",
                       requesting_profile_id="PR1", explicit_project_intent=True,
                       as_of="not-a-timestamp")
    with pytest.raises(Exception) as ei:
        build_evidence_set(m7route(rr), svc, rr)
    # fail closed: a typed error, not a silent pass-through with temporal=None
    assert not isinstance(ei.value, AssertionError)


# --- contract: as_of set -> temporal annotation present ----------------------

def test_as_of_builds_temporal_annotation():
    from src.integration.m7.evidence_builder import build_evidence_set
    from src.integration.m7.memory_router import route as m7route
    from src.integration.m7.contracts import RouterRequest
    from src.access.authorized_read import AuthorizedReadService
    from tests.unit.test_m8_6_integration import _build_store

    store = _build_store()
    svc = AuthorizedReadService(store, requesting_profile_id="PR1")
    rr = RouterRequest(normalized_text="Continue the project.", project_id="P",
                       requesting_profile_id="PR1", explicit_project_intent=True,
                       as_of="2026-08-01T00:00:00Z")
    es = build_evidence_set(m7route(rr), svc, rr)
    assert es.memory_needed
    assert es.temporal is not None
    # bounded: history_count per resource <= MAX_HISTORY_VERSIONS (20)
    from src.m8.temporal_read import MAX_HISTORY_VERSIONS
    for entry in es.temporal.resources:
        assert entry.history_count <= MAX_HISTORY_VERSIONS
        # annotation-only: superseded_by is provenance verbatim (str or None)
        assert entry.superseded_by is None or isinstance(entry.superseded_by, str)


# --- contract: annotation does not change selection --------------------------

def test_selection_identical_with_and_without_as_of():
    from src.integration.m7.evidence_builder import build_evidence_set
    from src.integration.m7.memory_router import route as m7route
    from src.integration.m7.contracts import RouterRequest
    from src.access.authorized_read import AuthorizedReadService
    from tests.unit.test_m8_6_integration import _build_store

    store = _build_store()
    def build(as_of):
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        rr = RouterRequest(normalized_text="Continue the project.", project_id="P",
                           requesting_profile_id="PR1", explicit_project_intent=True,
                           as_of=as_of)
        return build_evidence_set(m7route(rr), svc, rr)

    plain = build(None)
    stamped = build("2026-08-01T00:00:00Z")
    ids_plain = [(e.evidence_id, e.role.value) for e in plain.primary_evidence + plain.supporting_evidence]
    ids_stamped = [(e.evidence_id, e.role.value) for e in stamped.primary_evidence + stamped.supporting_evidence]
    assert ids_plain == ids_stamped
