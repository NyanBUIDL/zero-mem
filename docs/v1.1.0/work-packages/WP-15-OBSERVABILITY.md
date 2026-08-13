# Work Package: WP-15 — Observability and Diagnostics

**ID:** WP-15

**Title:** Observability and Diagnostics


**Status:** NOT STARTED

**Priority:** P2

**Categories:** Observability, Diagnostics, Operations

## Related Findings

F-001, F-002, F-013, F-014. Related ADRs: ADR-003 and ADR-004.

## Read Scope

Read only doctor, capture, ingestion, storage, injection adapter, and proposed public status/API material named in **Files / Modules to Inspect**.

## Planning Write Scope

V1.1.0 RE-PLANNING: documentation only — this work package, diagnostics/runbook drafts under `docs/`, and `TRACEABILITY.md`. No logging, telemetry, CLI, or status implementation write scope exists.

## Planning Files Allowed to Modify

This work package, diagnostics/runbook Markdown under `docs/`, and `TRACEABILITY.md` only.

## Proposed Implementation Write Scope

**PROPOSED FOR A FUTURE AUTHORIZATION ONLY.** A maintainer may authorize only the minimum subset of the entries under **Files / Modules to Inspect**, plus directly associated tests and benchmarks required by this package's acceptance criteria. Every allowed path must be named explicitly when implementation is authorized; all other paths remain forbidden.

## Forbidden Scope

`zero_mem/`, `src/`, `tests/`, migrations, schemas, dependency metadata, runtime configuration, CI, and git tags.

## Objective

Expose privacy-safe, actionable health, freshness, performance, and failure signals for local operators and agent integrations.

## Why This Exists

The existing doctor does not adequately expose capture failure or canonical-to-derived lag. Without watermarks, resource lifecycle signals, and stable status output, users cannot distinguish “no relevant memory” from “capture disabled,” “ingestion stale,” “database locked,” or “retrieval failed.”

## Current State on master

- [`zero_mem/commands_doctor.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/commands_doctor.py) performs a set of setup/environment checks.
- Runtime operations have logs/errors, but no documented metrics/status schema spans capture, ingestion, retrieval, and adapters.
- The injection adapter’s per-call connection behavior is not surfaced.
- Canonical and derived progress are not reported as one freshness state.

## Evidence

- **F-001:** missing capture store can be silent.
- **F-002:** no explicit canonical/derived freshness lifecycle.
- **F-013:** doctor does not diagnose lag and capture failure sufficiently.
- **F-014:** repeated read-only connection lifecycle lacks explicit closure and visibility.
- Existing diagnostic payload-redaction coverage is **Needs verification**.

## Problems Found

- **F-013 — P2 — Diagnostics:** status cannot reliably explain stale or absent memories.
- **F-001 — P1 — Readiness:** an integration can appear active without persistence.
- **F-002 — P1 — Freshness:** ingestion lag has no durable, user-visible measure.
- **F-014 — P2 — Resources:** connection creation and closure are not observable.

## Affected Components

- Doctor and status API/CLI
- Capture and ingestion
- Retrieval/context assembly
- Runtime lifecycle and queues
- Configuration and integrations
- Test and release evidence

## Files / Modules to Inspect

- [`zero_mem/commands_doctor.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/commands_doctor.py)
- [`src/storage/jsonl_capture.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/storage/jsonl_capture.py)
- [`src/storage/ingest.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/storage/ingest.py)
- [`src/storage/sqlite_store.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/storage/sqlite_store.py)
- [`src/integration/m7/injection_adapter.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/integration/m7/injection_adapter.py)
- Public API/status modules defined by WP-08

## Desired State

- A stable health schema reports readiness, canonical/derived watermarks, lag, last success/failure, schema/version, lock mode, queue saturation, and resource counts.
- Retrieval diagnostics separate candidate fetch, authorization/filtering, ranking, and context assembly latency.
- Health output is useful in human-readable and machine-readable forms.
- No memory payload, prompt, secret, or sensitive metadata is logged by default.
- Diagnostic cardinality is bounded by documented dimensions.

## Constraints

- Zero-Mem is local-first; remote telemetry is opt-in and not required.
- Status collection must not perform full-corpus reads.
- Record identifiers can be sensitive and must not be emitted by default.
- Metrics must not materially alter durability or retrieval behavior.

## Required Changes

1. Define health states and a versioned status schema.
2. Expose capture readiness and last canonical append outcome.
3. Expose derived watermark, lag, rebuild state, and last ingest error.
4. Add bounded timing/counter instrumentation for retrieval and context assembly.
5. Add runtime/connection/worker lifecycle counters.
6. Add redaction, cardinality, and diagnostic-overhead tests.
7. Extend doctor with actionable remediation and exit codes.

## Recommended Direction

Implement in-process counters and structured status snapshots first. Keep logs event-oriented and status state-oriented. Provide JSON output for automation plus concise text for users, with stable error codes linked to WP-14 runbooks.

## Alternatives Considered

- **Logs only:** easy to add but difficult to query reliably and prone to payload leakage.
- **Mandatory external telemetry:** conflicts with local-first operation and privacy expectations.
- **Full record-level tracing:** high cardinality and unacceptable content exposure by default.

## Risks

- Instrumentation can leak prompts or memory content.
- Unbounded labels can consume memory over long runtimes.
- Health checks can become expensive or lock-contending.
- “Healthy” can be misleading if freshness thresholds are not explicit.

## Compatibility Impact

Doctor output and exit codes may change. Machine consumers must use the versioned JSON schema; human text is not a stable parsing interface.

## Performance Impact

Steady-state instrumentation must use bounded memory and constant-time updates. WP-16 sets the allowed latency/throughput regression after baseline measurement; status reads must not scan canonical JSONL.

## Migration Impact

Existing logs remain readable but are not required for new health state. Configuration gains opt-in verbosity/export controls with safe defaults.

## Tests Required

### Existing Tests

- Current doctor, logging, ingest, retrieval, and adapter tests under [`tests/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/tests).

### Missing Tests

- Status schema for healthy, disabled, stale, rebuilding, degraded, and failed states.
- Exit-code and remediation-message tests.
- Payload/secret redaction with adversarial values.
- Counter cardinality and bounded-memory longevity.
- Connection, task, queue, and lock visibility.
- Status-query behavior during capture and ingestion contention.

### Regression Tests

- Doctor setup checks remain available.
- Instrumentation does not alter result ordering or canonical records.
- Human and JSON outputs describe the same underlying state.

## Benchmarks Required

- Capture and retrieval overhead with instrumentation enabled versus disabled.
- Status snapshot latency at all WP-16 corpus sizes.
- Long-running counter memory growth.
- Diagnostic behavior under lock contention and large lag.

## Acceptance Criteria

- Status reports capture readiness, canonical and derived watermarks, numeric lag, last successes, and safe last-error code.
- Doctor returns deterministic non-zero exit codes for every documented unhealthy state.
- Automated adversarial tests find zero memory payloads, prompts, or configured secrets in default logs/status.
- Status collection performs no full JSONL read and remains independent of corpus size except constant-size metadata reads.
- Runtime lifecycle tests return open connection, worker, and queue counts to baseline after close.

## Definition of Done

- Versioned human and machine status interfaces are documented.
- Signals cover every WP-14 failure class and WP-11/WP-12 lifecycle state.
- Privacy and overhead gates pass in WP-16.
- Release runbook explains how to diagnose capture, lag, retrieval, and migration failures.

## Dependencies

- WP-04 Storage
- WP-08 Agent-Agnostic API
- WP-11 Sync and Async Execution
- WP-12 Multi-Agent Operation
- WP-13 Configuration
- WP-14 Reliability and Recovery

## Blocks

- WP-16 Testing and Benchmarks
- WP-18 Documentation and Developer Experience
- WP-19 Release Readiness

## Out of Scope

- A hosted monitoring service
- Default export of telemetry off-device
- Memory-content logging
- Record-level high-cardinality metrics
