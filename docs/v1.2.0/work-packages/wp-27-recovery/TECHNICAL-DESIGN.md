# WP-27 Technical Design

**Status:** VERIFIED — final contract frozen

## Authorization and locked semantics

```text
ARCHITECTURE_DECISION_AUTHORIZATION
scope: WP-27 recovery coordination and filesystem safety
canonical_storage_semantics: unchanged
destructive_migration: not_authorized
release_publication: not_authorized
```

JSONL remains the sole canonical memory-event source. SQLite/FTS/indexes are derived and rebuildable. Recovery is canonical → derived only; no canonical rewrite, destructive migration, unrelated refactor, or publication is in scope.

### Round 2 production storage decision

Production-qualified storage is runtime-owned under one approved root:

```text
ZERO_MEM_HOME/
  canonical/
  derived/
  recovery/
  locks/
  metadata/
```

Configured legacy paths may be accepted only during safe bootstrap and must be normalized into this root; unsupported arbitrary path mode fails closed rather than claiming equivalent guarantees. Pathnames are bootstrap identifiers only. After secure open, descriptors, verified identities, and runtime-owned handles are operational authority. The guarantee is Linux/POSIX-first and covers cooperating Zero-Mem components and tested untrusted path objects inside the controlled root, not an omnipotent privileged host attacker or unsupported network filesystem.

Recovery state machine:

```text
IDLE → SNAPSHOT → BUILDING → READY_TO_COMMIT → COMMITTING → COMMITTED
                         ↘ CANCELLED / INTERRUPTED
```

`COMMITTING` is the commit linearization region. Before it, cancellation may return `INTERRUPTED`; after it begins, the bounded commit finishes and the result reports committed success/failure, never a misleading no-change `INTERRUPTED`. Only `RecoveryCoordinator` owns production promotion and production WAL/SHM quarantine.

### Round 3 identity-fenced promotion and cleanup

Owner metadata requires an exact `build_identity` containing device and inode;
missing or malformed identity is untrusted and never authorizes destructive
cleanup or promotion. One internal promotion primitive performs owner-marker
validation, current build `fstat`, identity comparison, generation/deadline
checks, sidecar handling, and relative rename under the controlled derived
directory authority. Cleanup follows the same exact-owner rule and preserves
the pinned parent-directory authority for its destructive sequence.

The v1.2 trust boundary covers cooperating Zero-Mem processes, stale artifacts,
symlink/type failures, crash/interruption, and accidental aliasing inside the
runtime-owned private storage domains. It excludes root-level hostile hosts,
privileged external mutators intentionally racing private inodes, mount
namespace attacks, and unsupported network/distributed filesystems. No stronger
guarantee is claimed than the tested Linux/POSIX primitives provide.

### Round 4 trusted private storage-root contract

The private runtime-owned root is trusted against an external process that
already has direct write permission and intentionally bypasses Zero-Mem
coordination. Such inode/path substitution is outside the v1.2 threat model and
is not a qualification blocker. This does not weaken internal guarantees:
canonical writers, projection writers, recovery, diagnosis, SQLite promotion,
and supported readers must use the documented coordination domain. Rollback and
error states remain observable and bounded; a failed rollback must not be
presented as clean success.

SQLite's Python URI API remains pathname-backed; it cannot portably consume a
directory/file descriptor. Read-only access therefore uses the controlled root,
descriptor-relative no-follow identity capture immediately before open, shared
coordination, and identity revalidation after open. This is a documented
pathname API limitation, not a claim of descriptor-only SQLite access.

## Technologies and dependencies

- Python 3.11 standard library and existing SQLite/WAL implementation.
- Linux-qualified `fcntl.flock`, `os.open` no-follow flags, `os.lstat`, `os.fstat`, and directory-relative rename where supported.
- Existing `SQLiteStore`, `src.storage.ingest.rebuild_from_jsonl`, and `zero_mem.recovery.diagnose` remain the subsystem authorities.
- No new third-party dependency and no schema migration.

## Shared coordination model

Add a small `src.storage.coordination` primitive for one explicit coordination domain per canonical/derived pair:

- canonical lock: `<canonical>.lock`, shared with the existing JSONL append writer;
- derived lock: `<derived>.lock`, shared by projection writes, read-open/diagnosis, recovery build, and promotion;
- `fcntl.flock`: shared mode for read-open/diagnosis, exclusive mode for canonical append, projection writes, recovery, and promotion;
- deterministic acquisition order: canonical lock, then derived lock; release in reverse order;
- finite acquisition timeout; failure returns a sanitized unavailable status;
- lock files are opened with `O_NOFOLLOW|O_CREAT|O_RDWR`, must be regular files, and are mode `0600`;
- unsupported platforms fail closed rather than silently weakening the protocol.

The runtime owns configured paths. No global mutable writer or second canonical store is introduced. Projection's trusted ingest callback acquires the derived exclusive lock. Read-only open/diagnosis acquires the derived shared lock while establishing its coherent database generation. Recovery holds the complete domain through diagnosis, build-input validation, promotion, and final diagnosis.

## Canonical snapshot / identity boundary

At the coordinated start of recovery, record canonical `lstat` identity, regular-file type, size, mtime-ns, and SHA-256, then create an owned immutable snapshot using no-follow exclusive creation. The worker ingests only that snapshot, never a later pathname reopen of canonical JSONL. Recheck canonical identity, size, mtime-ns, and hash immediately before promotion and again for the final diagnosis. A replacement, append, truncation, alias, symlink, non-regular object, or parent redirection detected by these checks fails closed without promotion.

This is an in-memory consistency boundary, not a second canonical truth. Cooperative appends wait on the shared canonical lock. A non-cooperating append/replacement is detected by identity/hash validation and causes a safe failure. Later canonical appends after a successful snapshot are represented by a later stale projection pass.

## Filesystem safety

Validate final paths and every existing parent with `lstat`; reject symlinks, dangling links, non-regular files, canonical/derived aliasing, and unsafe parent redirection. Use no-follow opens and directory-relative operations where available. Never delete an arbitrary object based only on a matching filename.

Recovery builds use a unique token and an ownership marker containing the canonical identity, derived destination, owner PID, and build token. Cleanup is allowed only for a verified regular, non-symlink artifact whose marker matches this coordinator. Unknown, hostile, or non-regular artifacts cause fail-closed unavailable status and are preserved.

Production WAL/SHM sidecars are not deleted during promotion. The new database is atomically published under the derived exclusive lock; old-reader sidecars remain tied to the old inode and are handled only by a later ownership-verified cleanup operation.

## Algorithm and state transitions

```text
acquire canonical + derived coordination
→ validate paths and capture canonical identity/hash
→ diagnose coherent canonical/derived generation
→ if rebuild required, create unique owned disposable SQLite build
→ rebuild from canonical read-only input using existing ingest entrypoint
→ close build and verify build identity/schema/checkpoint
→ revalidate canonical identity/hash and cancellation fence
→ atomically publish build, without deleting production WAL/SHM
→ diagnose the same coordinated generation
→ return REBUILT/CURRENT or sanitized UNAVAILABLE/INTERRUPTED
```

Existing public statuses remain: `CURRENT`, `MISSING`, `STALE`, `CORRUPT`, `INCOMPATIBLE`, `INTERRUPTED`, `REBUILT`, and `UNAVAILABLE`.

## Timeout and cancellation

One caller-owned deadline covers lock acquisition, diagnosis, build, identity validation, and promotion. The worker may finish only inside its unique disposable build artifact. It receives no production path or promotion authority. Before returning `INTERRUPTED`, the coordinator sets a cancellation/commit fence; promotion checks that fence and the canonical identity under the coordination lock. A late worker can never replace the production database, delete production sidecars, or update production checkpoints. Its owned temporary artifact is cleaned after completion only if ownership remains verified.

No infinite wait, retry, or detached production mutation is allowed. A stale owned build from a crash is safely reclaimable on the next attempt; an unknown or hostile object blocks recovery.

## Diagnosis consistency and deduplication

`diagnose()` runs inside the same coordination protocol as projection writes and promotion. It compares checkpoint prefix identity, canonical event identities/sequences, derived logical rows, and watermark/generation metadata. It does not use `derived row count == canonical event count` as its sole invariant because `sanitized_content_hash` deduplication can legitimately produce fewer derived rows than canonical events. Legitimate duplicate outcomes are evaluated using the real ingestion log/checkpoint semantics.

`CURRENT` means the diagnosed derived generation corresponds to the pinned canonical snapshot and the verified checkpoint/watermark. A later canonical append is `STALE`, not silently current.

## Database / promotion protocol

The rebuild database is created with the existing schema/migration path in a unique sibling artifact. Build and projection writes hold the derived exclusive coordination lock. Read-only connections are established under the derived shared lock. Promotion opens the derived parent directory with no-follow semantics, validates marker/build/destination identities relative to that descriptor, renames existing regular WAL/SHM sidecars to owned quarantine names, and then atomically renames the build into place. Quarantining preserves old-reader handles while preventing filename-associated sidecars from being inherited by the new database. Unknown or non-regular sidecars fail closed.

## Compatibility, rollback, and limitations

No schema or public contract changes are planned. The new coordination helper is disposable and removable without changing canonical events. Linux with `fcntl` is the qualified platform; unsupported platforms return bounded unavailable rather than claiming equivalent safety. A single absolute deadline is propagated through both lock acquisitions, diagnosis, build, validation, and promotion. If descriptor-relative/no-follow or coordinated SQLite promotion cannot be implemented without weakening the locked invariants, stop with `ESCALATION_REQUIRED`.

`timeout=None` resolves to a finite runtime-owned default, documented by runtime configuration and validated like explicit timeouts. Arbitrary rebuild callbacks are not production capabilities; the production path uses an owned build implementation returning only an isolated build handle to the coordinator.

## Prohibited approaches

No canonical rewrite, SQLite-to-canonical repair, silent fallback, infinite retry, destructive purge, hidden migration, arbitrary symlink cleanup, detached production mutation, or alternate per-subsystem recovery pipeline.

## Final bounded closure authorization

The final bounded closure is limited to the five in-model findings from the
Round-4 replacement review. `RecoveryCoordinator` now requires a validated
`RuntimeStorageRoot` and accepts canonical paths only below `canonical/` and
derived paths only below `derived/`; arbitrary production paths have no recovery
authority. Test fixtures construct an explicit temporary runtime root.

Owner `device` and `inode` fields use strict non-boolean integer validation.
Cleanup and snapshot-removal failures surface bounded diagnostics rather than
being silently ignored. After commit linearization, post-promotion diagnosis
failure is reported as `UNAVAILABLE/committed_post_diagnosis_failed`, never as a
pre-commit `INTERRUPTED` result. Stale-artifact diagnosis rejects orphan owner
markers and unknown recovery quarantine artifacts while preserving them.

This closure does not change the trusted-private-root model, canonical JSONL
semantics, recovery direction, supported Linux/POSIX boundary, or release hard
stop.

## FINAL_V1_2_WP27_CONTRACT_FREEZE

**Status:** FROZEN FOR FINAL VERIFICATION — no moving goalposts.

### Supported model

Production storage operates under a trusted runtime-owned private
`RuntimeStorageRoot` containing the canonical, derived, recovery, locks, and
metadata domains. Legitimate Zero-Mem processes use the approved coordination
model on qualified local POSIX/Linux filesystem semantics. External actors do
not maliciously mutate private storage while bypassing Zero-Mem coordination.
JSONL remains the sole canonical append-only memory-event source; SQLite/FTS and
other projections are derived and rebuildable, and recovery is canonical →
derived only.

### Out-of-model conditions

Root-level hostile operating systems, hostile kernels or mount namespaces,
privileged/direct external mutation that deliberately bypasses coordination,
unsupported network/distributed filesystems, and arbitrary privileged mutation
outside runtime-owned domains are threat-model limitations, not WP-27 blockers.

### Required invariants

- **A — Runtime root:** production recovery/storage paths are rooted in and
  validated against `RuntimeStorageRoot`; no production path escape.
- **B — Canonical immutability:** recovery never rewrites, truncates, replaces,
  repairs, or reconstructs canonical history from derived state.
- **C — Coherent canonical input:** recovery builds and validates one coherent
  canonical snapshot/generation, with documented watermark semantics for appends.
- **D — Legitimate coordination:** all legitimate canonical writers, projection
  writers, recovery, diagnosis, promotion, and overlapping derived readers use
  the approved coordination domain.
- **E — Bounded recovery:** retries and waits are finite; omitted, invalid,
  NaN, and infinite timeouts resolve or fail validation deterministically.
- **F — Interrupted semantics:** `INTERRUPTED` is pre-commit only and cannot be
  followed by promotion by the same operation.
- **G — Owner identity:** owner and participating canonical/snapshot identities
  use strict schemas; booleans are rejected as integer identities; malformed or
  missing identity never authorizes promotion or destructive cleanup.
- **H — Cleanup visibility:** in-model cleanup failures are bounded, visible,
  diagnosable, and cannot masquerade as clean success.
- **I — Stale artifacts:** supported recovery-owned artifacts have deterministic
  ownership, provenance, lifecycle, stale, cleanup, and unknown-artifact policy.
- **J — SQLite/WAL/SHM:** legitimate writer/recovery interaction never mixes
  generations; sidecars follow coordinated crash/restart handling.
- **K — Restart/idempotence:** supported interruption/crash recovery is bounded,
  restartable, repeatable, and rebuilds only from canonical truth.
- **L — Status correctness:** statuses truthfully represent committed/current,
  unavailable, failed, and interrupted outcomes; no false success.

### Reviewer rules

A blocker must identify one invariant A–L, an exact supported execution path,
current source logic, and reproducible evidence. Concerns requiring a new
guarantee or excluded hostile actor are post-v1.2 hardening. No new WP-27
invariant may be added without higher-authority conflict or
`ESCALATION_REQUIRED / NEW_REQUIREMENT_OUTSIDE_FROZEN_CONTRACT`.
