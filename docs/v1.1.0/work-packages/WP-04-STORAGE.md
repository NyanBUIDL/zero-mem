# Work Package: WP-04 — Canonical Storage and Derived Consistency

**ID:** WP-04

**Title:** Canonical Storage and Derived Consistency


**Status:** NOT STARTED

**Priority:** P1


**Categories:** ARCHITECTURE, RELIABILITY, PERFORMANCE

## Related Findings

F-002, F-003, F-004, F-010. Related ADR: ADR-003.

## Canonical Requirements

REQ-STORE-001 through REQ-STORE-006, REQ-LIFE-001 through REQ-LIFE-006, and REQ-CAP-001/003/004 in `SPEC_TRACEABILITY.md`; canonical DOCX §§6–7, 9–10, 14.3–14.4, 16.4; ADR-003.

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

Define and implement the composite canonical trace contract plus explicit raw-record/canonical-metadata/derived-index consistency lifecycle while preserving V1.0.0 data, append-first provenance, and rebuildability.

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

A public runtime always owns a writer when capture is enabled. It declares one consistency mode and exposes raw append sequence, canonical SQLite metadata watermark, derived index watermark, projection watermark, lag, sync, and rebuild health. V1.0.0 JSONL/SQLite remain discoverable and migratable. Shared writer behavior is safe or deterministically refused. Retention/delete and approved write-back create auditable append/tombstone/supersession records across all layers.

## Constraints

Sanitized append-first JSONL, versioned artifacts/corpus sources, approved write-back records, and canonical SQLite metadata/lifecycle follow ADR-003. FTS/vector/graph/cache/projection tables remain disposable. No silent raw rewrite, no loss of redaction/retention/tombstone semantics, no stale-state source-of-truth inversion.

## Required Changes

1. Make writer presence mandatory for enabled capture.
2. Define consistency modes and sync semantics.
3. Stream from durable offsets/checkpoints.
4. Select and enforce single-writer or interprocess-lock protocol with stale-lock recovery.
5. Define segment/rotation policy and sequence identity.
6. Expose freshness diagnostics to WP-15.
7. Verify backup/restore/upgrade across V1.0.0 and V1.1.0 formats.
8. Separate canonical SQLite tables from disposable indexes and prove full replay equivalence.
9. Implement retention/delete/tombstone behavior across canonical records, artifacts, indexes, and projections.

## Recommended Direction

For minimum risk, enforce one writer per data root in V1.1.0 with a portable lock/owner record, segmented append-only files, and a derived compact index. Keep an explicit `sync()` path; add background queue only if WP-11 evidence requires it.

## Alternatives Considered

- Make derived FTS/index/projection tables canonical or make SQLite the only raw source: rejected.
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
- V1.0.0 JSONL/SQLite migrate to the ADR-003 contract and replay produces equivalent canonical metadata plus derived state.
- Supported writer mode passes process contention and crash-recovery tests.
- No canonical record is silently rewritten or dropped.
- Deleting FTS/vector/graph/projection state leaves canonical data intact and the state rebuilds completely.
- Retention/delete/write-back tests prove authorized append/tombstone behavior and absence of orphaned indexes/projections.

## Security / Privacy, Observability, and Rollback

Redaction/rejection completes before any canonical write; `never_store` never reaches disk; delete/write-back requires explicit authorization. Status exposes watermarks, lag, writer/lock and rebuild/delete state without content. Rollback restores versioned schema/config/metadata backups, preserves append-only raw records, and rebuilds disposable state.

## Exit Gate and Traceability

Exit requires ADR-003 approval, replay/rebuild/concurrency/retention/delete/write-back/migration/fault tests, benchmark evidence, and all mapped REQ-STORE/REQ-LIFE/REQ-CAP rows `COVERED`.

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
