# WP-33 Technical Design

**Status:** VERIFIED

## Baseline technology

- Python 3.11 project environment and pytest.
- SQLite FTS5 read-only lexical retrieval.
- Existing typed retrieval contracts and keyset cursor.
- Standard-library benchmark timing/aggregation unless an existing project utility is sufficient.

## Measurement model

For each labeled query `q`, execute the same authorized query against a fixed corpus snapshot and record:

- retrieved IDs and deterministic order;
- relevant-ID set;
- precision@k and recall@k for approved k values;
- p50/p95 latency over repeated warm/cold runs where feasible;
- corpus size, index state, Python/platform, and benchmark version.

No score is reported without labels and reproducible inputs.

## Candidate pipeline

`identity/grant scope -> authorized candidate predicate -> lexical candidate discovery -> deterministic ranking/tie-break -> optional context handoff`.

If a hybrid experiment is justified: lexical and dense candidates are each scope-authorized before fusion; fusion and weights are versioned, deterministic, and server-governed. Missing/stale dense state returns a typed derived-state result or documented lexical fallback.

## Data structures

Benchmark records contain query ID, corpus snapshot ID, authorized scope, expected relevant IDs, observed IDs, metric values, timing samples, retrieval version, and environment metadata. Credentials and raw secrets are prohibited.

## Dependencies and storage

No new dependency or storage engine is approved by this plan. Any future embedding/index dependency requires a separate recorded decision covering license, model hash, storage, rebuild, latency, security, and removal path.

## Ordering and complexity

The lexical baseline retains `(created_at ASC, event_id ASC)` tie ordering and keyset pagination. Benchmark aggregation is O(number of query runs × k); raw benchmark artifacts remain disposable evidence, not canonical memory.

## Failure behavior

Malformed queries, unavailable FTS, stale/missing optional indexes, and invalid benchmark inputs remain typed/explicit. No infinite retry and no silent fallback that changes semantics.

## Prohibited approaches

- benchmark after authorization filtering;
- retrieve-all then filter;
- unbounded candidate/context injection;
- vector dependency before measurement;
- arbitrary ranking weights;
- derived index becoming canonical truth.

## Open decisions

Benchmark labels, scales, and any hybrid/vector choice are TBD until repository fixtures and local measurements resolve them.
