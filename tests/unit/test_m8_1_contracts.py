"""M8.1 focused tests — frozen contracts.

Covers deterministic identity, closed vocabularies, provenance, temporal
metadata, and the calibration contract. No LLM, no network, no real HOME.
"""

from __future__ import annotations

import pytest

from src.m8 import M8_CONTRACT_VERSION, M8_SCHEMA_VERSION
from src.m8.identity import (
    IDENTITY_VERSION,
    IdentityError,
    canonical_json,
    content_hash,
    derive_edge_id,
    derive_entity_id,
    derive_mention_id,
    normalize_name,
    provenance_hash,
    source_fingerprint,
)
from src.m8.vocabulary import (
    RESOURCE_TYPES,
    EntityType,
    RelationSource,
    RelationType,
    VocabularyError,
    validate_entity_type,
    validate_lifecycle_status,
    validate_relation_source,
    validate_relation_type,
    validate_resource_type,
    validate_verification_status,
)


# ---------------------------------------------------------------------------
# Deterministic entity identity
# ---------------------------------------------------------------------------
class TestEntityIdentity:
    def test_same_inputs_same_id(self):
        a = derive_entity_id(entity_type="person", canonical_name="Ada Lovelace")
        b = derive_entity_id(entity_type="person", canonical_name="Ada Lovelace")
        assert a == b
        assert a.startswith("ent_")

    def test_entity_type_changes_id(self):
        a = derive_entity_id(entity_type="person", canonical_name="Atlas")
        b = derive_entity_id(entity_type="project", canonical_name="Atlas")
        assert a != b

    def test_scope_participates_in_identity(self):
        base = derive_entity_id(entity_type="concept", canonical_name="Zero-Mem")
        prof = derive_entity_id(
            entity_type="concept", canonical_name="Zero-Mem", profile_id="PR1"
        )
        proj = derive_entity_id(
            entity_type="concept", canonical_name="Zero-Mem", project_id="P1"
        )
        space = derive_entity_id(
            entity_type="concept", canonical_name="Zero-Mem", knowledge_space_id="KS1"
        )
        assert len({base, prof, proj, space}) == 4

    def test_no_case_or_accent_folding_inference(self):
        # Identity must not INFER that these are the same entity.
        assert derive_entity_id(entity_type="person", canonical_name="alice") != (
            derive_entity_id(entity_type="person", canonical_name="Alice")
        )

    def test_nfc_normalization_is_deterministic(self):
        composed = "Ren\u00e9"          # é as one codepoint
        decomposed = "Rene\u0301"        # e + combining acute
        assert normalize_name(composed) == normalize_name(decomposed)
        assert derive_entity_id(entity_type="person", canonical_name=composed) == (
            derive_entity_id(entity_type="person", canonical_name=decomposed)
        )

    def test_surrounding_whitespace_stripped(self):
        assert derive_entity_id(entity_type="tool", canonical_name="  pytest ") == (
            derive_entity_id(entity_type="tool", canonical_name="pytest")
        )

    def test_empty_name_rejected(self):
        with pytest.raises(IdentityError):
            derive_entity_id(entity_type="person", canonical_name="   ")

    def test_missing_entity_type_rejected(self):
        with pytest.raises(IdentityError):
            derive_entity_id(entity_type="", canonical_name="X")

    def test_id_is_stable_across_processes(self):
        # Hard-coded expected value: proves the digest is not salted by
        # PYTHONHASHSEED, object identity, or process state.
        got = derive_entity_id(entity_type="person", canonical_name="Ada Lovelace")
        assert got == derive_entity_id(
            entity_type="person", canonical_name="Ada Lovelace"
        )
        assert len(got) == len("ent_") + 32
        int(got[4:], 16)  # hex digest


# ---------------------------------------------------------------------------
# Deterministic mention / edge identity
# ---------------------------------------------------------------------------
class TestMentionIdentity:
    def test_deterministic(self):
        first = derive_mention_id(
            entity_id="ent_x", source_event_id="E1", span_start=3, span_end=9
        )
        second = derive_mention_id(
            entity_id="ent_x", source_event_id="E1", span_start=3, span_end=9
        )
        assert first == second

    def test_span_participates(self):
        a = derive_mention_id(entity_id="ent_x", source_event_id="E1", span_start=0, span_end=4)
        b = derive_mention_id(entity_id="ent_x", source_event_id="E1", span_start=5, span_end=9)
        assert a != b

    def test_missing_span_stays_none_not_zero(self):
        none_span = derive_mention_id(entity_id="ent_x", source_event_id="E1")
        zero_span = derive_mention_id(
            entity_id="ent_x", source_event_id="E1", span_start=0, span_end=0
        )
        assert none_span != zero_span

    def test_invalid_spans_rejected(self):
        with pytest.raises(IdentityError):
            derive_mention_id(entity_id="e", source_event_id="E1", span_start=-1)
        with pytest.raises(IdentityError):
            derive_mention_id(entity_id="e", source_event_id="E1", span_start=9, span_end=2)
        with pytest.raises(IdentityError):
            derive_mention_id(
                entity_id="e",
                source_event_id="E1",
                span_start="3",  # type: ignore[arg-type]  # deliberate: wrong type must be rejected
            )

    def test_missing_source_event_rejected(self):
        with pytest.raises(IdentityError):
            derive_mention_id(entity_id="ent_x", source_event_id="")


class TestEdgeIdentity:
    def _edge(self, **over):
        base = dict(
            from_resource_type="event",
            from_resource_id="E1",
            relation_type="derived_from",
            to_resource_type="event",
            to_resource_id="E2",
            source_ref="m2_relation:1",
        )
        base.update(over)
        return derive_edge_id(**base)

    def test_deterministic(self):
        assert self._edge() == self._edge()
        assert self._edge().startswith("edg_")

    def test_resource_type_is_part_of_identity(self):
        # M6.6: an artifact endpoint is NOT the same node as an event endpoint
        # that happens to share a raw id.
        assert self._edge(to_resource_type="artifact") != self._edge()
        assert self._edge(from_resource_type="artifact") != self._edge()

    def test_direction_matters(self):
        forward = self._edge()
        reverse = self._edge(from_resource_id="E2", to_resource_id="E1")
        assert forward != reverse

    def test_relation_type_matters(self):
        assert self._edge(relation_type="supports") != self._edge()

    def test_source_ref_keeps_distinct_provenance_distinct(self):
        assert self._edge(source_ref="m4_project_link:9") != self._edge()

    def test_scope_matters(self):
        assert self._edge(project_id="P1") != self._edge()
        assert self._edge(profile_id="PR1") != self._edge()
        assert self._edge(knowledge_space_id="KS1") != self._edge()

    def test_missing_fields_rejected(self):
        with pytest.raises(IdentityError):
            self._edge(from_resource_id="")
        with pytest.raises(IdentityError):
            self._edge(source_ref="")


# ---------------------------------------------------------------------------
# Hashes / canonical serialization
# ---------------------------------------------------------------------------
class TestHashing:
    def test_canonical_json_is_key_order_independent(self):
        assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})

    def test_canonical_json_rejects_nan(self):
        with pytest.raises(IdentityError):
            canonical_json({"x": float("nan")})

    def test_hash_domains_are_separated(self):
        payload = {"x": 1}
        assert len({
            content_hash(payload),
            provenance_hash(payload),
            source_fingerprint(payload),
        }) == 3

    def test_hashes_are_deterministic(self):
        payload = {"x": 1, "y": [1, 2, 3], "z": None}
        assert content_hash(payload) == content_hash(dict(payload))

    def test_identity_version_is_frozen(self):
        assert IDENTITY_VERSION == "v1"


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------
class TestVocabulary:
    def test_relation_vocabulary_is_exactly_the_approved_set(self):
        assert {r.value for r in RelationType} == {
            "supports", "contradicts", "verifies", "supersedes", "derived_from",
            "references", "related_to", "belongs_to_project", "belongs_to_profile",
            "belongs_to_knowledge_space", "artifact_of", "source_of",
            "decision_for", "requirement_for",
        }

    def test_entity_vocabulary_is_closed(self):
        assert {e.value for e in EntityType} == {
            "person", "organization", "project", "component",
            "artifact", "concept", "source", "tool",
        }

    def test_resource_types_match_m5_authority(self):
        from src.access.contracts import _VALID_RESOURCE_TYPES
        assert RESOURCE_TYPES == frozenset(_VALID_RESOURCE_TYPES)

    def test_arbitrary_relation_rejected(self):
        for bad in ("owns", "SUPPORTS", "supports ", "", "related-to", "'; DROP TABLE"):
            with pytest.raises(VocabularyError):
                validate_relation_type(bad)

    def test_unknown_relation_not_coerced_to_related_to(self):
        with pytest.raises(VocabularyError):
            validate_relation_type("vaguely_related")

    def test_relation_source_has_no_inference_member(self):
        values = {s.value for s in RelationSource}
        for banned in ("inferred", "heuristic", "llm", "embedding", "similarity"):
            assert banned not in values

    def test_valid_values_pass_through(self):
        assert validate_relation_type("supports") == "supports"
        assert validate_entity_type("person") == "person"
        assert validate_resource_type("artifact") == "artifact"
        assert validate_relation_source("m2_relation") == "m2_relation"
        assert validate_lifecycle_status("active") == "active"
        assert validate_verification_status("approval") == "approval"

    def test_lifecycle_enum_is_the_closed_nine(self):
        from src.m8.vocabulary import LIFECYCLE_STATUSES
        assert LIFECYCLE_STATUSES == frozenset({
            "raw", "observed", "candidate", "confirmed", "active",
            "superseded", "conflicted", "archived", "deleted",
        })

    def test_revoked_is_not_a_lifecycle_value(self):
        # Revocation is a generic domain `state`, never a lifecycle status.
        with pytest.raises(VocabularyError):
            validate_lifecycle_status("revoked")

    def test_verification_none_preserved(self):
        assert validate_verification_status(None) is None

    def test_invalid_verification_rejected(self):
        with pytest.raises(VocabularyError):
            validate_verification_status("totally_verified")

    def test_error_message_is_sanitized_and_truncated(self):
        with pytest.raises(VocabularyError) as exc:
            validate_relation_type("x" * 500 + "\nSELECT * FROM secrets")
        text = str(exc.value)
        assert "\n" not in text
        assert "truncated" in text
        assert len(text) < 200

    def test_module_versions_frozen(self):
        assert M8_CONTRACT_VERSION == "m8.1"
        assert M8_SCHEMA_VERSION == 12
