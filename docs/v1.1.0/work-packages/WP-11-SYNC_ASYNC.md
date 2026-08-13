# Work Package: WP-11 — Sync and Async Execution

**ID:** WP-11

**Title:** Sync and Async Execution


**Status:** NOT STARTED

**Priority:** P2

**Categories:** API, Concurrency, Responsiveness

## Related Findings

F-003, F-010, F-014. Related ADRs: ADR-001 and ADR-003.

## Read Scope

Read only the capture, storage, retrieval, adapter, and proposed public API boundaries named in **Files / Modules to Inspect**.

## Planning Write Scope

V1.1.0 RE-PLANNING: documentation only — this work package, related ADRs, and `TRACEABILITY.md`. No concurrency, executor, connection, or API implementation write scope exists.

## Planning Files Allowed to Modify

This work package, related ADRs, and `TRACEABILITY.md` only.

## Proposed Implementation Write Scope

**PROPOSED FOR A FUTURE AUTHORIZATION ONLY.** A maintainer may authorize only the minimum subset of the entries under **Files / Modules to Inspect**, plus directly associated tests and benchmarks required by this package's acceptance criteria. Every allowed path must be named explicitly when implementation is authorized; all other paths remain forbidden.

## Forbidden Scope

`zero_mem/`, `src/`, `tests/`, migrations, schemas, dependency metadata, runtime configuration, CI, and git tags.

## Objective

Define safe synchronous and asynchronous execution contracts so agent runtimes can use Zero-Mem without blocking event loops or creating unbounded background work.

## Why This Exists

Capture, JSONL loading, SQLite access, and ingestion are synchronous. That is acceptable for a synchronous API, but async agent hosts need explicit wrappers, cancellation boundaries, backpressure, and lifecycle management. Implicitly calling current operations from an event loop risks latency spikes as corpus size grows.

## Current State on master

- Capture appends synchronously and may call `fsync` for each record.
- Ingestion performs synchronous file and SQLite work.
- Retrieval opens or uses synchronous SQLite connections.
- [`src/integration/m7/injection_adapter.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/integration/m7/injection_adapter.py) may open a read-only connection per memory-needed call.
- No stable async public API or worker lifecycle is documented.

## Evidence

- **F-003:** full JSONL materialization and reread grows with corpus size.
- **F-010:** per-append `fsync` and per-line derived commits increase synchronous cost.
- **F-014:** retrieval adapter connection lifecycle is repeated and not explicit.
- At 10,000 records, measured capture load reached **1,237.77 ms** and ingestion **19.355 s**; running these inline would visibly block an event loop.

## Problems Found

- **F-003 — P1 — Async safety:** corpus-scale synchronous work has no offload contract.
- **F-010 — P2 — Throughput:** durability and transaction granularity amplify blocking time.
- **F-014 — P2 — Resource lifecycle:** adapter calls lack an explicit reusable/closable connection policy.
- Cancellation, queue bounds, shutdown draining, and error propagation are unspecified.

## Affected Components

- Public API
- Capture and ingestion
- Retrieval and context assembly
- Agent adapters
- Runtime lifecycle and configuration
- Testing and observability

## Files / Modules to Inspect

- [`src/storage/jsonl_capture.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/storage/jsonl_capture.py)
- [`src/storage/ingest.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/storage/ingest.py)
- [`src/storage/sqlite_store.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/storage/sqlite_store.py)
- [`src/integration/m7/injection_adapter.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/integration/m7/injection_adapter.py)
- Public API modules defined by WP-08

## Desired State

- Synchronous APIs remain explicit and deterministic.
- Async APIs offload blocking work to a bounded worker mechanism.
- Queues have configured capacity and documented overflow behavior.
- Cancellation does not leave partial canonical writes or half-applied migrations.
- Runtime objects expose deterministic `close`/`aclose` lifecycle methods.
- Shutdown behavior distinguishes flush, drain-with-timeout, and immediate stop.

## Constraints

- SQLite connections cannot be moved across threads unless created/configured for that model.
- Canonical capture durability cannot be weakened implicitly.
- Async wrappers must not create one executor or connection per request.
- Native async SQLite replacement is not required for v1.1.0.

## Required Changes

1. Classify each public operation as fast sync, blocking sync, or async-capable.
2. Add bounded async adapters for blocking capture, ingest, and retrieval paths.
3. Define worker, queue, cancellation, timeout, and shutdown semantics.
4. Define per-thread/per-worker SQLite connection ownership.
5. Expose runtime lifecycle methods and context managers.
6. Add event-loop responsiveness and resource-leak tests.

## Recommended Direction

Keep the storage implementation synchronous and provide a small async facade backed by a bounded executor or dedicated worker. Preserve a single authoritative implementation, create connections inside their owning worker, and surface overload rather than growing an unbounded queue.

## Alternatives Considered

- **Rewrite on an async SQLite library:** larger dependency and migration surface without eliminating SQLite serialization constraints.
- **Run everything inline:** simplest but unsafe for async hosts at measured corpus sizes.
- **Fire-and-forget tasks:** low caller latency but weak durability, error reporting, and shutdown guarantees.

## Risks

- Cancellation can be mistaken for transaction rollback after a canonical append has already committed.
- Executor starvation can couple memory operations to unrelated application work.
- Background exceptions can become silent data-lag failures.

## Compatibility Impact

Existing synchronous behavior remains supported. New async entry points must have parallel result and error types, while deprecated adapter-specific calls follow WP-08 migration policy.

## Performance Impact

Async wrappers improve host responsiveness, not raw storage speed. Queue wait, execution time, and saturation must be observable separately. Numeric service-level thresholds are finalized by WP-16 from supported-platform baselines.

## Migration Impact

Async consumers can migrate operation-by-operation. Existing synchronous consumers require no forced rewrite. Runtime shutdown must be added wherever long-lived adapters are instantiated.

## Tests Required

### Existing Tests

- Current capture, ingest, retrieval, and adapter tests under [`tests/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/tests).

### Missing Tests

- Event-loop heartbeat during large ingest/retrieval.
- Queue saturation and overflow policy.
- Cancellation before dispatch, during derived ingestion, and after canonical append.
- `close`/`aclose` idempotency.
- Concurrent async calls with separate profiles.
- Shutdown drain and timeout behavior.

### Regression Tests

- Sync and async APIs return equivalent domain results for the same input.
- Exceptions retain stable codes and causes across both APIs.
- No connection, thread, or task remains after runtime shutdown.

## Benchmarks Required

- Event-loop delay distribution under capture, ingest, and retrieval load.
- Queue wait and worker execution latency at 1, 10, and configured maximum concurrency.
- Throughput comparison with synchronous baseline.
- Connection/task counts before and after repeated runtime lifecycle tests.

## Acceptance Criteria

- No documented async API executes filesystem or SQLite work on the event-loop thread.
- Background queues are bounded and expose deterministic overflow behavior.
- Cancellation outcomes identify whether canonical capture committed.
- Repeated create/use/close cycles return threads, tasks, and database connections to baseline counts.
- Sync/async conformance tests pass for all shared operations and error cases.

## Definition of Done

- Public sync and async contracts are documented and typed.
- Adapters use the supported runtime lifecycle.
- Responsiveness, cancellation, overload, and leak tests pass in WP-16.
- Observability in WP-15 exposes queue and worker health without payload content.

## Dependencies

- WP-02 Core Boundaries
- WP-04 Storage
- WP-08 Agent-Agnostic API
- WP-13 Configuration

## Blocks

- WP-12 Multi-Agent Operation
- WP-16 Testing and Benchmarks
- WP-18 Documentation and Developer Experience

## Out of Scope

- Distributed task queues
- A full native-async storage rewrite
- Guarantees that cancellation can undo an already durable canonical append
- Unbounded background concurrency
