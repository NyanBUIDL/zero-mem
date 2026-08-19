# WP-27 Implementation Plan

**STATUS: VERIFIED**

## Architecture decision authorization

```text
ARCHITECTURE_DECISION_AUTHORIZATION
scope: WP-27 recovery coordination and filesystem safety
canonical_storage_semantics: unchanged
destructive_migration: not_authorized
release_publication: not_authorized
```

This bounded authorization resolves the recorded WP-27 escalation only. It does not reopen verified WPs, change ADR-009, make SQLite canonical, rewrite JSONL, or authorize release publication.

## Architecture decision authorization — Round 2

```text
ARCHITECTURE_DECISION_AUTHORIZATION
round: 2
scope: WP-27 descriptor-pinned storage and recovery commit fencing
canonical_storage_semantics: unchanged
runtime_owned_storage_root: approved
descriptor_pinned_production_access: approved
coordinator_only_promotion: approved
finite_default_timeout: approved
destructive_migration: not_authorized
release_publication: not_authorized
```

Round 2 authorizes only the controlled production storage root, descriptor-pinned access, coordinator-only promotion, finite timeout defaults, explicit commit linearization, and removal of arbitrary production callback authority.

## Architecture decision authorization — Round 3

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
fingerprint. It authorizes only mandatory owner identity, one internal
identity-fenced promotion primitive, exact-owner cleanup, and the documented
Linux/POSIX trust boundary.

## Architecture decision authorization — Round 4 / final contract requalification

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

Round 4 is the final v1.2 contract requalification. The runtime-owned private
root is trusted against arbitrary external writers with direct write authority;
the implementation must still fully coordinate legitimate Zero-Mem actors,
crashes, interruption, stale artifacts, object hazards, and restart behavior.
No inode-bound rename/unlink guarantee is claimed beyond the Linux/POSIX
primitives actually used.

## Baseline

- Workspace: `/home/lenovo/Hermes Workspace/zero-mem-v1.1`
- Baseline SHA: `7d871a95017c250f2d27a6e284ccfc6ad6f3c02e`
- Dependencies WP-25/WP-26: `VERIFIED`
- Existing evidence: `src/storage/ingest.py` has `diagnose`/checkpoint validation and `rebuild_from_jsonl`; `src/project_memory/rebuild.py` and `src/access/rebuild.py` provide bounded derived rebuilds; SQLite backup APIs exist.

## Gap

There is no single WP-27 recovery coordinator that classifies missing/stale/corrupt/incompatible derived state, coordinates rebuild atomically, or records interrupted recovery outcomes without mutating canonical JSONL.

## Current-tree gap analysis

- Recovery has independent canonical/derived locks, but projection writes and read diagnosis do not share one explicit coordination domain.
- Canonical JSONL and derived/build paths are reopened by name after check-then-use validation.
- The timeout worker can continue isolated build work after `INTERRUPTED`, but its artifact identity and cleanup ownership are not explicit enough for safe restart semantics.
- Fixed `.recovery-building` naming makes stale artifacts block future work.
- Diagnosis is not serialized with projection writes, reader-open, and promotion, and its count comparison does not model legitimate content-hash deduplication.

## Increments

1. Define typed `RecoveryStatus`, `RecoveryDiagnosis`, and explicit source/checkpoint identity.
2. Implement read-only diagnosis over existing derived metadata/schema/checkpoint helpers.
3. Implement bounded rebuild orchestration using existing rebuild functions and SQLite backup/transaction boundaries.
4. Add one explicit Linux coordination domain shared by canonical append, projection writes, read-open/diagnosis, rebuild, and promotion; document lock ordering and bounded acquisition.
5. Pin canonical identity/size/hash across diagnosis and rebuild, use unique owned recovery-build artifacts, and fence late workers from promotion or production-sidecar mutation.
6. Add tests for missing, stale, corrupt, incompatible, canonical mutation, concurrent append, deadline, path/symlink, sidecar, deterministic rebuild, restart, dedupe semantics, and no infinite retry.

## Expected files

- `src/storage/recovery.py` (new or narrow extension if an existing recovery boundary is authoritative).
- `tests/unit/test_wp27_recovery.py` (new).
- Planning/evidence/state docs.

## Compatibility and migration

No new schema or dependency planned. Existing `zm_migrations`, `zm_ingest_checkpoint`, and canonical prefix hashes remain authoritative inputs for diagnosis. If a schema change is required, stop and reconcile before implementation.

## Security/data integrity

Recovery accepts explicit canonical paths from runtime-owned configuration, uses descriptor-relative/no-follow validation where supported, verifies object identity before promotion, sanitizes status, and never writes canonical JSONL. Derived build files are unique, owned disposable artifacts; stale cleanup only removes verified regular files with the coordinator's ownership marker.

## Rollback

Recovery coordinator is disposable; remove it without altering canonical events. Existing rebuild functions remain available.

## Test strategy

TDD against each failure class, canonical byte/hash preservation, rebuild parity, interrupted transaction/backup, restart, and no infinite retry. Run WP-24/25/26 plus storage/recovery regression and isolated full suite.

## Implementation deviations

The implementation uses a temporary SQLite build plus caller-thread atomic promotion rather than a separate persistent recovery marker or subsystem-specific backup API. This preserves the required fail-closed/no-partial-current invariant without adding schema or dependency scope. Existing `zero_mem.recovery.diagnose` remains the diagnosis authority.


## Plan validation

Validated against Master Plan Phase 1 §1.3, ADR-009, current ingestion/rebuild modules, WP-25 runtime ownership, and WP-26 verified projection boundary. The authorization changes coordination implementation only; canonical direction and derived-state semantics are unchanged.

## Final bounded closure authorization

The approved final closure changes only WP-27. It requires root-bound
`RecoveryCoordinator` construction from `RuntimeStorageRoot`, strict typed owner
identity, deterministic cleanup diagnostics, committed post-diagnosis result
semantics, and complete orphan/quarantine artifact diagnosis. No native helper,
destructive migration, unrelated WP changes, or publication action is allowed.

Current final disposition: `VERIFIED`, supported by the final bounded-closure evidence and exact-tree independent review recorded in `EVIDENCE.md`.

Earlier escalation findings remain historical and are not reopened by this documentation reconciliation.
