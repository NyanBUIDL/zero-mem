# WP-12 Closure Evidence

## Mode policy

- Isolated profiles: supported by separate canonical roots and explicit immutable runtime handles.
- Shared local profile: supported through an advisory OS process lock adjacent to canonical JSONL; writers serialize before duplicate/sequence evaluation.
- Native Windows and network-filesystem guarantees: not supported by the approved WP-09 v1.1.0 matrix.
- Readers use the existing derived-index freshness model; canonical JSONL remains authoritative.

## Production changes

`JsonlCaptureStore` now uses a per-stream `fcntl.flock` lock, refreshes only newly appended records while holding it, and preserves append-only JSONL as canonical state. `new_runtime()` provides immutable explicit runtime handles without global mutation. Legacy process-local configuration remains compatibility-only.

## Verification

- Two-process shared writer test: PASS; 100 records, unique IDs, contiguous sequences.
- Four-process 10,000-operation stress benchmark: PASS; 10,000 records, all workers exit zero, 3.197091s.
- Isolated profile and immutable runtime tests: PASS.
- Storage/regression tests: `49 passed`.
- `git diff --check`: pass.

## Risk boundary

Cross-host distributed coordination, network filesystems, and native Windows are explicitly outside v1.1.0. Lock wait and write time are not yet separately exposed in telemetry; this remains a later observability obligation.

## Decision

`PASS — WP-12 VERIFIED`
