# Work Package: WP-03 — Performance and Long-Run Scaling

**ID:** WP-03

**Title:** Performance and Long-Run Scaling


**Status:** NOT STARTED

**Priority:** P1


**Categories:** PERFORMANCE, RELIABILITY

## Related Findings

F-003, F-008, F-010, F-014. Related ADRs: ADR-003 and ADR-005.

## Canonical Requirements

REQ-PERF-001 through REQ-PERF-007 and performance portions of REQ-STORE/REQ-RETR/REQ-API/REQ-OBS in `SPEC_TRACEABILITY.md`; canonical DOCX §§15–17 and 19.

## Read Scope

Read only the modules and benchmark fixtures named in **Files / Modules to Inspect**, plus the audit measurements.

## Planning Write Scope

V1.1.0 RE-PLANNING: documentation only — this work package, benchmark plans/results under `docs/v1.1.0/benchmarks/`, and `TRACEABILITY.md`. No executable benchmark changes are authorized.

## Planning Files Allowed to Modify

This work package, `TRACEABILITY.md`, and `docs/v1.1.0/benchmarks/**` Markdown only.

## Proposed Implementation Write Scope

**PROPOSED FOR A FUTURE AUTHORIZATION ONLY.** A maintainer may authorize only the minimum subset of the entries under **Files / Modules to Inspect**, plus directly associated tests and benchmarks required by this package's acceptance criteria. Every allowed path must be named explicitly when implementation is authorized; all other paths remain forbidden.

## Forbidden Scope

`zero_mem/`, `src/`, `tests/`, `benchmarks/`, migrations, schemas, dependency metadata, runtime configuration, CI, and git tags.

## Objective

Remove proven history-dependent hot-path work and establish measured startup, write, ingest, retrieval, and resource budgets for V1.1.0.

## Why This Exists

Audit measurements show capture load peak rising from 6.42 MiB at 1k records to 64.20 MiB at 10k, ingest rising from 0.408 s to 19.355 s, and FTS p95 rising from 1.648 ms to 22.198 ms. Current code rereads/materializes full JSONL and can materialize all corpus candidates.

## Current State on master

- `JsonlCaptureStore._load()` reads/parses all history and retains full records in two maps.
- `ingest_file()` calls `read_bytes()/split()` and `_iter_jsonl_lines()` rereads the file.
- `JsonlCaptureStore.append()` fsyncs every event.
- `_commit_outcome()` commits every ingested line.
- `retrieve_corpus()` fetches all matching/all fallback units before Python processing.
- `InjectionAdapter._make_service()` opens a read-only connection per memory-needed request.

## Evidence

F-003, F-008, F-010, F-014 and the audit benchmark data. Existing M3 200-record FTS p95 is about 0.79 ms, proving small-store speed but not long-run stability.

## Problems Found

- PERFORMANCE P1: startup/ingest work grows with all history.
- PERFORMANCE P1: corpus candidate work is not bounded by final result limits.
- PERFORMANCE P2: per-event fsync and per-line commits create burst overhead.
- PERFORMANCE P2: read connection churn occurs on pre-LLM paths.
- 100k/1M behavior: `Needs verification`.

## Affected Components

Capture, ingest, SQLite, corpus retrieval, injection, backup/rebuild/upgrade measurement.

## Files / Modules to Inspect

- [`src/storage/jsonl_capture.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/storage/jsonl_capture.py)
- [`src/storage/ingest.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/storage/ingest.py)
- [`src/storage/sqlite_store.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/storage/sqlite_store.py)
- [`src/corpus/retrieval.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/corpus/retrieval.py)
- [`src/integration/m7/injection_adapter.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/integration/m7/injection_adapter.py)
- [`benchmarks/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/benchmarks)

## Desired State

Normal startup is bounded by compact metadata rather than full payload history; incremental ingest streams only the unconsumed suffix; candidate processing is explicitly bounded; durability modes are measured; read sessions have explicit reuse/close ownership.

## Constraints

Do not weaken canonical durability, redaction, authorization-before-influence, deterministic ordering, or rebuildability to win benchmarks. No external cache/database dependency.

## Required Changes

1. Stream canonical ingest from checkpoint/byte offset without duplicate full reads.
2. Reduce capture startup retained state to compact IDs/hashes/offsets or segments.
3. Establish batch boundaries for derived commits; keep crash/replay semantics explicit.
4. Push bounded predicates/limits into retrieval where security semantics permit.
5. Define read-session ownership/reuse.
6. Add resource measurements for WAL, disk amplification, CPU, and peak RAM.

## Recommended Direction

Optimize one measured path at a time. First remove duplicate full reads, then introduce segmented/compact capture indexes, then benchmark commit batching and candidate bounds. Preserve a durable safe default.

## Alternatives Considered

- In-memory cache of all records: current approach; rejected for long-running scale.
- External vector/cache service: rejected as out of scope.
- Disable fsync globally: rejected without durability evidence.

## Risks

Offsets can be invalidated by tampering/truncation; batch commits alter crash windows; SQL pushdown must not let unauthorized data influence ranking.

## Compatibility Impact

Internal only if canonical format remains readable. New performance/durability configuration must follow WP-13/WP-17.

## Performance Impact

Primary package purpose. Every change requires before/after metrics and statistical sample disclosure.

## Migration Impact

Compact indexes must be derived and rebuildable from V1.0.0 JSONL. No mandatory canonical rewrite.

## Tests Required

### Existing Tests

M1 capture boundary/rate, M2 ingest/rebuild/checkpoint, M3 performance, M7 performance, M10 retrieval/rollout.

### Missing Tests

Large suffix-only ingest, restart with compact index, interrupted batch replay, connection lifecycle, WAL growth, and memory ceiling tests.

### Regression Tests

Ingest must not call full-file `read_bytes()` during a valid suffix resume; unauthorized corpus rows cannot affect scores/order.

## Benchmarks Required

For 1k/10k/100k/1M: startup wall time/peak RSS, single and burst writes, suffix ingest, FTS structured/corpus retrieval, replay/rebuild, DB/JSONL/WAL size. 100k and 1M: Benchmark required; do not set production claims until measured.

## Acceptance Criteria

- Normal incremental ingest reads only the unconsumed suffix plus bounded integrity metadata.
- Normal retrieval never scans canonical JSONL.
- Candidate materialization is bounded or emits a deterministic capability warning.
- 1k/10k metrics improve or remain within approved budgets with no invariant regression.
- 100k/1M results are recorded or marked `Needs verification` in release notes.
- Local sidecar, profile-mode unions/fallbacks, Obsidian projection/write-back, migration, startup, write, index rebuild, memory/disk, and context/token costs have measured baselines or explicit `benchmark required` plans.

## Security / Privacy, Observability, and Rollback

Performance changes cannot weaken durability, authorization, sensitivity, provenance, conflict visibility, or evidence budgets. Measurements expose stage/candidate/queue/resource counts without content. Every optimization is independently reversible and uses versioned derived indexes/configuration; rollback preserves canonical data.

## Exit Gate and Traceability

Exit requires reproducible 1k/10k results, 100k/1M measurement or honest disposition, no unexplained regression, bounded steady-state paths, and all mapped performance requirements `COVERED`.

## Definition of Done

- Changes implemented with regression tests.
- Benchmarks rerun against WP-00.
- Resource and durability tradeoffs documented.
- Relevant canonical, migration, and security tests pass.

## Dependencies

WP-00, WP-01, WP-02, WP-04 design approval.

## Blocks

WP-16 performance gates and WP-19.

## Out of Scope

Distributed scaling, mandatory embeddings, hardware-specific tuning, and unsupported benchmark marketing.
