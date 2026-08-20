# V122-01 — Cross-Platform Storage Contract

**Status:** `VERIFIED_LINUX_SCOPED`
**Owner:** Zero-Mem storage boundary
**Baseline SHA:** `af01e494a29410b11dd6d5c4c78275e6e08604df` (parent candidate lineage)
**Audit IDs closed:** A-06; A-08 foundation
**Prerequisites:** V122-00 VERIFIED (`V122-00-EXACT-TREE-REPLACEMENT-REVIEW-001`)
**Approval:** `MAINTAINER_APPROVAL_V122_01_TO_06_2026_08_20`
**Allowed source paths:** `src/storage/platform.py`, `src/storage/coordination.py`, `src/storage/runtime_root.py`, `src/storage/jsonl_capture.py`, `src/storage/recovery.py`, V122-01 platform/storage tests, this package evidence
**Forbidden source paths:** canonical JSONL schema, SQLite schema/migrations, public API semantics, Hermes core, remote refs, tags, releases, PyPI

## Authority read

- [x] `AGENTS.md`, `docs/governance/GITHUB-POLICY.md`
- [x] `docs/architecture/ARCHITECTURE.md`
- [x] Spec Amendment 001 and ADR-009
- [x] v1.2.2 agent-development-system `00` through `07`
- [x] V122-01 package record and shared execution-system gates

## Problem and non-goals

The storage coordination owner was Linux/POSIX-specific and exposed raw platform primitives to domain callers. This package isolates locking, safe regular-file access, identity, cleanup, atomic promotion, directory bootstrap, and typed platform failures. It does not change canonical event format or recovery direction.

## Contract

- **Inputs:** runtime-owned absolute `Path` values and bounded lock timeout/deadline values.
- **Outputs:** regular-file bytes/identity, durable lock context, atomic promotion/cleanup, private directory validation.
- **Typed failures:** `LOCK_TIMEOUT`, `UNSAFE_PATH`, `UNAVAILABLE`, `NOT_FOUND`, `NOT_REGULAR`, `IO_ERROR`; domain callers retain sanitized errors.
- **Authorization:** runtime-owned storage root validation precedes writer/query/recovery use; no caller-supplied public request path is introduced.
- **Freshness:** unchanged; projection/recovery watermarks remain derived concerns.
- **Ownership:** the platform adapter owns descriptors/handles for the operation; runtime owns the canonical writer; locks are released deterministically.
- **Deadline/retry:** lock acquisition uses a finite timeout/deadline; no unbounded retry loop.
- **Restart/shutdown:** OS locks are released by context exit and process termination; writer close remains runtime-owned.
- **Platform:** POSIX backend on Linux/macOS; Win32-oriented handle locking and reparse-point rejection on Windows, with unsupported primitive outcomes typed as `UNAVAILABLE` rather than silently weakened.
- **Compatibility:** `src.storage.coordination` remains a thin compatibility API; canonical storage semantics are unchanged.

## Design and implementation boundary

`src/storage/platform.py` is the sole owner of platform-specific primitives. `coordination.py` delegates to it. `runtime_root.py` uses platform-neutral secure directory helpers. `jsonl_capture.py` uses platform adapter file opening and locking while preserving append/fsync/JSONL receipt behavior. No public API, schema, or Hermes code is changed.

## Acceptance criteria

- [x] Functional lock/read/identity/cleanup/promotion contract.
- [x] Negative symlink/path and identity-fence tests.
- [x] Concurrent process lock, timeout, abandoned-lock release.
- [x] Affected capture/recovery/WP-33 compatibility.
- [x] Static boundary check: no raw `fcntl`, `O_DIRECTORY`, `O_NOFOLLOW`, `LockFileEx`, `/proc/self/fd`, or raw errno in the V122-01 domain owners.
- [x] Independent exact-tree review: `V122-FINAL-EXACT-TREE-ADVERSARIAL-REVIEW-005-20260821` PASS.

## Test commands and results

Recorded in `artifacts/evidence/v1.2.2/ba9cd2d8719bcb00e8562b4a7baf07dfb69cceb0616c134c519d7ec99f5a3bdc/` with raw logs and SHA-256 linkage. Current Linux/CPython 3.11.16/SQLite 3.53.1 evidence is source-bound and verifier-approved.

## Evidence and review

- Changed files: platform adapter, three adapterized owners, focused platform tests, package evidence.
- Evidence manifest: current candidate bundle above.
- Independent reviewer: `V122-FINAL-EXACT-TREE-ADVERSARIAL-REVIEW-005-20260821` — PASS.
- Rollback: revert only the V122-01 package commit; canonical JSONL and SQLite schema are untouched.
