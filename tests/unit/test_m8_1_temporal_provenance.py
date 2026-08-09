"""M8.1 focused tests — temporal, provenance, and graph/calibration contracts."""

from __future__ import annotations

import pytest

from src.m8.calibration_contract import (
    ALLOWED_FACTOR_NAMES,
    CALIBRATION_CONTRACT_VERSION,
    CalibrationContractError,
    CalibrationInput,
    CalibrationResult,
    describe_calibration_contract,
)
from src.m8.graph_contract import (
    GraphContractError,
    GraphEdge,
    GraphNode,
    EntityRecord,
    ResourceRef,
    ScopeMetadata,
)
from src.m8.provenance import (
    PROVENANCE_CONTRACT_VERSION,
    REQUIRED_PROVENANCE_FIELDS,
    Provenance,
    ProvenanceError,
    validate_provenance,
)
from src.m8.temporal_contract import (
    TemporalError,
    TemporalMetadata,
    build_temporal_metadata,
    normalize_timestamp,
)
from src.m8.vocabulary import VocabularyError


def _prov(**over) -> Provenance:
    base = dict(
        relation_source="m2_relation",
        source_ref="m2_relation:1",
        projection_version="m8.1",
    )
    base.update(over)
    return Provenance(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Temporal
# ---------------------------------------------------------------------------
class TestTemporalContract:
    def test_accepts_offset_aware_iso8601(self):
        ts = normalize_timestamp("created_at", "2026-01-02T03:04:05+00:00")
        assert ts is not None and ts.raw == "2026-01-02T03:04:05+00:00"

    def test_z_suffix_accepted_and_normalized(self):
        ts = normalize_timestamp("created_at", "2026-01-02T03:04:05Z")
        assert ts is not None
        assert ts.raw == "2026-01-02T03:04:05Z"      # canonical original preserved
        assert ts.utc == "2026-01-02T03:04:05+00:00"  # comparison form

    def test_offset_normalized_to_utc_but_raw_kept(self):
        ts = normalize_timestamp("effective_at", "2026-01-02T05:04:05+02:00")
        assert ts is not None
        assert ts.utc == "2026-01-02T03:04:05+00:00"
        assert ts.raw == "2026-01-02T05:04:05+02:00"

    def test_none_stays_none(self):
        assert normalize_timestamp("valid_from", None) is None

    @pytest.mark.parametrize("bad", [
        "2026-01-02T03:04:05",       # timezone-naive
        "2026-01-02",                # date only, naive
        "not-a-timestamp",
        "",
        " 2026-01-02T03:04:05Z",     # leading whitespace
        "2026-13-45T99:99:99Z",      # impossible components
    ])
    def test_malformed_rejected(self, bad):
        with pytest.raises(TemporalError):
            normalize_timestamp("created_at", bad)

    def test_non_string_rejected(self):
        with pytest.raises(TemporalError):
            normalize_timestamp("created_at", 1767322445)  # type: ignore[arg-type]

    def test_absent_dimensions_are_not_invented(self):
        meta = build_temporal_metadata(created_at="2026-01-02T03:04:05Z")
        assert meta.has_transaction_time is True
        assert meta.has_valid_time is False
        # created_at must NOT be copied into a validity dimension.
        assert meta.valid_from is None
        assert meta.valid_until is None
        assert meta.effective_at is None

    def test_valid_time_detected_only_from_explicit_fields(self):
        assert build_temporal_metadata(effective_at="2026-01-02T00:00:00Z").has_valid_time
        assert build_temporal_metadata(valid_from="2026-01-02T00:00:00Z").has_valid_time
        assert not build_temporal_metadata(observed_at="2026-01-02T00:00:00Z").has_valid_time

    def test_inverted_interval_rejected(self):
        with pytest.raises(TemporalError):
            build_temporal_metadata(
                valid_from="2026-05-01T00:00:00Z", valid_until="2026-01-01T00:00:00Z"
            )

    def test_equal_bounds_allowed(self):
        meta = build_temporal_metadata(
            valid_from="2026-05-01T00:00:00Z", valid_until="2026-05-01T00:00:00Z"
        )
        assert meta.has_valid_time

    def test_serialization_is_deterministic(self):
        a = build_temporal_metadata(created_at="2026-01-02T03:04:05Z").to_dict()
        b = build_temporal_metadata(created_at="2026-01-02T03:04:05Z").to_dict()
        assert a == b

    def test_no_recency_ordering_helper_exists(self):
        # "latest timestamp wins" must not exist as M8 authority semantics.
        import src.m8.temporal_contract as mod
        for banned in ("latest", "is_newer", "newest", "pick_winner", "rank", "sort_by_time"):
            assert not hasattr(mod, banned)

    def test_ingested_at_is_diagnostic_not_validity(self):
        meta = build_temporal_metadata(ingested_at="2026-01-02T03:04:05Z")
        assert meta.has_valid_time is False
        assert meta.has_transaction_time is False


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------
class TestProvenanceContract:
    def test_required_fields_frozen(self):
        assert REQUIRED_PROVENANCE_FIELDS == (
            "relation_source", "source_ref", "projection_version", "identity_version",
        )
        assert PROVENANCE_CONTRACT_VERSION == "v1"

    def test_valid_provenance_round_trips(self):
        p = _prov(profile_id="PR1", project_id="P1", knowledge_space_id="KS1")
        assert validate_provenance(p) is p
        payload = p.to_dict()
        for f in REQUIRED_PROVENANCE_FIELDS:
            assert payload[f]

    def test_missing_source_ref_rejected(self):
        with pytest.raises(ProvenanceError):
            _prov(source_ref="")

    def test_missing_projection_version_rejected(self):
        with pytest.raises(ProvenanceError):
            _prov(projection_version="   ")

    def test_unknown_relation_source_rejected(self):
        with pytest.raises(VocabularyError):
            _prov(relation_source="llm_extraction")

    def test_empty_optional_rejected_not_coerced(self):
        with pytest.raises(ProvenanceError):
            _prov(trace_id="")

    def test_absent_optional_stays_none(self):
        p = _prov()
        assert p.trace_id is None
        assert p.source_event_id is None
        assert p.to_dict()["trace_id"] is None

    def test_scope_keys_always_present_even_when_none(self):
        payload = _prov().to_dict()
        for f in ("profile_id", "project_id", "knowledge_space_id"):
            assert f in payload and payload[f] is None

    def test_serialization_and_hash_deterministic(self):
        a, b = _prov(project_id="P1"), _prov(project_id="P1")
        assert a.to_canonical_json() == b.to_canonical_json()
        assert a.compute_hash() == b.compute_hash()

    def test_scope_change_changes_hash(self):
        assert _prov(project_id="P1").compute_hash() != _prov(project_id="P2").compute_hash()

    def test_non_provenance_object_rejected(self):
        with pytest.raises(ProvenanceError):
            validate_provenance({"relation_source": "m2_relation"})  # type: ignore[arg-type]

    def test_immutable(self):
        p = _prov()
        with pytest.raises(Exception):
            p.source_ref = "tampered"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Graph contracts
# ---------------------------------------------------------------------------
def _edge(**over) -> GraphEdge:
    base = dict(
        from_ref=ResourceRef(resource_type="event", resource_id="E1"),
        relation_type="derived_from",
        to_ref=ResourceRef(resource_type="event", resource_id="E2"),
        scope=ScopeMetadata(profile_id="PR1", project_id="P1"),
        lifecycle_status="candidate",
        provenance=_prov(profile_id="PR1", project_id="P1"),
    )
    base.update(over)
    return GraphEdge(**base)  # type: ignore[arg-type]


class TestGraphContracts:
    def test_resource_ref_requires_valid_type(self):
        with pytest.raises(VocabularyError):
            ResourceRef(resource_type="node", resource_id="X")
        with pytest.raises(VocabularyError):
            ResourceRef(resource_type="", resource_id="X")

    def test_resource_ref_requires_id(self):
        with pytest.raises(GraphContractError):
            ResourceRef(resource_type="event", resource_id="  ")

    def test_edge_is_deterministic_and_serializable(self):
        a, b = _edge(), _edge()
        assert a.edge_id == b.edge_id
        assert a.to_canonical_json() == b.to_canonical_json()
        assert a.compute_content_hash() == b.compute_content_hash()

    def test_edge_rejects_unknown_relation(self):
        with pytest.raises(VocabularyError):
            _edge(relation_type="owns")

    def test_edge_rejects_invalid_lifecycle(self):
        with pytest.raises(VocabularyError):
            _edge(lifecycle_status="revoked")

    def test_edge_requires_valid_provenance(self):
        with pytest.raises(ProvenanceError):
            _edge(provenance={"source_ref": "x"})

    def test_resource_type_retained_in_payload(self):
        payload = _edge(
            to_ref=ResourceRef(resource_type="artifact", resource_id="A1")
        ).to_dict()
        assert payload["from"]["resource_type"] == "event"
        assert payload["to"]["resource_type"] == "artifact"

    def test_scope_retained_in_payload(self):
        payload = _edge().to_dict()
        assert payload["scope"] == {
            "profile_id": "PR1", "project_id": "P1", "knowledge_space_id": None,
        }

    def test_authorization_metadata_is_per_endpoint_and_decisionless(self):
        meta = _edge(
            to_ref=ResourceRef(resource_type="artifact", resource_id="A1")
        ).authorization_metadata()
        assert set(meta) == {"edge", "from", "to"}
        # Endpoints are described independently so no decision can be inherited.
        assert meta["from"]["resource_type"] == "event"
        assert meta["to"]["resource_type"] == "artifact"
        # No allow/deny/grant field may exist anywhere in the descriptor.
        flat = str(meta)
        for banned in ("allow", "denied", "granted", "authorized", "permission"):
            assert banned not in flat

    def test_edge_does_not_upgrade_verification(self):
        assert _edge().verification_status is None
        assert _edge().to_dict()["verification_status"] is None

    def test_edge_carries_verification_through_unchanged(self):
        assert _edge(verification_status="approval").verification_status == "approval"

    def test_graph_module_exposes_no_traversal_or_centrality(self):
        import src.m8.graph_contract as mod
        for banned in (
            "traverse", "neighbors", "neighbours", "degree", "centrality",
            "rank", "walk", "bfs", "dfs", "shortest_path", "page_rank",
        ):
            assert not hasattr(mod, banned)

    def test_node_key_is_typed(self):
        node = GraphNode(
            ref=ResourceRef(resource_type="artifact", resource_id="A1"),
            scope=ScopeMetadata(project_id="P1"),
            lifecycle_status="active",
            provenance=_prov(project_id="P1"),
        )
        assert node.node_key == ("artifact", "A1")

    def test_same_id_different_type_are_distinct_nodes(self):
        common = dict(
            scope=ScopeMetadata(project_id="P1"),
            lifecycle_status="active",
            provenance=_prov(project_id="P1"),
        )
        a = GraphNode(ref=ResourceRef(resource_type="event", resource_id="X1"), **common)  # type: ignore[arg-type]
        b = GraphNode(ref=ResourceRef(resource_type="artifact", resource_id="X1"), **common)  # type: ignore[arg-type]
        assert a.node_key != b.node_key
        assert a.compute_content_hash() != b.compute_content_hash()

    def test_entity_record_identity_deterministic(self):
        def make():
            return EntityRecord(
                entity_type="person",
                canonical_name="Ada Lovelace",
                scope=ScopeMetadata(project_id="P1"),
                lifecycle_status="candidate",
                provenance=_prov(project_id="P1"),
            )
        assert make().entity_id == make().entity_id

    def test_entity_record_rejects_unknown_type(self):
        with pytest.raises(VocabularyError):
            EntityRecord(
                entity_type="alien",
                canonical_name="X",
                scope=ScopeMetadata(),
                lifecycle_status="candidate",
                provenance=_prov(),
            )


# ---------------------------------------------------------------------------
# Calibration contract (structure only — no scoring in M8.1)
# ---------------------------------------------------------------------------
class TestCalibrationContract:
    def _input(self, **over) -> CalibrationInput:
        base = dict(
            candidate_resource_type="decision",
            candidate_resource_id="D1",
            lifecycle_status="active",
        )
        base.update(over)
        return CalibrationInput(**base)  # type: ignore[arg-type]

    def test_input_deterministic_fingerprint(self):
        assert self._input().compute_fingerprint() == self._input().compute_fingerprint()

    def test_input_fingerprint_changes_with_input(self):
        assert self._input().compute_fingerprint() != (
            self._input(has_conflict=True).compute_fingerprint()
        )

    def test_input_has_no_authorization_field(self):
        payload = self._input().to_dict()
        for banned in (
            "requesting_profile_id", "grant", "grant_id", "authorized",
            "allow", "permission", "scope_grant",
        ):
            assert banned not in payload

    def test_input_rejects_bad_resource_type(self):
        with pytest.raises(VocabularyError):
            self._input(candidate_resource_type="graph_node")

    def test_input_rejects_bad_lifecycle(self):
        with pytest.raises(VocabularyError):
            self._input(lifecycle_status="promoted")

    def test_input_rejects_non_boolean_flags(self):
        with pytest.raises(CalibrationContractError):
            self._input(has_conflict="yes")

    def test_result_score_must_be_bounded(self):
        for bad in (-0.01, 1.01, 42):
            with pytest.raises(CalibrationContractError):
                CalibrationResult(
                    candidate_resource_type="decision",
                    candidate_resource_id="D1",
                    score=bad,
                )

    def test_result_score_not_clamped_silently(self):
        # Out-of-range must RAISE, not clamp — clamping would mask a bad factor.
        with pytest.raises(CalibrationContractError):
            CalibrationResult(
                candidate_resource_type="decision", candidate_resource_id="D1", score=5.0
            )

    def test_result_rejects_unknown_factor(self):
        with pytest.raises(CalibrationContractError):
            CalibrationResult(
                candidate_resource_type="decision",
                candidate_resource_id="D1",
                score=0.5,
                factor_values={"node_degree": 0.9},
            )

    def test_no_centrality_or_recency_factor_allowed(self):
        for banned in ("node_degree", "centrality", "recency", "link_count", "repetition"):
            assert banned not in ALLOWED_FACTOR_NAMES

    def test_result_rejects_unknown_reason_code(self):
        with pytest.raises(CalibrationContractError):
            CalibrationResult(
                candidate_resource_type="decision",
                candidate_resource_id="D1",
                score=0.5,
                reason_codes=("BECAUSE_I_SAID_SO",),
            )

    def test_result_serialization_deterministic(self):
        def make():
            return CalibrationResult(
                candidate_resource_type="decision",
                candidate_resource_id="D1",
                score=0.5,
                factor_values={"scope_priority": 0.2, "retrieval_match": 0.8},
                reason_codes=("VERIFIED_SOURCE",),
                lifecycle_status="active",
            )
        assert make().to_canonical_json() == make().to_canonical_json()

    def test_result_echoes_verification_without_changing_it(self):
        r = CalibrationResult(
            candidate_resource_type="decision",
            candidate_resource_id="D1",
            score=1.0,
            verification_status=None,
            lifecycle_status="candidate",
        )
        # Maximum score must not imply verification or lifecycle promotion.
        assert r.verification_status is None
        assert r.lifecycle_status == "candidate"

    def test_contract_declares_it_is_not_authority(self):
        d = describe_calibration_contract()
        assert d["scoring_implemented"] is False
        assert d["grants_authorization"] is False
        assert d["performs_verification"] is False
        assert d["resolves_conflicts"] is False
        assert d["overrides_lifecycle"] is False
        assert d["calibration_contract_version"] == CALIBRATION_CONTRACT_VERSION

    def test_no_scoring_function_exists_in_m8_1(self):
        import src.m8.calibration_contract as mod
        for banned in ("calibrate", "compute_score", "score_candidates", "rank", "sort"):
            assert not hasattr(mod, banned)
