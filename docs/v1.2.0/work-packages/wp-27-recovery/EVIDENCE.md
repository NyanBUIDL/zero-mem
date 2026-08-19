# WP-27 Evidence

## Identity and authorization

- WP: WP-27 Recovery
- Baseline SHA: `7d871a95017c250f2d27a6e284ccfc6ad6f3c02e`
- Dependencies: WP-25 and WP-26 `VERIFIED`
- Authorization: `AUTONOMOUS_EXECUTION_AUTHORIZATION`, scope `WP-24..WP-35`; per-WP approval not required; architecture escalation required; release publication not authorized.

## Implementation

- Added `src/storage/recovery.py` with typed `RecoveryStatus`, `RecoveryResult`, and `RecoveryCoordinator`.
- Diagnosis delegates to the existing read-only `zero_mem.recovery.diagnose` contract.
- Recovery rebuilds only disposable derived SQLite state using existing `rebuild_from_jsonl`.
- Rebuild occurs in a sibling `.recovery-building` database and is atomically promoted only after successful rebuild; canonical JSONL is never written.
- Recovery uses a bounded daemon worker and caller timeout; deadline expiry returns `INTERRUPTED` and terminally prevents automatic retry.
- Corrupt/missing derived state is rebuildable; malformed/missing canonical state is unavailable and not rebuilt.
- No schema migration, new dependency, retrieval, authorization, API, sidecar, Hermes, release, tag, push, or publication was added.

## Files changed

- `src/storage/recovery.py`
- `tests/unit/test_wp27_recovery.py`
- WP-27 planning/evidence/state documents.

## TDD and verification

- RED: `.venv/bin/python -m pytest tests/unit/test_wp27_recovery.py -q` failed at collection because `src.storage.recovery` did not exist.
- Focused WP-24/WP-25/WP-26/WP-27 and storage recovery suite: `89 passed`.
- Full isolated regression excluding known baseline artifact test: `3192 passed, 5 skipped in 63.65s`.
- Compile: `.venv/bin/python -m compileall -q src/storage/recovery.py` → pass.
- `git diff --check` → pass.
- Graphify final local-tree read-only analysis after lock and main-thread-promotion hardening: `7154 nodes, 21114 edges, 195 communities`; `RecoveryCoordinator` connects to SQLiteStore/configuration, canonical/derived locks, temporary build, caller-thread promotion, cancellation, sidecar/symlink guards, and WP-27 tests. Disposable output: `/home/lenovo/graphify-zero-mem-v1.2-wp27-final-5`.

- Fresh current-tree independent review: `passed: false`. Blocking findings: path/sidecar symlink TOCTOU; incomplete coordination with concurrent SQLite writers/readers; canonical input is not pinned against non-cooperating mutation; timeout workers continue derived-state mutation after caller return; stale `.recovery-building` artifacts can block restart; public diagnosis is not serialized with recovery/writes. These require an approved coordination/filesystem-safety decision before implementation.

Independent fail-closed review: `passed: true`; `security_concerns: []`; `logic_errors: []`. Reviewer confirmed canonical/derived locks, timeout no-promotion, deterministic rebuild, sidecar/symlink handling, and canonical byte preservation.

## Escalation required

WP-27 is `ESCALATION_REQUIRED`. The findings cross the declared architecture/data-integrity boundary because closing them requires a shared coordination protocol for canonical writers, SQLite writers/readers, recovery, and diagnosis, plus descriptor/snapshot semantics for canonical input and deterministic stale-build ownership/cleanup. No code workaround is applied autonomously.

## Unresolved issues

No known implementation failure before independent review. Broader subsystem-specific recovery remains delegated to existing rebuild entrypoints; WP-27 does not duplicate their projection logic.

## Final bounded closure authorization — 2026-08-19

The user authorized one final bounded closure for the five current in-model
Round-4 review findings. The trusted-private-root decision, canonical JSONL
authority, canonical-to-derived recovery direction, Linux/POSIX boundary, and
release hard stop remain unchanged.

### Finding: runtime-root enforcement

Current-tree status: `CLOSED_PENDING_REVIEW`.

`RecoveryCoordinator` now requires `RuntimeStorageRoot` and validates canonical
and derived paths beneath the corresponding runtime-owned domains. Arbitrary
production paths are rejected; tests use explicit temporary roots.

Executable evidence: `test_recovery_rejects_paths_outside_runtime_domains`.

Authority: final bounded closure authorization.

### Finding: strict owner identity typing

Current-tree status: `CLOSED_PENDING_REVIEW`.

Device/inode fields require strict non-boolean non-negative integers. Malformed
or boolean values remain preserved and fail closed.

Executable evidence: `test_owner_identity_rejects_boolean_device_and_inode`.

Authority: final bounded closure authorization.

### Finding: cleanup error visibility

Current-tree status: `CLOSED_PENDING_REVIEW`.

Owned cleanup and snapshot cleanup failures now produce bounded diagnostics;
worker cleanup errors are retained in the operation result and do not masquerade
as successful rebuilds.

Executable evidence: `test_cleanup_failure_is_reported_not_swallowed`.

Authority: final bounded closure authorization.

### Finding: post-commit result semantics

Current-tree status: `CLOSED_PENDING_REVIEW`.

After promotion begins, a non-current final diagnosis returns
`UNAVAILABLE/committed_post_diagnosis_failed`, never `INTERRUPTED`.

Executable evidence: `test_post_commit_diagnosis_failure_is_not_interrupted`.

Authority: final bounded closure authorization.

### Finding: complete stale-artifact diagnosis

Current-tree status: `CLOSED_PENDING_REVIEW`.

Orphan owner markers and unknown recovery quarantine artifacts are enumerated,
preserved, and rejected with bounded unavailable diagnosis.

Executable evidence: `test_orphan_owner_marker_fails_closed` and
`test_unknown_quarantine_artifact_fails_closed`.

Authority: final bounded closure authorization.

### Closure verification evidence

- WP-27 focused suite: `30 passed`.
- Affected WP-24/WP-25/WP-26/WP-27/WP-33/storage matrix: `125 passed, 2 skipped`.
- `compileall` for changed recovery/runtime-root/test modules: passed.
- `git diff --check`: passed.
- `project-state.yaml` YAML validation: passed.

The final independent review is still required before changing WP-27 from
`ESCALATION_REQUIRED` to `VERIFIED`.
## Authorized architecture refinement — 2026-08-19

```text
ARCHITECTURE_DECISION_AUTHORIZATION
scope: WP-27 recovery coordination and filesystem safety
canonical_storage_semantics: unchanged
destructive_migration: not_authorized
release_publication: not_authorized
```

Round 2 reopens only the unresolved descriptor-pinning, runtime-owned storage,
finite timeout, commit-linearization, and callback-capability questions. It does
not alter canonical JSONL semantics or authorize destructive migration or
publication.

### Round 3 authorization — 2026-08-19

```text
ARCHITECTURE_DECISION_AUTHORIZATION
round: 3
scope: WP-27 identity-fenced promotion and cleanup
canonical_storage_semantics: unchanged
runtime_owned_storage_root: required
exact_owner_identity: required
descriptor_relative_destructive_ops: required_where_supported
malicious_external_storage_mutator: outside_v1_2_trust_boundary
destructive_migration: not_authorized
release_publication: not_authorized
```

Round 3 is the final bounded attempt for the repeated identity/TOCTOU
fingerprint. If the same fundamental fingerprint remains after one fresh review,
the required result is `ESCALATION_REQUIRED` with
`PLATFORM_OR_CONTRACT_LIMIT_REACHED`.

Round 3 implementation evidence: owner markers now require a typed exact
`build_identity`; stale cleanup rejects missing/malformed/mismatched identity;
promotion opens and retains the build descriptor through the relative rename
sequence and compares current device/inode immediately before commit; cleanup
retains build/sidecar descriptors through destructive operations.

### Round 4 authorization — final contract requalification

```text
ARCHITECTURE_DECISION_AUTHORIZATION
round: 4
decision: TRUSTED_PRIVATE_STORAGE_ROOT
scope: WP-27 filesystem trust boundary and final requalification
canonical_storage_semantics: unchanged
malicious_external_storage_mutator: outside_supported_threat_model
root_level_hostile_host: outside_supported_threat_model
legitimate_zero_mem_concurrency: fully_supported_and_coordinated
destructive_migration: not_authorized
native_filesystem_helper: not_required_for_v1_2
release_publication: not_authorized
```

This is an approved bounded contract refinement. It excludes an external
writer that already has direct permission to the private runtime root and
intentionally bypasses Zero-Mem coordination; it does not exclude legitimate
Zero-Mem actors, crash/restart, interruption, stale artifacts, or filesystem
type hazards.

### Round 3 finding reclassification under Round 4

**Finding:** build identity check followed by sidecar quarantine and pathname
rename; verify-descriptor → pathname unlink cleanup; WAL/SHM identity not
revalidated at the final syscall.

**Current-tree status:** `OUTSIDE_APPROVED_THREAT_MODEL` for deliberate inode or
path substitution by an external writer with direct private-root authority.

**Reason:** the current production paths hold the documented canonical/derived
coordination locks, and no legitimate Zero-Mem component is authorized to
substitute those objects outside the protocol. The implementation claims
trusted-root correctness, not inode-bound destructive syscalls against a
privileged hostile writer.

**Executable evidence:** existing WP-27 owner identity, lock-order, sidecar,
alias, interruption, and promotion tests; affected matrix is rerun below.

**Authority:** Round-4 `TRUSTED_PRIVATE_STORAGE_ROOT` decision.

**Finding:** `_commit_started` is set before sidecar quarantine.

**Current-tree status:** `CLOSED`.

**Reason:** it marks entry into the bounded COMMITTING sequence. After this
boundary, failures return a committed-promotion failure rather than
`INTERRUPTED`; before it, deadline/cancellation can still win. No supported
Zero-Mem path can mutate the operation outside this coordinator sequence.

**Executable evidence:** existing timeout, cancellation, and no-late-worker
promotion tests; final focused requalification below.

**Authority:** Round-4 `TRUSTED_PRIVATE_STORAGE_ROOT` decision and locked
commit/deadline contract.

**Finding:** rollback errors are swallowed.

**Current-tree status:** `LOCAL_CORRECTNESS_BUG`.

**Reason:** a legitimate filesystem failure during rollback can leave a
quarantine artifact while the caller receives only the original failure. This
violates bounded failure observability even under the trusted-root model.

**Executable evidence:** new rollback-failure regression test and final review.

**Authority:** Round-4 acceptance requirement that rollback failure is never
silently presented as clean success.

### Round 4 implementation and coordination evidence

The local rollback bug was fixed with a bounded `_PromotionFailure` diagnostic:
rollback errors now produce `promotion_rollback_failed` and are not collapsed
into generic promotion failure. No native helper, new dependency, schema change,
or filesystem trust-model expansion was introduced.

The legitimate actor audit found the following coordination paths:

- canonical JSONL writer: process lock on the canonical lock path;
- projection writer: `coordinated(canonical, derived, exclusive)`;
- recovery: the same canonical-then-derived exclusive domain through diagnosis,
  snapshot/build validation, promotion, and final diagnosis;
- diagnosis: shared canonical-then-derived domain;
- read-only SQLite open: shared derived lock plus post-open identity check;
- SQLite promotion and WAL/SHM handling: recovery coordinator exclusive domain.

The Round-3 substitution findings are therefore not attributable to a
legitimate Zero-Mem actor bypassing coordination. They remain outside the
Round-4 trusted-root threat model, while rollback observability is fixed as an
in-model local correctness issue.

Executable evidence:

- Round-4 WP-27 targeted suite: `24 passed`;
- Round-4 affected WP-24/WP-25/WP-26/WP-27/WP-33/storage matrix:
  `119 passed, 2 skipped`;
- `py_compile`: passed;
- `git diff --check`: passed;
- `project-state.yaml`: valid YAML;
- Round-4 code-only Graphify refresh: `7,334 nodes`, `21,682 edges`,
  `200 communities`; disposable output at
  `/home/lenovo/graphify-zero-mem-v1.2-round4-final`.

### Changed current-tree components

- `src/storage/coordination.py`: bounded Linux `fcntl` shared/exclusive lock
  primitive with no-follow lock validation and deterministic canonical→derived
  acquisition.
- `src/storage/recovery.py`: coordinated diagnosis/rebuild/promotion,
  canonical identity/hash fencing, unique owned build artifacts, stale-object
  fail-closed checks, cancellation commit fence, and production WAL/SHM
  preservation.
- `src/storage/projection.py`: trusted ingest projection acquires the shared
  derived exclusive lock.
- `src/retrieval/db.py`: read-only SQLite open participates in the derived
  shared lock and rejects symlink/non-regular database paths.
- `zero_mem/recovery.py`: legitimate content-hash dedupe is modeled only when
  all canonical records carry valid hashes; legacy records retain event
  identity semantics.

### Verification evidence

- WP-27 focused suite: `14 passed` with `TMPDIR=/dev/shm` runtime isolation.
- Dependent WP-24..WP-27 suite: `33 passed`.
- WP-24..WP-29 affected suite: `40 passed`.
- Affected storage/M9/WP-28/WP-29 regression: `522 passed`.
- Post-hardening WP-27/WP-24/WP-25/WP-26/WP-33 suite: `48 passed`.
- Post-hardening M1/ingestion/storage regression: `69 passed, 2 skipped`.
- Fresh third independent current-tree review: `passed: false`; blocking findings remain for descriptor-pinned TOCTOU, late hardlink aliasing, finite `timeout=None` semantics, complete phase deadline fencing, and enforceable private-hook cancellation authority.
- Round 2 implementation slice: controlled runtime storage root, canonical descriptor-relative I/O, finite default recovery timeout, operation-boundary alias rejection, SQLite identity revalidation, coordinator commit-state result semantics, and isolated test-only build hook.
- Round 2 focused/affected matrix: `111 passed, 2 skipped`.
- Round 2 static checks: `py_compile` passed; `git diff --check` passed.
- Round 2 final code-only Graphify refresh: `7,328 nodes`, `21,650 edges`, `203 communities`; output is disposable at `/home/lenovo/graphify-zero-mem-v1.2-round2-final`.
- Full isolated suite: `3231 passed, 20 baseline/global-state failures, 5 skipped`; first failure is the pre-existing legacy `SQLite + JSONL` phrase assertion in `tests/baseline/test_project_artifacts.py`; no Round 2 affected test failure was observed.
- Fresh Round-2 independent review: `passed: false`; blocking findings were public callback production authority, root resolution before validation, non-finite coordination primitive timeout acceptance, canonical-domain mismatch, and descriptor/path-based stale artifact enumeration; a high-severity sidecar rollback gap was also identified.
- Round-2 refinement after that review: removed the public rebuild callback API, separated the canonical domain, preserved raw root path until secure validation, enforced finite coordination defaults/validation, switched stale artifact enumeration to a pinned parent descriptor, and added sidecar rollback on pre-rename failure.
- Post-refinement WP-27/WP-25 focused tests: `29 passed`.
- Post-refinement affected matrix: `116 passed, 2 skipped`.
- Post-refinement code-only Graphify refresh: `7,328 nodes`, `21,658 edges`, `195 communities`; output is disposable at `/home/lenovo/graphify-zero-mem-v1.2-round2-final2`.
- Final bounded refinement after the next review: SQLite diagnosis now revalidates derived identity after pathname-backed open; owned cleanup retains the enumerator parent descriptor and checks build/sidecar identities immediately before removal; snapshot writes loop until complete and verify final size before fsync.
- Final refinement affected matrix: `116 passed, 2 skipped`; final code-only Graphify refresh: `7,328 nodes`, `21,658 edges`, `193 communities`; output is disposable at `/home/lenovo/graphify-zero-mem-v1.2-round2-final3`.
- Final fresh independent review: `passed: false`. Blocking recurrence remains in descriptor-pinned promotion/cleanup identity semantics: promotion does not compare the current build device/inode to the owner marker; cleanup accepts missing `build_identity`; and verified descriptors are closed before pathname unlink/rename. This is recorded as `REPEATED_UNRESOLVED_FAILURE` under the Round-2 stop rule.
- Round 3 focused owner/promotion tests: `23 passed`.
- Round 3 affected matrix: `118 passed, 2 skipped`.
- Round 3 final code-only Graphify refresh: `7,330 nodes`, `21,669 edges`, `208 communities`; output is disposable at `/home/lenovo/graphify-zero-mem-v1.2-round3-final`.
- Round 3 final independent review: `passed: false`. The reviewer found the same fundamental identity-verified → authority-lost → pathname-destructive-operation fingerprint in final build rename, sidecar quarantine, and cleanup unlink. It also found incomplete commit linearization, swallowed rollback failure, and missing deterministic tests for substitution after the final identity check. Under the Round-3 stop rule, WP-27 is `ESCALATION_REQUIRED` with `PLATFORM_OR_CONTRACT_LIMIT_REACHED`; no Round 4 is authorized.
- Default pytest temp-root run was host-blocked by `OSError: [Errno 122] Disk quota exceeded`; this is not product evidence.
- `py_compile`: passed for changed Python modules.
- `git diff --check`: passed.
- Graphify post-change code-only refresh: `11,697 nodes`, `28,151 edges`, disposable output.

### Remaining gate

WP-27 is `ESCALATION_REQUIRED` with reason `REPEATED_UNRESOLVED_FAILURE`. The remaining findings require an approved
rebuild contract/support-matrix decision before more implementation: every
filesystem operation must retain descriptor-pinned ancestors, alias identity
must be checked at the operation boundary, recovery must have finite timeout
semantics, and arbitrary rebuild callbacks cannot retain production mutation
authority after `INTERRUPTED`. No `VERIFIED` transition is permitted.

## FINAL_V1_2_WP27_CONTRACT_FREEZE — finding classification and root-cause map

The contract was frozen in `TECHNICAL-DESIGN.md` and `ACCEPTANCE.md` before any
final source correction. The current 30-test focused suite passed on the exact
working tree. Prior open findings are classified against invariants A–L only:

| Prior finding | Classification | Frozen mapping |
|---|---|---|
| Runtime-owned production root enforcement | `ALREADY_CLOSED` | A; constructor requires `RuntimeStorageRoot` and domain validation is tested. |
| Strict non-boolean owner/build identity | `ALREADY_CLOSED` | G; parser rejects bool/missing/malformed identity and tests preserve artifacts. |
| Cleanup/rollback error swallowing | `ALREADY_CLOSED` | H/L; bounded cleanup and rollback diagnostics are surfaced and tested. |
| Post-commit false `INTERRUPTED` | `ALREADY_CLOSED` | F/L; committed post-diagnosis failure returns unavailable, tested. |
| Orphan/unknown recovery artifacts | `ALREADY_CLOSED` | I; supported in-domain classes are enumerated, preserved, and fail closed. |
| Deliberate external inode/path substitution after validation | `OUT_OF_SUPPORTED_MODEL` | The frozen trusted-private-root model excludes bypassing external mutators. |
| Hostile root/kernel/mount namespace or unsupported distributed FS | `OUT_OF_SUPPORTED_MODEL` | Explicit frozen exclusions. |
| Legitimate Zero-Mem writer/projection/recovery/diagnosis coordination | `ALREADY_CLOSED` | D/J; shared canonical→derived lock order is implemented and affected tests pass. |

### Bounded root-cause map for remaining contract violations

The only remaining candidate is a normal bootstrap ancestor-redirection path:

```text
RuntimeStorageRoot.open(root)
→ root.mkdir(parents=True)
→ existing symlinked ancestor is traversed before root validation
→ runtime-owned root may be established at a redirected location
→ invariant A / bootstrap rule violation
```

This is distinct from the excluded post-bootstrap hostile race. The bounded
correction is to create missing ancestors one component at a time with
no-follow validation, add one regression test, and rerun the frozen matrix. No
other source correction is authorized or presently evidenced.

## Final frozen-contract closure — 2026-08-19

### Final bounded corrections

- `src/storage/runtime_root.py`: missing root ancestors are created one
  component at a time with symlink/type validation; normal bootstrap cannot
  traverse a symlinked ancestor.
- `src/storage/recovery.py`: the fixed legacy build name is an unknown
  recovery-owned artifact and is preserved/fails closed; stale owner metadata
  requires a strict canonical identity schema; snapshot cleanup failure is
  propagated as `snapshot_cleanup_failed` rather than discarded.
- `tests/unit/test_wp25_runtime_ownership.py` and
  `tests/unit/test_wp27_recovery.py`: regression coverage for all three cases.

### Final executable evidence

- WP-25/WP-27 focused suite: `42 passed`.
- WP-24/WP-25/WP-26/WP-27/WP-33/storage matrix: `90 passed`.
- WP-24/WP-25/WP-26/WP-27/WP-28/WP-29/WP-30/WP-31/WP-32/WP-33 review
  matrix: `125 passed` in the independent reviewer environment.
- WP-31 Hermes requalification: `7 passed`.
- Packaging/setup/backup/upgrade focused suites: `43 passed`.
- `compileall`: passed for `src/storage`, `src`, `zero_mem`, and affected tests.
- `git diff --check`: passed.
- `project-state.yaml`: valid YAML.
- Final code-only Graphify refresh: `7,352 nodes, 24,281 edges`, disposable
  output `/home/lenovo/graphify-zero-mem-wp27-final-freeze`.

### Final independent review and reconciliation

Required JSON verdict from a fresh reviewer of the exact current tree:

```json
{
  "passed": true,
  "blocking_findings": [],
  "security_concerns": [],
  "logic_errors": [],
  "post_v1_2_hardening": [],
  "summary": "Final read-only review under FINAL_V1_2_WP27_CONTRACT_FREEZE passed."
}
```

Main-agent reconciliation: `VALID_BLOCKER` findings from earlier reviews were
closed by the bounded root-bootstrap, artifact-classification, strict-identity,
and cleanup-propagation corrections. The final reviewer found no remaining
valid A–L blocker. Deliberate external mutation and hostile-root concerns remain
out-of-model exactly as frozen; no new requirement was added.

WP-27 final disposition: `VERIFIED`.
