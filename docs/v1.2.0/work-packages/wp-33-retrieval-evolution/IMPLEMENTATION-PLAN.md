# WP-33 Implementation Plan

**Status:** VERIFIED
**Baseline SHA:** `7d871a95017c250f2d27a6e284ccfc6ad6f3c02e`

## Current repository state

The repository has a read-only SQLite/FTS5 lexical baseline in `src/retrieval/query.py` and `src/retrieval/search.py`. It uses parameterized queries, deleted-record exclusion, deterministic `(created_at, event_id)` ordering, typed errors, and keyset cursors. `benchmarks/m10_benchmark.py` exists, but its suitability as the WP-33 labeled retrieval benchmark is not yet established.

## Gap analysis

- No WP-33 benchmark artifact/evidence is currently present.
- Retrieval quality metrics and labeled relevance judgments need a reproducible contract.
- Corpus scaling limits and available local resources must be measured, not assumed.
- Optional hybrid/vector value is unknown and must remain TBD until lexical measurements exist.

## Planned increments

1. Inspect existing benchmark utilities and retrieval fixtures; define the smallest labeled corpus/query schema.
2. Implement deterministic lexical baseline measurement with p50/p95 latency and precision/recall where labels exist.
3. Run feasible 1k/10k/100k/1M measurements; record limitations rather than fabricate unavailable scales.
4. Review failure modes and decide whether lexical-only is sufficient.
5. If and only if justified, design a reversible optional hybrid experiment with versioned model/index metadata; otherwise retain lexical baseline.

## Expected files

- `benchmarks/` WP-33 benchmark harness and fixture/artifact files as justified.
- `tests/` benchmark contract and deterministic retrieval regression tests.
- `docs/v1.2.0/work-packages/wp-33-retrieval-evolution/` evidence and decision records.
- Existing retrieval modules only if a measured correction is required.

## Compatibility and recovery

No canonical schema migration is planned. Any new index is derived, rebuildable, and optional. Lexical retrieval must continue to work when an optional index is missing, stale, or unavailable.

## Test strategy

Run benchmark unit/contract tests, authorization-negative tests, deterministic tie-order tests, stale-index behavior tests, targeted retrieval regression, and the isolated full suite. Record actual measurements and environment.

## Open decisions

- Benchmark labels/query set: TBD from existing fixtures and approved corpus availability.
- Whether hybrid/vector is needed: TBD until lexical measurements complete.
- Exact benchmark scales feasible on this host: TBD; report limitations honestly.

## Plan validation

Planning package created against the current verified WP-32 tree. No implementation begins until the benchmark schema and measurement boundary are concrete.
