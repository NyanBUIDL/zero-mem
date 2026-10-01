"""DEF-056 - CorpusHit exposes external_ref + memory_type; both are post-
authorization filters.  ADR: docs/v1.6.1/decisions/ADR-V170-01-CORPUS-HIT-PROVENANCE.md.

The authorization decision must be unchanged by the new filters.
"""
from __future__ import annotations

import dataclasses

import pytest

from src.corpus.query_planner import CorpusQueryError, build_query_plan
from src.corpus.retrieval import CorpusHit
from tests.unit.t3_corpus_helpers import build_store, doc, search

PERSONA = "Prefers terse answers and always runs pytest."
WORKFLOW = "Run pytest before every commit and keep commits small."
FACT = "The deploy script lives in scripts/deploy.sh."
PLAIN = "pytest plain note without a memory type."


def _store(tmp_path):
    return build_store(tmp_path, [
        doc(PERSONA, ref="mem://persona/style", meta={"memory_type": "persona"}),
        doc(WORKFLOW, ref="mem://workflow/commit-flow", meta={"memory_type": "workflow"}),
        doc(FACT, ref="mem://fact/abc123", meta={"memory_type": "fact"}),
        doc(PLAIN, ref="file://notes/plain.txt"),
        # Another agent's private persona: matching memory_type, NOT authorized for p1.
        doc("Other agent persona mentions pytest too.", ref="mem://persona/other",
            profile="p2", meta={"memory_type": "persona"}),
    ])


def _by_text(result):
    return {hit.normalized_text: hit for hit in result.items}


def test_hit_exposes_external_ref_and_memory_type(tmp_path):
    ro = _store(tmp_path)
    hits = _by_text(search(ro, "pytest"))
    persona = hits[PERSONA]
    assert persona.external_ref == "mem://persona/style"
    assert persona.memory_type == "persona"
    assert hits[WORKFLOW].memory_type == "workflow"
    assert hits[WORKFLOW].external_ref == "mem://workflow/commit-flow"
    ro.close()


def test_source_without_memory_type_keeps_none_but_has_external_ref(tmp_path):
    ro = _store(tmp_path)
    plain = _by_text(search(ro, "pytest"))[PLAIN]
    assert plain.memory_type is None
    assert plain.external_ref == "file://notes/plain.txt"
    ro.close()


def test_evidence_dict_carries_provenance(tmp_path):
    ro = _store(tmp_path)
    persona = _by_text(search(ro, "pytest"))[PERSONA]
    evidence = persona.as_evidence_dict()
    assert evidence["external_ref"] == "mem://persona/style"
    assert evidence["memory_type"] == "persona"
    ro.close()


def test_new_hit_fields_default_to_none_for_existing_constructors():
    names = {f.name: f for f in dataclasses.fields(CorpusHit)}
    assert names["external_ref"].default is None
    assert names["memory_type"].default is None


def test_memory_type_filter_narrows_to_authorized_matching_sources(tmp_path):
    ro = _store(tmp_path)
    result = search(ro, "pytest", metadata={"memory_type": "persona"})
    assert [hit.normalized_text for hit in result.items] == [PERSONA]
    ro.close()


def test_external_ref_prefix_filter(tmp_path):
    ro = _store(tmp_path)
    result = search(ro, "pytest", metadata={"external_ref_prefix": "mem://workflow/"})
    assert [hit.normalized_text for hit in result.items] == [WORKFLOW]
    both = search(ro, "", metadata={"external_ref_prefix": "mem://"})  # metadata-only
    assert {hit.memory_type for hit in both.items} == {"persona", "workflow", "fact"}
    assert all(hit.profile_id == "p1" for hit in both.items)
    ro.close()


def test_filters_combine_with_and(tmp_path):
    ro = _store(tmp_path)
    assert search(ro, "pytest", metadata={"memory_type": "persona"}).items  # non-vacuous
    result = search(ro, "pytest", metadata={
        "memory_type": "persona", "external_ref_prefix": "mem://workflow/"})
    assert result.items == []
    assert result.reason_code == search(ro, "pytest").reason_code
    ro.close()


def test_filters_work_for_metadata_only_queries(tmp_path):
    ro = _store(tmp_path)
    result = search(ro, "", metadata={"memory_type": "fact"})
    assert [hit.normalized_text for hit in result.items] == [FACT]
    ro.close()


def test_filter_never_widens_authorization(tmp_path):
    """The decision and the authorized universe are identical with and without
    the filter; the unauthorized persona (profile p2) never appears."""
    ro = _store(tmp_path)
    unfiltered = search(ro, "pytest")
    filtered = search(ro, "pytest", metadata={"memory_type": "persona"})

    assert filtered.allowed is unfiltered.allowed is True
    assert filtered.reason_code == unfiltered.reason_code
    assert [hit.normalized_text for hit in filtered.items] == [PERSONA]  # non-vacuous
    unfiltered_ids = {hit.unit_id for hit in unfiltered.items}
    assert {hit.unit_id for hit in filtered.items} <= unfiltered_ids
    assert all(hit.profile_id == "p1" for hit in filtered.items)
    assert "mem://persona/other" not in {hit.external_ref for hit in filtered.items}
    ro.close()


def test_filter_does_not_unlock_other_profiles_for_other_requester(tmp_path):
    ro = _store(tmp_path)
    result = search(ro, "pytest", profile="p3", metadata={"memory_type": "persona"})
    assert result.items == []  # p3 owns nothing and has no grants
    ro.close()


@pytest.mark.parametrize("bad", [
    {"memory_type": ""},
    {"memory_type": 5},
    {"memory_type": "x" * 200},
    {"memory_type": "bad type with spaces"},
    {"external_ref_prefix": ""},
    {"external_ref_prefix": 7},
    {"external_ref_prefix": "x" * 2000},
])
def test_invalid_filter_values_are_rejected(bad):
    with pytest.raises(CorpusQueryError):
        build_query_plan("pytest", metadata=bad)


def test_unknown_metadata_key_is_still_rejected():
    with pytest.raises(CorpusQueryError):
        build_query_plan("pytest", metadata={"finance_sector": "bank"})
    with pytest.raises(CorpusQueryError):
        build_query_plan("pytest", metadata={"external_ref": "mem://x"})  # only the prefix form


def test_plan_round_trips_new_filters():
    plan = build_query_plan("pytest", metadata={"memory_type": "persona",
                                                "external_ref_prefix": "mem://persona/"})
    assert plan.metadata.as_dict() == {"memory_type": "persona",
                                       "external_ref_prefix": "mem://persona/"}


def test_malformed_custom_meta_yields_no_memory_type():
    from src.corpus.retrieval import _memory_type_from_custom_meta

    assert _memory_type_from_custom_meta('{"memory_type": "persona"}') == "persona"
    assert _memory_type_from_custom_meta("{not json") is None
    assert _memory_type_from_custom_meta('["list"]') is None
    assert _memory_type_from_custom_meta('{"memory_type": 5}') is None
    assert _memory_type_from_custom_meta(None) is None
    assert _memory_type_from_custom_meta("") is None


def test_mcp_corpus_search_surfaces_provenance(tmp_path):
    """The M6 read path returns hits through ``_safe_view`` so the new fields
    reach agents with no handler change."""
    from src.integration.m6 import handlers
    from src.integration.m6.contracts import M6Request
    from src.integration.m6.runtime import M6Runtime

    ro = _store(tmp_path)
    runtime = M6Runtime(ro.path)
    request = M6Request(tool="corpus_search", requesting_profile_id="p1",
                        search_text="pytest")
    items = handlers.handle_corpus_search(request, runtime)
    by_ref = {item["external_ref"]: item for item in items}
    assert by_ref["mem://persona/style"]["memory_type"] == "persona"
    assert "mem://persona/other" not in by_ref
    ro.close()
