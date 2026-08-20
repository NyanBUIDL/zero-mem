# V122-01 Windows/macOS Qualification Handoff to v1.2.3

**Status:** `IMPLEMENTATION_COMPLETE` / Linux verified / Windows and macOS qualification deferred
**Candidate HEAD:** `ad6e38eaa7ac7a764aa54bd5fee8dfcd59a5a6a6`
**Worktree:** intentionally dirty; current-tree evidence is bound to the candidate HEAD plus the tracked/untracked package delta.
**Parent/release lineage:** V122-00 baseline `af01e494a29410b11dd6d5c4c78275e6e08604df`; V122-00 was `VERIFIED` by `V122-00-EXACT-TREE-REPLACEMENT-REVIEW-001`.

## 1. Decision

The maintainer explicitly deferred real Windows and macOS qualification from v1.2.2 to v1.2.3 because those machines are unavailable in the current execution environment. Linux remains the active qualified platform target for v1.2.2. v1.2.2 must not advertise Windows or macOS as production-qualified. The implementation and tests remain in the tree and qualification resumes in v1.2.3. This is a bounded execution/release exception, not a waiver of platform safety requirements.

V122-01 classification:

- Engineering: `IMPLEMENTATION_COMPLETE`
- Linux: `VERIFIED`
- Windows: `DEFERRED_TO_V1_2_3`
- macOS: `DEFERRED_TO_V1_2_3`
- Cross-platform release claim: `NOT_ALLOWED`
- Dependent package execution: authorized by the maintainer exception

## 2. Baseline

- Current candidate SHA/tree identity: `ad6e38eaa7ac7a764aa54bd5fee8dfcd59a5a6a6`; the worktree is dirty and future evidence must bind the exact post-change tree, not reuse this SHA after mutation.
- V122-01 evidence: `artifacts/evidence/v1.2.2/V122-01-remediation-current/` (commands, raw logs, SHA256 manifest, final Graphify snapshots).
- Relevant current review: `V122-01-EXACT-TREE-REVIEW-003` is historical/superseded for this maintainer decision; its Linux findings were remediated in the current tree. No historical review is a current blocker by itself.
- V122-01 package record: `docs/v1.2.2/work-packages/V122-01-cross-platform-storage/README.md`.
- Prior V122-00 handoff: `artifacts/handoffs/V122-00-HANDOFF.md`.
- Linux environment used by the current evidence: Linux kernel `7.0.0-30-generic`, x86_64, CPython `3.11.16`, SQLite `3.53.1`, FTS5 available.
- Focused/affected local V122-01 result recorded in the current command manifest: `105 passed, 0 failed, 0 skipped`; evidence verifier: `4 passed`.
- Platform-boundary audit: PASS, zero forbidden raw primitive hits in the designated recovery/JSONL owners.
- Windows/macOS execution: not available; neither platform is qualified by this record.

## 3. Work Already Completed

The implementation is retained in these owners and tests:

| Area | Current owner/symbols | Completed behavior |
|---|---|---|
| Platform abstraction | `src/storage/platform.py`: platform adapter, `FileIdentity`, `open_regular`, lock/promotion/cleanup helpers | Single boundary for platform-sensitive filesystem behavior and typed failures; POSIX and Win32-oriented branches remain isolated. |
| Win32 identity | `src/storage/platform.py`: Windows `BY_HANDLE_FILE_INFORMATION` declarations and identity helper | Correct ABI/layout, pointer-safe declarations, mandatory handle-derived volume/file-index identity, identity fencing. |
| Win32 file open | `src/storage/platform.py`: `open_regular` and handle-bound validation | Expected identity and digest checks occur on the opened handle; non-regular/unsafe/unavailable outcomes are typed. |
| Shared/exclusive locks | `src/storage/platform.py`, `src/storage/coordination.py` | Windows shared/exclusive lock implementation work and POSIX compatibility are behind the adapter; bounded timeout semantics are preserved. |
| Reparse/path handling | `src/storage/platform.py`, `src/storage/runtime_root.py` | Runtime-owned roots and platform path checks reject unsafe path/reparse conditions rather than weakening the contract. |
| Atomic promotion | `src/storage/platform.py`, `src/storage/recovery.py` | Source pathname reopen was removed from `atomic_promote`; promotion is handle/identity-fenced where supported and failures are normalized. |
| Relative delete/rename | `src/storage/platform.py`, `src/storage/recovery.py` | Windows handle-bound relative delete/rename helpers are used by recovery cleanup. |
| JSONL short writes | `src/storage/platform.py`, `src/storage/jsonl_capture.py` | Complete-write loops, durable flush behavior, and short-write handling preserve append/receipt semantics. |
| Error normalization | `src/storage/platform.py`, `src/storage/recovery.py`, `src/storage/jsonl_capture.py` | Raw platform errors are converted to typed/sanitized domain outcomes at the boundary. |
| Recovery integration | `src/storage/recovery.py`, `tests/unit/test_wp27_recovery.py` | Recovery cleanup/promotion routes through platform helpers; canonical JSONL remains immutable and recovery is canonical → derived. |
| Abandoned-lock portability | `tests/unit/test_v122_lock_modes.py` and related lock contexts | Explicit spawn-based multiprocessing coverage avoids fork-only assumptions and covers release/timeout behavior. |
| Evidence verifier | `scripts/verify_v122_evidence.py`, `tests/unit/test_v122_evidence_verifier.py` | Source-bound manifests require exact tree/log/hash evidence and reject incomplete or altered records. |
| Regression coverage | `tests/unit/test_v122_platform_storage.py`, `test_v122_short_write.py`, `test_v122_lock_modes.py`, `test_wp27_recovery.py`, affected WP tests | Deterministic identity, locking, capture, recovery, short-write, and boundary regressions are covered. |

No canonical JSONL semantics, SQLite schema, public API semantics, Hermes core, remote refs, tags, releases, or PyPI artifacts were changed by V122-01.

## 4. What Has NOT Been Proven

Linux cannot prove Windows kernel handle semantics, `LockFileEx` shared/exclusive behavior, Windows reparse-point behavior, Win32 identity ABI at runtime, Windows atomic promotion behavior, or Windows error normalization under real failures. Linux also cannot prove macOS-specific POSIX behavior or macOS filesystem/locking edge cases. No unconditional skip may count as a platform PASS.

## 5. Windows Qualification Procedure

On a real supported Windows machine or approved Windows CI job:

1. Check out the exact v1.2.3 candidate and verify SHA and tree identity.
2. Use each supported CPython version declared by `pyproject.toml`/package constraints.
3. Create an isolated virtual environment and install declared test/build dependencies only.
4. Derive the focused platform-storage command from the current test files and run it.
5. Run lock tests, including shared/shared, shared/exclusive, exclusive/shared, exclusive/exclusive, timeout, and abandoned-lock process tests.
6. Run reparse/path-safety tests.
7. Run identity tests.
8. Run atomic-promotion tests.
9. Run JSONL short-write/capture tests.
10. Run recovery tests.
11. Run WP-33 affected tests.
12. Run the full suite with no collection errors and no hidden/unconditional skips.
13. Build wheel and sdist using the repository's declared build workflow.
14. Clean-install both artifacts into fresh environments and run public/API/sidecar/Hermes smoke tests.
15. Collect exact commands, exit codes, elapsed times, OS/Python versions, raw logs, raw-log SHA-256 values, test counts, artifact hashes, and an exact-tree independent review.

Do not invent a command when the repository's current test/build scripts provide the command. The source of command truth is the current `pyproject.toml`, test layout, package scripts, and V122-06 evidence manifest.

## 6. Windows Acceptance Criteria

Real Windows evidence must record `PASS` for every row: `REGULAR_FILE_IDENTITY`, `SHARED_SHARED_LOCK`, `SHARED_EXCLUSIVE_CONFLICT`, `EXCLUSIVE_SHARED_CONFLICT`, `EXCLUSIVE_EXCLUSIVE_CONFLICT`, `ABANDONED_LOCK`, `LOCK_TIMEOUT`, `REPARSE_PROTECTION`, `ATOMIC_PROMOTION`, `ERROR_NORMALIZATION`, `JSONL_CAPTURE`, `RECOVERY`, `FULL_SUITE`, and `CLEAN_INSTALL`. No unconditional skip, emulation, or Linux-only result counts as PASS.

## 7. macOS Qualification Procedure

On a real supported macOS machine or approved macOS CI job:

1. Check out and verify the exact v1.2.3 candidate SHA/tree.
2. Use each supported CPython version declared by package constraints in isolated environments.
3. Install declared dependencies and run the focused platform-storage suite.
4. Run POSIX locking, process contention, timeout, abandoned-lock, and restart tests.
5. Run no-follow/path safety and alias/identity tests.
6. Run file-identity and atomic-promotion tests.
7. Run JSONL short-write/capture and recovery tests.
8. Run WP-33 and all affected V122 tests.
9. Run the full suite without collection errors or unconditional skips.
10. Build wheel and sdist, clean-install both, and run public API, sidecar, and Hermes lifecycle smoke tests.
11. Record raw logs and hashes, exact environment/toolchain, artifact hashes, test counts, and an independent exact-tree review.

## 8. macOS Acceptance Criteria

Real macOS evidence must show PASS for POSIX locking, shared/exclusive contention and timeout, abandoned-lock recovery, no-follow/path-safety and alias protection, regular-file identity, atomic promotion, normalized errors, JSONL capture/short writes, canonical-to-derived recovery, WP-33, full suite, wheel/sdist build, and clean-install smoke. No skip or Linux result counts as PASS.

## 9. Failure Triage

Every future failure is classified as exactly one of `PRODUCT`, `TEST`, `ENVIRONMENT`, `PLATFORM_CONTRACT`, or `EVIDENCE`, then mapped to the owning production file/symbol. Product and platform-contract defects require remediation; test defects require correcting the test without weakening the contract; environment failures require reproducible environment evidence; evidence failures require regenerating source-bound records. Real product defects must not be worked around with skips.

## 10. v1.2.3 Completion Rule

Deferred Windows/macOS work closes only when real-platform evidence exists for the declared support matrix, all acceptance rows pass, the exact current tree has an independent review, and support claims are updated explicitly. Until then, v1.2.2 claims remain Linux-only.
