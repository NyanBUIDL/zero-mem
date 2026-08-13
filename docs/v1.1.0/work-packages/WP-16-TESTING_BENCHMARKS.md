# Work Package: WP-16 — Testing, Validation, and Benchmarks

**ID:** WP-16

**Title:** Testing, Validation, and Benchmarks


**Status:** NOT STARTED

**Priority:** P1

**Categories:** Quality, Testing, Performance Validation

## Related Findings

F-001 through F-014. Related ADRs: ADR-001 through ADR-005.

## Read Scope

Read only test, benchmark, packaging metadata, fixture, and module scopes named in **Files / Modules to Inspect**, plus linked acceptance criteria from every dependent WP.

## Planning Write Scope

V1.1.0 RE-PLANNING: documentation only — this work package, benchmark plans/results under `docs/v1.1.0/benchmarks/`, and `TRACEABILITY.md`. No test, fixture, benchmark script, CI, or release-artifact write scope exists.

## Planning Files Allowed to Modify

This work package, `TRACEABILITY.md`, and Markdown plans/results under `docs/v1.1.0/benchmarks/` only.

## Proposed Implementation Write Scope

**PROPOSED FOR A FUTURE AUTHORIZATION ONLY.** A maintainer may authorize only the minimum subset of the entries under **Files / Modules to Inspect**, plus directly associated tests and benchmarks required by this package's acceptance criteria. Every allowed path must be named explicitly when implementation is authorized; all other paths remain forbidden.

## Forbidden Scope

`zero_mem/`, `src/`, `tests/`, `benchmarks/`, `packaging/`, migrations, schemas, dependency metadata, runtime configuration, CI, and git tags.

## Objective

Provide one evidence-producing quality system that verifies correctness, compatibility, reliability, privacy, and performance for the v1.1.0 release candidate.

## Why This Exists

The repository has a large test suite, but the audited noncanonical Windows/Python 3.14 run produced 59 failures and 11 errors, and no CI workflow was established in the audited tree. Performance probes also show nonlinear costs as the corpus grows. V1.1.0 needs release gates tied to supported environments and reproducible fixtures.

## Current State on master

- [`tests/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/tests) contains extensive unit and integration coverage.
- Existing M3 synthetic retrieval tests cover 200 records.
- No committed release matrix or centralized benchmark gate was confirmed.
- Current performance-sensitive operations include JSONL load, ingest, FTS retrieval, structured retrieval, context assembly, setup, and doctor.

## Evidence

- Full audit run: **3,068 passed, 59 failed, 11 errors, 5 skipped** in **74.05 s** on unsupported Windows/CPython 3.14.
- Existing 200-record synthetic benchmark: FTS p95 about **0.79 ms**, structured retrieval below about **0.52 ms**.
- Audit probes:

| Records | Capture load | Peak memory | Ingest | FTS p95 |
|---:|---:|---:|---:|---:|
| 1,000 | 52.25 ms | 6.42 MiB | 0.408 s | 1.648 ms |
| 5,000 | 274.10 ms | 32.08 MiB | 2.982 s | 11.796 ms |
| 10,000 | 1,237.77 ms | 64.20 MiB | 19.355 s | 22.198 ms |

- Supported-platform reproducibility and variance are **Needs verification**.

## Problems Found

- **F-003 — P1 — Scalability:** full-file loading/materialization grows memory and latency.
- **F-008 — P1 — Retrieval scalability:** broad fetch precedes Python authorization/filter/ranking.
- **F-010 — P2 — Write throughput:** per-record durability/transaction costs compound.
- **F-005 — P1 — Matrix coverage:** unsupported-platform failures are not separated from canonical release evidence.
- Cross-package acceptance criteria need one enforcing owner and artifact format.

## Affected Components

- Entire package and integrations
- Supported-platform CI
- Fixture and corpus generation
- Fault injection and migration validation
- Performance and memory measurement
- Release artifact qualification

## Files / Modules to Inspect

- [`tests/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/tests)
- [`pyproject.toml`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/pyproject.toml)
- Benchmark scripts/fixtures to be added under a documented test location
- All modules referenced by WP-00 through WP-15

## Desired State

- Deterministic unit, integration, lifecycle, fault-injection, compatibility, migration, and benchmark suites.
- The exact built wheel is tested in every supported environment.
- Benchmarks cover 200, 1k, 5k, 10k, and a release-approved large corpus.
- Performance gates compare against an approved v1.0.0 baseline on equivalent hardware/runtime.
- Results include latency distributions, throughput, memory, I/O, and variance.
- Every F-001–F-014 finding has at least one regression test or an explicit non-testable rationale.

## Constraints

- The audited Windows/Python 3.14 run cannot serve as the supported baseline.
- Absolute timing thresholds require controlled runners; otherwise relative thresholds and repeated samples are required.
- Test fixtures must contain synthetic, non-sensitive content.
- Benchmarks must not silently skip unavailable FTS or optional integrations.

## Required Changes

1. Establish the supported CI matrix from WP-09.
2. Define test layers, markers, fixtures, ownership, and artifact retention.
3. Add regression tests for every audit finding.
4. Add lifecycle tests against the exact wheel.
5. Add reproducible benchmark harnesses and v1.0.0/v1.1.0 comparisons.
6. Add memory, file-descriptor/handle, thread/task, and database-connection leak checks.
7. Add fault injection and migration fixture validation.
8. Define flake policy, retry policy, and release-blocking thresholds.

## Recommended Direction

Use fast unit tests on each change, supported-matrix integration tests for merges, and full lifecycle/fault/benchmark suites for release candidates. Store raw machine-readable results plus a summarized comparison. Set numeric regression budgets only after repeating baselines on controlled supported runners; until then those budgets are **Needs verification**.

## Alternatives Considered

- **Use the existing suite only:** misses release artifact, matrix, scale, and fault semantics.
- **Use absolute microbenchmark thresholds everywhere:** brittle across shared runners and platforms.
- **Manual release testing:** non-repeatable and insufficient for 20 dependent work packages.

## Risks

- Noisy hardware can create false performance regressions.
- Large fixtures can make routine CI too slow.
- Retrying flaky tests can hide deterministic race conditions.
- Benchmark optimizations can accidentally weaken correctness or durability.

## Compatibility Impact

The test matrix defines which environments are release-blocking. Best-effort environments may be reported separately but cannot substitute for supported rows.

## Performance Impact

This package sets the release performance contract. At minimum, v1.1.0 must eliminate full-corpus work from steady-state capture/retrieval paths and show bounded memory at increasing corpus sizes. Final numeric budgets require baseline approval.

## Migration Impact

Migration tests must preserve source fixtures, compare logical records before/after, verify schema/config versions, and execute rollback with the v1.0.0 reader where applicable.

## Tests Required

### Existing Tests

- All tests currently under [`tests/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/tests), inventoried by component and marker.

### Missing Tests

- One or more targeted regressions for F-001 through F-014.
- Exact-wheel clean install/upgrade/uninstall.
- Supported OS/Python/SQLite capability matrix.
- Multi-process, async cancellation, fault injection, and recovery.
- Large-corpus bounded-memory and incremental-ingest behavior.
- Status privacy/redaction and resource leak tests.

### Regression Tests

- Full v1.0.0 behavior inventory from WP-00.
- Public API contract snapshots and deprecation behavior.
- Retrieval relevance/authorization ordering.
- Hermes optionality and generic adapter conformance.

## Benchmarks Required

- Capture append throughput and p50/p95/p99 latency.
- Incremental ingest and full rebuild throughput.
- FTS and structured retrieval p50/p95/p99 with candidate counts.
- Context token/input/output ratios from WP-06.
- Setup, doctor, status, migration, backup, and rollback duration.
- Peak RSS/allocated memory, file handles, connections, threads, and tasks.
- Contention tests for supported multi-agent modes.

## Acceptance Criteria

- All supported matrix rows pass the exact-wheel release suite with **0 failures and 0 unexpected errors**.
- Every audit finding F-001–F-014 maps to a passing regression test or approved non-testable rationale in MASTER_PLAN traceability.
- Benchmark runs use at least five measured repetitions after warm-up and publish raw results, environment metadata, median, p95 where meaningful, and variance.
- No release benchmark shows an unexplained regression beyond the approved budget.
- Capture/retrieval steady-state memory does not scale by materializing the entire canonical corpus; proof includes memory profiles at 1k, 5k, and 10k records.
- Test retries are not used to turn a deterministic failure into a pass.

## Definition of Done

- CI, fixtures, test markers, and benchmark harnesses are documented and reproducible.
- All upstream work-package acceptance tests pass.
- Raw artifacts and a signed-off summary are linked from WP-19.
- Remaining skips/xfailed tests have owner, reason, and expiration or release acceptance.

## Dependencies

- WP-00 Baseline
- WP-03 Performance
- WP-04 Storage
- WP-05 Retrieval
- WP-06 Context Efficiency
- WP-07 Hermes Integration
- WP-08 Agent-Agnostic API
- WP-09 Compatibility and Portability
- WP-10 Installation and Packaging
- WP-11 Sync and Async Execution
- WP-12 Multi-Agent Operation
- WP-13 Configuration
- WP-14 Reliability and Recovery
- WP-15 Observability
- WP-17 Migration for final migration suite

## Blocks

- WP-19 Release Readiness

## Out of Scope

- Production-user data in test fixtures
- Performance claims from incomparable hardware without normalization
- Treating unsupported runtime results as canonical release evidence
- Hiding failures through unconditional retries
