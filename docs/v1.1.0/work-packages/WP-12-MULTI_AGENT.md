# Work Package: WP-12 — Multi-Agent and Multi-Process Operation

**ID:** WP-12

**Title:** Multi-Agent and Multi-Process Operation


**Status:** NOT STARTED

**Priority:** P1

**Categories:** Concurrency, Isolation, Multi-Agent

## Related Findings

F-004, F-006, F-012. Related ADRs: ADR-001, ADR-003, ADR-004.

## Canonical Requirements

Physical runtime/process isolation portions of REQ-ARCH-005, REQ-PROF-003/005/010, REQ-SEC-003/004, and REQ-STORE-001 in `SPEC_TRACEABILITY.md`; canonical DOCX §§8, 13–14; ADR-001, ADR-003, ADR-004, ADR-007.

## Read Scope

Read only the capture, runtime, configuration, storage, and integration modules named in **Files / Modules to Inspect** and the related ADRs.

## Planning Write Scope

V1.1.0 RE-PLANNING: documentation only — this work package, related ADRs, and `TRACEABILITY.md`. No lock, runtime, profile, or database implementation write scope exists.

## Planning Files Allowed to Modify

This work package, related ADRs, and `TRACEABILITY.md` only.

## Proposed Implementation Write Scope

**PROPOSED FOR A FUTURE AUTHORIZATION ONLY.** A maintainer may authorize only the minimum subset of the entries under **Files / Modules to Inspect**, plus directly associated tests and benchmarks required by this package's acceptance criteria. Every allowed path must be named explicitly when implementation is authorized; all other paths remain forbidden.

## Forbidden Scope

`zero_mem/`, `src/`, `tests/`, migrations, schemas, dependency metadata, runtime configuration, CI, and git tags.

## Objective

Define and enforce safe operating modes for multiple agents, threads, and processes using Zero-Mem concurrently.

## Why This Exists

The current capture writer uses only an in-process `threading.RLock`, while runtime configuration can be overwritten through mutable module-global state. Multiple agents may accidentally share canonical files, derived databases, or runtime settings without a process-safe coordination contract.

## Current State on master

- [`src/storage/jsonl_capture.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/storage/jsonl_capture.py) serializes writers only inside one Python process.
- [`src/integration/zero_mem_runtime.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/integration/zero_mem_runtime.py) stores mutable module-global runtime state.
- Adapters can construct or replace that runtime state.
- Profiles and filesystem paths provide some logical separation, but ownership and sharing rules are not authoritative.
- SQLite supplies database locking, but the canonical JSONL append path has no equivalent cross-process policy.

## Evidence

- **F-004:** no cross-process write safety for canonical capture.
- **F-006:** adapter construction can overwrite mutable global runtime state.
- **F-012:** inconsistent path validation can cause profiles/components to point at unexpected locations.
- Multi-process correctness on supported systems is **Needs verification**.

## Problems Found

- **F-004 — P1 — Data integrity:** `threading.RLock` does not coordinate separate processes.
- **F-006 — P1 — Isolation:** global runtime replacement can route one agent through another agent’s configuration.
- **F-012 — P2 — Profile isolation:** path defaults and safety constraints are not uniformly enforced.
- Shared-writer, single-writer, read-only replica, and isolated-profile modes are not defined.

## Affected Components

- Canonical capture
- Runtime ownership
- Profile and path configuration
- SQLite ingestion and retrieval
- Agent integrations
- Reliability and diagnostics

## Files / Modules to Inspect

- [`src/storage/jsonl_capture.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/storage/jsonl_capture.py)
- [`src/integration/zero_mem_runtime.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/integration/zero_mem_runtime.py)
- [`src/integration/bridge_config.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/integration/bridge_config.py)
- [`src/storage/sqlite_store.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/storage/sqlite_store.py)
- [`src/integration/m7/injection_adapter.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/integration/m7/injection_adapter.py)
- Hermes boundary/adapter files identified by WP-07

## Desired State

- Each runtime instance owns immutable effective configuration and explicit resources.
- Per-agent isolated runtimes/data roots are fully supported without changing the canonical retrieval default.
- Shared-memory operation has one documented writer policy: either process-safe serialization or deterministic single-writer rejection.
- Readers have a documented freshness model relative to canonical writes.
- Profile identifiers cannot escape configured roots or alias unintentionally.
- Every capture and retrieval can be attributed to a runtime/profile without storing secret payloads in telemetry.

## Constraints

- Cross-host distributed coordination is outside v1.1.0.
- File-lock semantics differ across platforms and network filesystems.
- Canonical append atomicity alone does not guarantee correct multi-record ordering or ingestion ownership.
- Shared state must not depend on process-global mutable configuration.

## Required Changes

1. Approve supported modes: isolated per-agent profiles and shared profile behavior.
2. Replace implicit global runtime mutation with explicitly passed runtime instances.
3. Add cross-process writer coordination or reject additional writers with an actionable error.
4. Define profile naming, root resolution, ownership, and lock locations.
5. Define ingestion leadership and reader freshness semantics.
6. Add multi-thread, multi-process, crash, and contention tests on supported platforms.
7. Keep physical isolation/writer ownership separate from WP-20 access modes: authorized `profile_first` global reads remain the canonical default, while cross-profile writes stay explicitly authorized/reviewed.

## Recommended Direction

Support isolated profiles by default. For a shared profile, use one explicit writer/ingester lease with multiple read-only consumers unless a proven cross-platform file-lock implementation is adopted. Runtime objects should be dependency-injected and immutable after construction.

## Alternatives Considered

- **Best-effort concurrent appends:** inadequate because ordering, recovery, and ingestion ownership remain ambiguous.
- **One global runtime per process:** simple but unsafe for hosts managing multiple agents/profiles.
- **Distributed locking:** broader than local-first v1.1.0 and introduces external infrastructure.

## Risks

- Stale or orphaned locks after crashes can block recovery.
- A lock that works locally may not be safe on network-mounted storage.
- Shared retrieval can expose another agent’s memory if profile authorization is weak.

## Compatibility Impact

Code relying on implicit module-global runtime replacement must migrate to explicit runtime handles. A temporary compatibility shim may exist only if it is process-local, emits a deprecation signal, and cannot silently switch active profiles.

## Performance Impact

Writer serialization adds contention under shared-profile load. Measurements must report lock wait separately from write time. Isolated profiles should show no cross-profile lock contention.

## Migration Impact

Existing single-profile users can be mapped to one default runtime/profile. Hosts that instantiate multiple adapters must choose isolated or shared mode explicitly during migration.

## Tests Required

### Existing Tests

- Current capture locking, runtime, profile, and adapter tests under [`tests/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/tests).

### Missing Tests

- Two processes writing the same profile.
- Two isolated profiles with simultaneous writes and reads.
- Writer crash while holding coordination state.
- Multiple readers during ingestion transaction boundaries.
- Duplicate runtime construction with conflicting configurations.
- Profile traversal, alias, Unicode, and case-sensitivity behavior.

### Regression Tests

- Single-process operation retains canonical ordering and durability.
- One agent cannot change another runtime’s effective configuration.
- Shared-profile rejection, where applicable, occurs before any write.

## Benchmarks Required

- Throughput and lock-wait distribution for 1, 2, 4, and 8 local writers/readers as supported.
- Isolated-profile versus shared-profile latency.
- Recovery time after forced writer termination.
- Resource usage per active runtime/profile.

## Acceptance Criteria

- Supported multi-agent modes are named and documented; all unspecified modes fail closed.
- In a 10,000-operation multi-process stress run, canonical records are neither lost nor malformed and IDs are not duplicated.
- Conflicting shared writers are either serialized correctly or one is rejected before mutation.
- Creating a second runtime cannot alter the first runtime’s configuration or resources.
- Profile escape and alias tests cannot cross configured isolation boundaries.

## Definition of Done

- Runtime ownership and writer/ingester leadership are implemented and documented.
- Stress, crash-recovery, and isolation tests pass on every supported OS.
- WP-15 can report active mode, profile, lock/lease state, and lag safely.
- Migration guidance covers existing global-runtime consumers.

## Dependencies

- WP-02 Core Boundaries
- WP-04 Storage
- WP-08 Agent-Agnostic API
- WP-11 Sync and Async Execution
- WP-13 Configuration

## Blocks

- WP-14 Reliability and Recovery
- WP-16 Testing and Benchmarks
- WP-18 Documentation and Developer Experience
- WP-19 Release Readiness

## Out of Scope

- Multi-host consensus
- Cloud-managed shared databases
- Network-filesystem guarantees without separate qualification
- Unbounded or unauthorized cross-profile retrieval. Authorized global/profile-first reads are required and owned by WP-20.

## Security / Privacy, Observability, and Rollback

Runtime isolation cannot be used to infer or bypass profile policy; shared local service callers remain explicitly identified/authorized. Status exposes runtime/profile/lease/lock/reader mode and lag without memory content. Rollback returns hosts to isolated per-runtime mode and restores prior leases/configuration without rewriting canonical data.

## Exit Gate and Traceability

Exit requires supported-mode stress/crash/isolation tests on every platform, WP-20 mode conformance under concurrency, deterministic rejection for unsupported modes, and mapped requirements `COVERED`.
