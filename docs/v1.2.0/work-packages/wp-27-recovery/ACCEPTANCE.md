# WP-27 Acceptance

**STATUS: VERIFIED**

## Architecture authorization

`ARCHITECTURE_DECISION_AUTHORIZATION` — scope: WP-27 recovery coordination and filesystem safety; canonical storage semantics unchanged; destructive migration and release publication not authorized.

Round 2 additionally authorizes the runtime-owned storage root, descriptor-pinned production access, coordinator-only promotion, finite default timeout, explicit commit linearization, and removal of arbitrary production callback authority.

Round 3 additionally requires mandatory exact build identity, identity-fenced
promotion and cleanup primitives, descriptor-relative destructive operations
where supported, and an explicit trust boundary excluding privileged hostile
external storage mutators and unsupported filesystems.

Round 4 / final contract requalification selects
`TRUSTED_PRIVATE_STORAGE_ROOT`: malicious external storage mutators and
root-level hostile hosts are outside the supported threat model; legitimate
Zero-Mem concurrency remains fully supported and coordinated. The acceptance
criteria do not claim inode-bound rename/unlink semantics unavailable from the
qualified Python/Linux/POSIX primitives.

## Functional

- [ ] Diagnosis classifies current, missing, stale, corrupt, incompatible, and interrupted derived state under the shared coordination domain.
- [ ] Rebuild uses an owned immutable canonical snapshot and existing subsystem rebuild functions; canonical JSONL is never reopened as a mutable build input.
- [ ] Successful rebuild re-diagnoses as current with matching pinned generation/provenance/checkpoint.
- [ ] Legitimate sanitized-content-hash deduplication is diagnosed from `zm_ingest_log`/checkpoint semantics, including duplicate tails with null checkpoint identity, not raw row-count equality.

## Filesystem safety

- [ ] Production-qualified canonical, derived, recovery, lock, and metadata objects are under one runtime-owned approved root.
- [ ] Legacy arbitrary paths fail closed or are safely normalized during bootstrap; no silent guarantee weakening.
- [ ] Canonical symlink, dangling symlink, non-regular file, parent redirection, and canonical/derived alias fail closed.
- [ ] Derived, build, lock, WAL, and SHM path substitution is rejected or detected before mutation.
- [ ] Recovery-building artifacts have explicit ownership; only verified owned stale artifacts are reclaimable.
- [ ] Unknown or hostile recovery-building objects are preserved and cause unavailable status.

## Coordination and consistency

- [ ] Canonical writer, projection writer, read-open/diagnosis, recovery, and promotion share one documented coordination protocol.
- [ ] Lock acquisition is deterministic, bounded, process-safe, and deadlock-free.
- [ ] Diagnosis during projection/recovery cannot return a mixed-generation result.
- [ ] Promotion is descriptor-relative and atomic; existing regular WAL/SHM sidecars are quarantined before replacement and unknown/non-regular sidecars fail closed.

## Timeout, restart, and failure

- [ ] One absolute caller deadline covers both lock acquisitions, diagnosis, snapshot/build, validation, and promotion.
- [ ] `INTERRUPTED` establishes a commit fence; no late worker can promote or mutate production derived state.
- [ ] Timeout, crash, and interruption leave canonical bytes unchanged.
- [ ] Subsequent recovery safely handles owned stale build artifacts without manual cleanup.
- [ ] `timeout=None` resolves to a finite documented runtime default.
- [ ] Recovery state machine distinguishes `READY_TO_COMMIT`, `COMMITTING`, `COMMITTED`, and `INTERRUPTED` without misleading post-commit interruption.
- [ ] Repeated successful recovery is idempotent; no infinite retry or deadlock exists.

## Regression and verification

- [ ] WP-24/WP-25/WP-26 focused tests pass.
- [ ] Existing M2/M4/M5/M8 recovery/rebuild tests pass.
- [ ] Focused matrix covers concurrency, canonical append, promotion, diagnosis, timeout, crash/restart, WAL/SHM, symlink/TOCTOU, and deduplication.
- [ ] `compileall`, `git diff --check`, static scans, and fresh independent review pass.
- [ ] Full isolated regression is run if host resources permit; host quota/I/O failures are recorded separately.
- [ ] Private/test rebuild callbacks have isolated build-only authority and cannot promote or mutate production state after interruption.
- [ ] Missing or mismatched owner build identity never authorizes cleanup or promotion.
- [ ] Promotion compares current build identity immediately before commit authority and uses one internal promotion primitive.
- [ ] Cleanup does not use verify-close-unlink for production recovery artifacts without the strongest documented controlled-directory boundary.
- [ ] Rollback failure is surfaced as a bounded failure and never silently presented as clean success.
- [ ] Every legitimate Zero-Mem production writer/reader path uses the approved coordination domain where it can overlap recovery.

## Exit gate

Transition to `VERIFIED` only with executable evidence for every listed blocker, canonical immutability, no destructive migration, no unresolved coordination issue, and current-tree independent review:

```text
passed: true
security_concerns: []
logic_errors: []
```

## Final bounded closure gates

- [ ] `RecoveryCoordinator` requires `RuntimeStorageRoot` and rejects canonical
  or derived paths outside the approved domains.
- [ ] Owner identity rejects booleans, missing values, malformed values, and
  invalid identity ranges fail closed.
- [ ] Cleanup and snapshot failures produce bounded diagnostics and cannot be
  reported as clean success.
- [ ] Post-commit diagnosis failure is committed failure/unavailable, never
  pre-commit `INTERRUPTED`.
- [ ] Orphan owner markers and unknown recovery quarantine artifacts are
  diagnosed and preserved fail closed.
- [ ] Fresh exact-tree independent review passes with empty blocking arrays.

## FINAL_V1_2_WP27_CONTRACT_FREEZE

**Status:** FROZEN AND VERIFIED — no moving goalposts.

### Supported model and exclusions

The supported model is a trusted runtime-owned private `RuntimeStorageRoot`,
qualified local POSIX/Linux semantics, and legitimate Zero-Mem participants
using the approved coordination protocol. JSONL is canonical append-only truth;
SQLite/FTS/projections are derived and recovery is canonical → derived. Hostile
root/kernel/mount actors, privileged external mutation bypassing coordination,
unsupported network filesystems, and unrelated privileged directory mutation are
out of model and cannot alone block WP-27.

### Frozen invariants A–L

The required invariants are exactly those defined in the matching
`FINAL_V1_2_WP27_CONTRACT_FREEZE` section of `TECHNICAL-DESIGN.md`: A runtime
root, B canonical immutability, C coherent canonical input, D legitimate
coordination, E bounded recovery, F interrupted semantics, G strict owner
identity, H cleanup-failure visibility, I deterministic stale-artifact model,
J SQLite/WAL/SHM generation safety, K restart/idempotence, and L truthful
status semantics.

### Frozen executable acceptance matrix

- **A:** valid root; outside-root production rejection; safe normal bootstrap;
  no production path bypass.
- **B/C:** canonical bytes unchanged; coherent snapshot/generation; append
  watermark behavior; missing, corrupt, stale, incompatible inputs.
- **D/J:** canonical writer/projection/recovery/diagnosis/readers coordinate;
  writer/recovery and projection/recovery concurrency; no generation mixing;
  WAL/SHM crash leftovers.
- **E/F/L:** finite `timeout=None`; invalid/NaN/infinite rejection;
  pre-commit timeout gives `INTERRUPTED` with no promotion; post-commit failure
  is not pre-commit `INTERRUPTED`; no false success.
- **G:** valid identity; bool device/inode rejection; malformed or missing
  owner/canonical identity rejection.
- **H:** successful cleanup; injected legitimate cleanup failure is surfaced;
  residual state remains diagnosable; no clean-success masking.
- **I:** build DB, owner marker, orphan/malformed marker, quarantine, WAL/SHM,
  and unknown in-domain artifact classification; unknown artifacts preserved and
  fail closed where safe state cannot be proven.
- **K:** restart after missing/stale/corrupt/interrupted state; repeated
  recovery/idempotence; duplicate content-hash semantics.

### Reviewer rules

Only a reproducible violation of A–L through the supported model blocks. A
reviewer must report invariant, source location, supported path, evidence, and
summary in the required JSON shape. No acceptance item may be expanded during
final verification.
