# WP-32 Implementation Plan

**Status:** VERIFIED
**Baseline SHA:** `7d871a95017c250f2d27a6e284ccfc6ad6f3c02e`

## Current repository state

WP-29 authorization and WP-31 Hermes are verified. Existing M7 modules provide typed `EvidenceSet`, authorization-first evidence construction, deterministic budget selection, provenance-bearing `EvidenceItem`, DATA-only envelope serialization, and the Hermes pre-LLM adapter. `src/m8` provides temporal/provenance/calibration metadata. No dedicated WP-32 package or context assembler exists yet.

## Gap analysis

- Existing M7 budget ordering is deterministic but is a pre-existing M7 contract and must be evaluated before extension.
- Existing envelope serialization preserves many provenance fields but WP-32 needs explicit freshness semantics and end-to-end budget assertions.
- Existing injection consumes serialized evidence; WP-32 must prove no canonical transcript mutation and no stale substitution for external-current requests.
- Existing authorization must remain the sole candidate-discovery boundary.

## Planned increments

1. Freeze the WP-32 context contract and test fixtures: authorized evidence, freshness states, provenance, conflicts, and governed budgets.
2. Add the smallest context assembly/packing behavior needed to enforce deterministic order, freshness gates, provenance retention, and bounded output.
3. Integrate through the existing M7/Hermes DATA-only boundary without changing Hermes core or authorization.
4. Add failure/security/restart/regression tests and independent review.

## Expected files

- `src/integration/m7/` context helper or bounded extension, only if existing contracts cannot satisfy the gate;
- `tests/unit/test_wp32_context.py`;
- WP-32 planning/evidence documentation;
- `project-state.yaml` and WP index after acceptance only.

## Contracts and compatibility

Reuse `EvidenceSet`, `EvidenceItem`, `MemoryRoute`, `AuthorizedReadService`, and `serialize_evidence_set`. Preserve v1.1/v1.2 existing caller behavior. Client-controlled values cannot increase server/governed limits. No schema migration is expected.

## Security/provenance/recovery impact

Authorization remains before candidate discovery. Unauthorized items must not affect ordering, counts, omitted metadata, or output. Provenance, source, trace, lifecycle, verification, and freshness metadata remain attached to selected evidence. Context assembly is derived/read-only and rebuildable; it must not mutate JSONL, SQLite, or transcript state.

## Rollback

Revert only WP-32-owned helper/tests/docs changes. No canonical data migration or destructive operation is planned.

## Test strategy

- RED/GREEN tests for deterministic ordering and tie-breaks;
- budget overflow, zero/negative/oversized limits, UTF-8/code-point safety;
- external-current no-stale-memory behavior;
- provenance/freshness preservation and conflict visibility;
- unauthorized omission non-leakage;
- envelope injection-safety and payload non-mutation;
- Hermes restart and isolated full regression.

## Open questions

- Freshness is grounded in existing M8 `TemporalDimension` (`transaction` / `valid`), explicit `as_of`, and temporal metadata fields (`created_at`, `observed_at`, `effective_at`, `valid_from`, `valid_until`). Unknown stays unknown; no wall-clock or invented timestamp is allowed.
- Existing M8 temporal statuses `TEMPORAL_VALID`, `TEMPORAL_UNKNOWN`, and `TEMPORAL_INVALID` are the freshness basis; WP-32 must not invent a parallel vocabulary.
- Existing M7 budget/envelope code already satisfies part of the contract, but WP-32 must prove the remaining end-to-end freshness/provenance and budget behavior with tests before adding a new abstraction.
- Any new token estimator or dependency is NOT APPROVED; prefer existing deterministic estimator/standard library.

## Plan validation

Validated against AGENTS.md, the unified specification, approved Spec Amendment 001, ADR-009, the v1.2 Master Plan Phase 5 context-budget requirements, and verified WP-29/WP-31 repository state. Implementation must begin only after these open questions are resolved by repository evidence.
