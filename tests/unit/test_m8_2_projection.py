"""M8.2 focused tests — deterministic graph projection.

Covers the pure projection layer: deterministic entity/mention/edge results,
closed relation-vocabulary enforcement, provenance preservation, source
identity preservation, and fail-closed behavior on malformed input.
"""

from __future__ import annotations

import pytest

from src.m8.graph_projection import (
    GRAPH_PROJECTION_VERSION,
    EdgeSourceRecord,
    EntitySourceRecord,
    MentionSourceRecord,
    ProjectionError,
    describe_projection,
    map_m2_relation_type,
    map_verification_subject_type,
    parse_link_list,
    project_edge,
    project_entity,
    project_mention,
)
from src.m8.identity import IDENTITY_VERSION


def edge_source(**overrides) -> EdgeSourceRecord:
    base = dict(
        from_resource_type="event",
        from_resource_id="E1",
        relation_type="derived_from",
        to_resource_type="event",
        to_resource_id="E2",
        relation_source="m2_relation",
        source_ref="zm_relations:E1:derived_from:E2",
        project_id="P1",
        lifecycle_status="candidate",
    )
    base.update(overrides)
    return EdgeSourceRecord(**base)


def entity_source(**overrides) -> EntitySourceRecord:
    base = dict(
        entity_type="person",
        canonical_name="Ada Lovelace",
        relation_source="m4_project_link",
        source_ref="zm_decisions:D1",
        project_id="P1",
    )
    base.update(overrides)
    return EntitySourceRecord(**base)


class TestDeterministicEdgeProjection:
    def test_same_source_yields_identical_edge(self):
        a = project_edge(edge_source())
        b = project_edge(edge_source())
        assert a.edge_id == b.edge_id
        assert a.to_canonical_json() == b.to_canonical_json()
        assert a.compute_content_hash() == b.compute_content_hash()

    def test_edge_id_is_stable_across_processes(self):
        # Deterministic digest, not a random UUID and not Python's hash().
        edge = project_edge(edge_source())
        assert edge.edge_id.startswith("edg_")
        assert edge.edge_id == project_edge(edge_source()).edge_id

    def test_typed_endpoints_participate_in_identity(self):
        as_event = project_edge(edge_source(to_resource_type="event", to_resource_id="X"))
        as_artifact = project_edge(
            edge_source(
                relation_type="source_of", to_resource_type="artifact", to_resource_id="X"
            )
        )
        assert as_event.edge_id != as_artifact.edge_id

    def test_source_ref_participates_in_identity(self):
        a = project_edge(edge_source(source_ref="ref:a"))
        b = project_edge(edge_source(source_ref="ref:b"))
        assert a.edge_id != b.edge_id

    def test_lifecycle_copied_not_upgraded(self):
        edge = project_edge(edge_source(lifecycle_status="superseded"))
        assert edge.lifecycle_status == "superseded"

    def test_verification_absent_stays_none(self):
        assert project_edge(edge_source()).verification_status is None


class TestRelationVocabularyEnforcement:
    def test_unknown_relation_type_rejected(self):
        with pytest.raises(ProjectionError):
            project_edge(edge_source(relation_type="totally_made_up"))

    def test_unknown_relation_is_not_coerced_to_related_to(self):
        try:
            project_edge(edge_source(relation_type="child_of"))
        except ProjectionError:
            pass
        else:  # pragma: no cover - guard
            pytest.fail("child_of must not be admitted")

    def test_m2_map_returns_none_for_unmapped(self):
        assert map_m2_relation_type("child_of") is None
        assert map_m2_relation_type("nonsense") is None
        assert map_m2_relation_type(None) is None  # type: ignore[arg-type]

    def test_m2_map_only_approved_members(self):
        assert map_m2_relation_type("derived_from") == "derived_from"
        assert map_m2_relation_type("supersedes") == "supersedes"

    def test_unknown_resource_type_rejected(self):
        with pytest.raises(ProjectionError):
            project_edge(edge_source(from_resource_type="node"))

    def test_unknown_relation_source_rejected(self):
        with pytest.raises(ProjectionError):
            project_edge(edge_source(relation_source="llm_inferred"))

    def test_unknown_lifecycle_rejected(self):
        with pytest.raises(ProjectionError):
            project_edge(edge_source(lifecycle_status="accepted"))

    def test_verification_subject_map_is_closed(self):
        assert map_verification_subject_type("decision") == "decision"
        assert map_verification_subject_type("session") is None


class TestProvenancePreservation:
    def test_provenance_carries_source_identity(self):
        edge = project_edge(edge_source(source_event_id="E1", trace_id="T1"))
        prov = edge.provenance
        assert prov.relation_source == "m2_relation"
        assert prov.source_ref == "zm_relations:E1:derived_from:E2"
        assert prov.source_event_id == "E1"
        assert prov.trace_id == "T1"

    def test_projection_and_identity_versions_stamped(self):
        prov = project_edge(edge_source()).provenance
        assert prov.projection_version == GRAPH_PROJECTION_VERSION
        assert prov.identity_version == IDENTITY_VERSION

    def test_absent_trace_id_is_not_fabricated(self):
        prov = project_edge(edge_source(trace_id=None)).provenance
        assert prov.trace_id is None

    def test_provenance_hash_is_deterministic(self):
        assert (
            project_edge(edge_source()).provenance.compute_hash()
            == project_edge(edge_source()).provenance.compute_hash()
        )

    def test_missing_source_ref_fails_closed(self):
        with pytest.raises(ProjectionError):
            project_edge(edge_source(source_ref=""))


class TestEntityProjection:
    def test_deterministic_entity_id(self):
        assert project_entity(entity_source()).entity_id == (
            project_entity(entity_source()).entity_id
        )

    def test_case_difference_is_not_merged(self):
        a = project_entity(entity_source(canonical_name="Ada"))
        b = project_entity(entity_source(canonical_name="ada"))
        assert a.entity_id != b.entity_id

    def test_similar_names_are_not_merged(self):
        a = project_entity(entity_source(canonical_name="Ada Lovelace"))
        b = project_entity(entity_source(canonical_name="A. Lovelace"))
        assert a.entity_id != b.entity_id

    def test_unknown_entity_type_rejected(self):
        with pytest.raises(ProjectionError):
            project_entity(entity_source(entity_type="alien"))

    def test_empty_name_rejected(self):
        with pytest.raises(ProjectionError):
            project_entity(entity_source(canonical_name="   "))


class TestMentionProjection:
    def test_deterministic_mention_id(self):
        record = MentionSourceRecord(
            entity=entity_source(), source_event_id="E1", span_start=0, span_end=4,
            mention_text="Ada",
        )
        assert project_mention(record).mention_id == project_mention(record).mention_id

    def test_raw_text_is_hashed_not_stored(self):
        record = MentionSourceRecord(
            entity=entity_source(), source_event_id="E1", mention_text="secret-span"
        )
        payload = project_mention(record).to_dict()
        assert "secret-span" not in str(payload)
        assert payload["mention_text_hash"]

    def test_missing_span_stays_none(self):
        record = MentionSourceRecord(
            entity=entity_source(), source_event_id="E1", mention_text="Ada"
        )
        projected = project_mention(record)
        assert projected.span_start is None and projected.span_end is None

    def test_span_participates_in_identity(self):
        a = project_mention(
            MentionSourceRecord(
                entity=entity_source(), source_event_id="E1", span_start=0,
                span_end=3, mention_text="Ada",
            )
        )
        b = project_mention(
            MentionSourceRecord(
                entity=entity_source(), source_event_id="E1", span_start=7,
                span_end=10, mention_text="Ada",
            )
        )
        assert a.mention_id != b.mention_id

    def test_mention_inherits_entity_scope(self):
        record = MentionSourceRecord(
            entity=entity_source(profile_id="prof-a", project_id="P1"),
            source_event_id="E1", mention_text="Ada",
        )
        mention = project_mention(record)
        assert mention.scope.profile_id == "prof-a"
        assert mention.scope.project_id == "P1"

    def test_inverted_span_fails_closed(self):
        with pytest.raises(ProjectionError):
            project_mention(
                MentionSourceRecord(
                    entity=entity_source(), source_event_id="E1", span_start=9,
                    span_end=2, mention_text="Ada",
                )
            )

    def test_missing_text_and_hash_fails_closed(self):
        with pytest.raises(ProjectionError):
            project_mention(
                MentionSourceRecord(entity=entity_source(), source_event_id="E1")
            )

    def test_missing_source_event_fails_closed(self):
        with pytest.raises(ProjectionError):
            project_mention(
                MentionSourceRecord(
                    entity=entity_source(), source_event_id="", mention_text="Ada"
                )
            )


class TestLinkListParsing:
    def test_none_is_empty(self):
        assert parse_link_list(None, "f") == ()

    def test_comma_separated(self):
        assert parse_link_list("R1, R2 ,R3", "f") == ("R1", "R2", "R3")

    def test_json_array(self):
        assert parse_link_list('["R1", "R2"]', "f") == ("R1", "R2")

    def test_duplicates_collapse_deterministically(self):
        assert parse_link_list("R1,R2,R1", "f") == ("R1", "R2")

    def test_order_is_preserved(self):
        assert parse_link_list("R2,R1", "f") == ("R2", "R1")

    def test_malformed_json_fails_closed(self):
        with pytest.raises(ProjectionError):
            parse_link_list('["R1",', "f")

    def test_json_object_fails_closed(self):
        with pytest.raises(ProjectionError):
            parse_link_list('{"a": 1}'.replace("{", "[{").replace("}", "}]"), "f")


class TestProjectionDescription:
    def test_declares_derived_not_truth(self):
        d = describe_projection()
        assert d["graph_is_derived"] is True
        assert d["graph_is_truth"] is False
        assert d["makes_authorization_decisions"] is False
        assert d["resolves_conflicts"] is False

    def test_declares_later_increments_absent(self):
        d = describe_projection()
        assert d["temporal_query_implemented"] is True
        assert d["calibration_scoring_implemented"] is True

    def test_schema_version_unchanged(self):
        assert describe_projection()["schema_version"] == 13
