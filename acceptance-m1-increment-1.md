# M1 Increment 1 Acceptance Evidence

**Increment:** Freeze the M1 event contract
**Status:** VERIFIED
**Scope boundary:** Contract definitions, normalization, deterministic validation, serialization/deserialization, supported/deferred registry, and contract tests only. No Hermes integration, redaction execution, persistence, retry, dead-letter, deduplication, retrieval, or injection implemented.
**Initial implementation commit:** `5b58b5caef92f042924cca5949861d3c98ef68b8`
**Evidence reconciliation commit:** `75025155bd08c668d508c02691fd0160717ea6d2`
**Canonical test evidence is bound to:** `75025155bd08c668d508c02691fd0160717ea6d2`
**Latest evidence reconciliation commit:** `43eb46be1e3bc1ec761c0023996bb87fcfeb561a`
**Current evidence-chain review commit:** `f159633a5079b8f67440835391b84a9510c75353`
**Rerun required:** No — changes after tested commit are documentation, planning, and state-record updates only; no source, tests, contracts, configuration, or executable state logic changed.
**Latest ad-hoc scope:** state and planning records only; not fresh canonical test evidence.
**Checkpoint:** `checkpoint-m1-increment-1-start` → `0194113675afe8e433bd1bcede1607e672fc0bcd`
**No-op patch incident:** attempted identical old/new patch for `src/capture/adapter.py`; product impact none; no file change required.

| Criterion | Status | Objective evidence |
|---|---|---|
| Valid minimal envelope | PASS | `tests/unit/test_m1_event_contract.py::test_valid_minimal_envelope`; included in focused run: `13 passed in 0.03s` |
| Valid complete envelope | PASS | `test_valid_complete_envelope`; focused run passed |
| Missing required field rejected | PASS | `test_missing_required_field_rejected`; focused run passed |
| Invalid event type rejected | PASS | `test_invalid_event_type_rejected`; focused run passed |
| Invalid timestamp rejected | PASS | `test_invalid_timestamp_rejected`; focused run passed |
| Invalid sensitivity/retention rejected | PASS | `test_invalid_policy_value_rejected`; focused run passed |
| Optional-field handling | PASS | `test_optional_fields_are_explicit_null_or_empty_tuple`; focused run passed |
| Deterministic serialization/deserialization | PASS | `test_deterministic_serialization_and_round_trip`; focused run passed |
| Original payload remains unchanged | PASS | `test_source_payload_is_not_mutated`; focused run passed |
| Assistant claim cannot become verified state implicitly | PASS | `test_assistant_claim_cannot_become_verified_state_implicitly`; focused run passed |
| Supported/deferred registry | PASS | `test_supported_and_deferred_event_class_registry`; focused run passed |
| Schema-version behavior | PASS | `test_schema_version_behavior`; focused run passed |

## Commands

Focused contract tests:

```text
.venv/bin/python -m pytest tests/unit/test_m1_event_contract.py -q
13 passed in 0.03s
```

Canonical repository suite:

```text
.venv/bin/python -m pytest tests/ -q
16 passed in 0.02s
```

No temporary verification files or test caches are retained after cleanup. The increment does not verify any full M1 capture acceptance criterion; those remain pending for later increments.
