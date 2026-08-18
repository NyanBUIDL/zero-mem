# Work Package: WP-14 — Reliability, Failure Handling, and Recovery

**ID:** WP-14

**Title:** Reliability, Failure Handling, and Recovery


**Status:** NOT STARTED

**Priority:** P1

**Categories:** Reliability, Recovery, Data Integrity

## Related Findings

F-001, F-002, F-003, F-004, F-013. Related ADRs: ADR-002, ADR-003.

## Canonical Requirements

REQ-LIFE-001 through REQ-LIFE-006, REQ-SEC-008, REQ-STORE-003/005/006, and recovery portions of REQ-OBS-006/012 in `SPEC_TRACEABILITY.md`; canonical DOCX §§6–7, 9.3, 12.6, 14.3–14.4, 16.4, 20; ADR-003 and ADR-008.

## Read Scope

Read only the capture, ingestion, storage, backup, upgrade, doctor, and Hermes boundary modules named in **Files / Modules to Inspect**.

## Planning Write Scope

V1.1.0 RE-PLANNING: documentation only — this work package, recovery runbook drafts under `docs/`, and `TRACEABILITY.md`. No storage, backup, upgrade, or repair implementation write scope exists.

## Planning Files Allowed to Modify

This work package, recovery runbook Markdown under `docs/`, and `TRACEABILITY.md` only.

## Proposed Implementation Write Scope

**PROPOSED FOR A FUTURE AUTHORIZATION ONLY.** A maintainer may authorize only the minimum subset of the entries under **Files / Modules to Inspect**, plus directly associated tests and benchmarks required by this package's acceptance criteria. Every allowed path must be named explicitly when implementation is authorized; all other paths remain forbidden.

## Forbidden Scope

`zero_mem/`, `src/`, `tests/`, migrations, schemas, dependency metadata, runtime configuration, CI, and git tags.

## Objective

Make failures explicit, preserve canonical data, provide deterministic recovery procedures, and prevent silent divergence between capture and retrieval state.

## Why This Exists

The current Hermes boundary can register capture hooks without a backing store, while canonical JSONL and derived SQLite state have no unified freshness lifecycle. Process-only locking, repeated full-file ingestion, and limited diagnostics increase the chance that users see silent loss, stale retrieval, or unclear recovery after interruption.

## Current State on master

- Canonical events are appended to JSONL.
- SQLite/FTS is derived through a separate ingestion path.
- Backup and upgrade modules exist, but the audit did not prove an end-to-end recovery contract for partial failure.
- Doctor covers basic checks but not all lag, lock, capture, corruption, and recovery states.
- Adapter errors and disabled/no-store states are not consistently surfaced.

## Evidence

- **F-001:** Hermes capture can be registered without persistence.
- **F-002:** canonical and derived stores have no explicit consistency/freshness lifecycle.
- **F-003:** ingestion rereads/materializes the corpus, increasing interruption exposure.
- **F-004:** canonical writer coordination is process-local only.
- **F-013:** doctor lacks sufficient capture failure and derived-lag diagnosis.
- Recovery from disk-full, malformed JSONL, locked SQLite, interrupted upgrade, and corrupted derived state is **Needs verification**.

## Problems Found

- **F-001 — P1 — Silent failure:** enabled-looking integration can persist nothing.
- **F-002 — P1 — Consistency:** retrieval may lag canonical capture without a visible watermark.
- **F-004 — P1 — Concurrency:** competing processes can undermine canonical integrity.
- **F-013 — P2 — Recovery diagnostics:** operators lack actionable state and repair guidance.
- Failure classes do not have stable error codes, retryability, or data-commit semantics.

## Affected Components

- Capture and canonical store
- Ingestion and derived database
- Runtime and integrations
- Upgrade, migration, and backup
- Doctor/status and observability
- Public error model

## Files / Modules to Inspect

- [`src/storage/jsonl_capture.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/storage/jsonl_capture.py)
- [`src/storage/ingest.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/storage/ingest.py)
- [`src/storage/sqlite_store.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/storage/sqlite_store.py)
- [`zero_mem/backup.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/backup.py)
- [`zero_mem/upgrade.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/upgrade.py)
- [`zero_mem/commands_doctor.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/commands_doctor.py)
- Hermes boundary files identified by WP-07

## Desired State

- “Enabled” means persistence prerequisites passed; otherwise startup fails or the integration is explicitly disabled.
- Every canonical append has a stable outcome: committed, rejected before write, or unknown/recovery-required.
- Derived state records a durable source watermark and can be rebuilt from canonical data.
- Recovery procedures cover stale derived data, malformed tails, lock contention, disk full, permission loss, interrupted migration, and schema mismatch.
- Errors have stable codes, safe messages, retry guidance, and commit-state metadata.
- Repair never mutates canonical data without backup and explicit authorization.
- Canonical source, decision, profile-policy, concurrent-update, and stale-information conflicts have stable typed records; all positions/provenance remain visible and no last-writer-wins or silent overwrite is allowed.

## Constraints

- JSONL is canonical unless WP-04 approves a different contract.
- `fsync` success does not protect against all hardware/filesystem failures.
- Recovery must preserve forensic evidence for ambiguous corruption.
- Automatic repair must be limited to changes proven safe and idempotent.

## Required Changes

1. Define a failure taxonomy and stable public error model.
2. Add startup readiness checks for capture and retrieval prerequisites.
3. Add source watermarks, lag detection, and idempotent derived rebuild.
4. Define lock timeout, retry, and stale-lock recovery behavior.
5. Add backup-before-migration and rollback verification.
6. Implement a read-only diagnosis mode and explicit repair commands.
7. Add fault-injection and crash-recovery tests.
8. Define the canonical conflict taxonomy/detection/resolution audit contract consumed by retrieval and WP-22; keep projection/edit-conflict detection in WP-22.
9. Cover retention/delete/tombstone recovery, approved write-back recovery, and conflict replay.

## Recommended Direction

Treat canonical append as the primary durability boundary and derived SQLite as disposable/rebuildable. Record ingestion progress with an offset plus record identity/checksum suitable for detecting truncation or replacement. Separate diagnosis from repair, and require an explicit command for any canonical mutation.

## Alternatives Considered

- **Hide failures and continue:** maximizes availability appearance but risks silent memory loss.
- **Make SQLite/derived indexes the only canonical source:** rejected; ADR-003 requires append-first replay provenance plus explicit canonical metadata and rebuildable indexes.
- **Always auto-rebuild:** convenient, but expensive and unsafe when the canonical source itself is ambiguous.

## Risks

- A stale watermark can falsely report freshness.
- Retrying ambiguous writes can duplicate records without stable IDs.
- Recovery tools can worsen corruption if they overwrite evidence.
- Disk-full handling may fail to persist its own diagnostics.

## Compatibility Impact

Operations that previously failed silently may now fail startup or return explicit errors. This is intentional and requires integration updates and release notes.

## Performance Impact

Checksums, watermarks, and readiness checks add bounded overhead. They must avoid full-corpus scans during normal startup and retrieval. Recovery operations may be expensive but must report progress.

## Migration Impact

Before v1.1.0 migration, canonical data, configuration, descriptor state, and schema metadata require a verified backup. Rollback must restore both file state and the version that can read it.

## Tests Required

### Existing Tests

- Current capture, ingest, backup, upgrade, doctor, and storage failure tests under [`tests/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/tests).

### Missing Tests

- Integration enabled with absent/unwritable store.
- Disk full before and during append/transaction.
- Malformed or truncated final JSONL record.
- Canonical file replacement/truncation after watermark.
- SQLite lock timeout, corruption, and unavailable FTS.
- Process termination at each migration and ingestion checkpoint.
- Backup verification and rollback restore.

### Regression Tests

- Valid canonical data rebuilds to the same logical derived records.
- Recovery retries do not duplicate stable record IDs.
- Read-only diagnosis changes no file timestamp or database content.

## Benchmarks Required

- Incremental catch-up and full rebuild duration at WP-16 corpus scales.
- Startup readiness-check cost.
- Recovery time objective measurements for supported failure fixtures.
- Checksum/watermark overhead per append and ingest batch.

## Acceptance Criteria

- A configured integration cannot report capture-ready without a writable canonical store.
- Doctor/status reports canonical count/watermark, derived watermark, lag, last successful ingest, and last safe error.
- Deleting the derived database and rebuilding from a valid canonical fixture reproduces all expected logical records with zero duplicates.
- Every fault-injection test yields a documented error code and commit-state classification.
- Interrupted migration restores the pre-migration state through the documented rollback procedure.
- Diagnosis mode is proven read-only by before/after hashes or equivalent metadata checks.
- Source/decision/profile/concurrent/stale conflict fixtures preserve all canonical positions, return no silent winner, and reproduce through replay/rebuild.
- Interrupted approved write-back or delete either commits exactly once with a known outcome or remains recovery-required; it never partially overwrites raw history.

## Security / Privacy, Observability, and Rollback

Recovery/conflict/delete operations require explicit authority and preserve forensic evidence without secret payloads. Status exposes safe conflict/backlog/recovery classes and commit outcome. Rollback restores verified backups/versioned metadata and appends compensating/superseding records; it never deletes raw history to hide a conflict.

## Exit Gate and Traceability

Exit requires the full failure/conflict/retention/delete/write-back matrix, replay/rebuild and backup/rollback proof on supported platforms, no P1 silent-loss/staleness/overwrite path, and all mapped requirements `COVERED`.

## Definition of Done

- Failure taxonomy and recovery runbook are approved.
- Fault-injection suite passes on the supported matrix.
- No P1 silent-loss or silent-staleness path remains open.
- Recovery evidence is attached to WP-19.

## Dependencies

- WP-04 Storage
- WP-08 Agent-Agnostic API
- WP-12 Multi-Agent Operation
- WP-13 Configuration

## Blocks

- WP-15 Observability
- WP-16 Testing and Benchmarks
- WP-17 Migration
- WP-19 Release Readiness

## Out of Scope

- Disaster recovery across hosts or regions
- Automatic repair of ambiguous canonical corruption
- Hardware-level durability guarantees
- Remote backup services
