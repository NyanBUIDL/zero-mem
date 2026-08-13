# Work Package: WP-04 — Canonical Storage and Derived Consistency

**ID:** WP-04

**Title:** Canonical Storage and Derived Consistency


**Status:** NOT STARTED

**Priority:** P1


**Categories:** ARCHITECTURE, RELIABILITY, PERFORMANCE

## Related Findings

F-002, F-003, F-004, F-010. Related ADR: ADR-003.

## Read Scope

Read only the storage, setup, backup, and upgrade modules named in **Files / Modules to Inspect**, their direct contracts, and ADR-003.

## Planning Write Scope

V1.1.0 RE-PLANNING: documentation only — this work package, ADR-003, `TRACEABILITY.md`, and design notes under `docs/v1.1.0/`. No schema or migration write scope exists.

## Planning Files Allowed to Modify

This work package, ADR-003, `TRACEABILITY.md`, and design notes under `docs/v1.1.0/` only.

## Proposed Implementation Write Scope

**PROPOSED FOR A FUTURE AUTHORIZATION ONLY.** A maintainer may authorize only the minimum subset of the entries under **Files / Modules to Inspect**, plus directly associated tests and benchmarks required by this package's acceptance criteria. Every allowed path must be named explicitly when implementation is authorized; all other paths remain forbidden.

## Forbidden Scope

`zero_mem/`, `src/`, `tests/`, migrations, schemas, dependency metadata, runtime configuration, CI, and git tags.

## Objective

Define and implement a safe canonical writer plus explicit JSONL-to-SQLite consistency lifecycle while preserving V1.0.0 canonical data and rebuildability.

## Why This Exists

Capture and derived ingest are separate, and the public Hermes composition does not supply a writer. `JsonlCaptureStore` uses process-local locking/state, while SQLite WAL does not protect JSONL. Retrieval freshness is therefore undefined and shared writes are unsafe.

## Current State on master

`JsonlCaptureStore` owns append/dedupe/sequence in memory and fsyncs each record. `ingest_file()` separately projects into schema v10 tables and checkpoints. `upgrade.py` and `backup.py` rebuild derived state from canonical sources.

## Evidence

F-001 through F-004 and F-010. Code locations: `src/storage/jsonl_capture.py::JsonlCaptureStore`, `src/storage/ingest.py::ingest_file`, `zero_mem/hermes_integration.py::HermesBoundary.register`.

## Problems Found

- BUG/INTEGRATION P1: public registration can have no writer.
- ARCHITECTURE P1: no consistency/freshness contract.
- RELIABILITY P1: process-local lock and sequence/dedupe snapshots.
- PERFORMANCE P1/P2: full-history load, fsync per event, per-line derived commit.

## Affected Components

Capture, adapters, setup/doctor, ingest, backup/restore, upgrade, retrieval freshness, multi-agent policy.

## Files / Modules to Inspect

- [`src/storage/capture_boundary.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/storage/capture_boundary.py)
- [`src/storage/jsonl_capture.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/storage/jsonl_capture.py)
- [`src/storage/ingest.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/storage/ingest.py)
- [`src/storage/canonical_replay.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/storage/canonical_replay.py)
- [`src/storage/sqlite_store.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/storage/sqlite_store.py)
- [`zero_mem/commands_setup.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/commands_setup.py)
- [`zero_mem/backup.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/backup.py)
- [`zero_mem/upgrade.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/upgrade.py)

## Desired State

A public runtime always owns a writer when capture is enabled. It declares one consistency mode and exposes last canonical sequence, last derived sequence, lag, sync, and rebuild health. V1.0.0 JSONL remains readable. Shared writer behavior is safe or deterministically refused.

## Constraints

JSONL and corpus registry/blobs remain canonical. SQLite remains disposable. No silent canonical rewrite, no loss of redaction/retention/tombstone semantics, no source-of-truth inversion.

## Required Changes

1. Make writer presence mandatory for enabled capture.
2. Define consistency modes and sync semantics.
3. Stream from durable offsets/checkpoints.
4. Select and enforce single-writer or interprocess-lock protocol with stale-lock recovery.
5. Define segment/rotation policy and sequence identity.
6. Expose freshness diagnostics to WP-15.
7. Verify backup/restore/upgrade across V1.0.0 and V1.1.0 formats.

## Recommended Direction

For minimum risk, enforce one writer per data root in V1.1.0 with a portable lock/owner record, segmented append-only files, and a derived compact index. Keep an explicit `sync()` path; add background queue only if WP-11 evidence requires it.

## Alternatives Considered

- Make SQLite canonical: rejected.
- Allow undocumented best-effort multi-process append: rejected.
- Introduce a daemon by default: rejected unless single-process integration cannot meet requirements.

## Risks

Cross-platform file-lock semantics, crash recovery, stale owner records, partial final lines, and sequence compatibility.

## Compatibility Impact

V1.0.0 canonical files must open without rewrite. Direct construction of `JsonlCaptureStore` may remain internal-compatible but public API behavior becomes stricter.

## Performance Impact

Streaming and segmentation should reduce startup/ingest memory. Locking and consistency checks add bounded overhead that must be measured.

## Migration Impact

New derived offset/index state must rebuild automatically. Segment adoption cannot require destructive conversion of existing `events-v1.jsonl`.

## Tests Required

### Existing Tests

M1 capture boundary, M2 ingest/checkpoint/rebuild/tombstone, PKG-5 backup/restore, PKG-6 upgrade.

### Missing Tests

Two-process writer contention, stale lock, crash between append/sync, V1.0 monolithic JSONL plus V1.1 segments, lag health, partial-line recovery.

### Regression Tests

Enabled capture without writer is refused; duplicate sequence/dedupe races cannot occur in supported mode; derived state rebuilds exactly from canonical data.

## Benchmarks Required

Single write, 100 sequential, 100 concurrent attempts, 10k replay, suffix sync, restart at 1k/10k/100k/1M, fsync/batch mode disk amplification.

## Acceptance Criteria

- Every successful public observe call has a canonical persistence result.
- Freshness state is measurable and deterministic.
- V1.0.0 JSONL rebuilds schema-v10/V1.1 derived state equivalently.
- Supported writer mode passes process contention and crash-recovery tests.
- No canonical record is silently rewritten or dropped.

## Definition of Done

- Storage/consistency ADR approved and implemented.
- Recovery, concurrency, migration, and benchmark gates pass.
- Doctor/health exposes writer and lag state.
- Documentation specifies durability and consistency guarantees.

## Dependencies

WP-00, WP-01, WP-02, WP-13 configuration design.

## Blocks

WP-03, WP-05 freshness, WP-07, WP-08, WP-12, WP-14, WP-17.

## Out of Scope

Remote storage, replication, distributed locks, and automatic physical deletion of canonical history.
