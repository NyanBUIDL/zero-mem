# 03 — Strict delivery protocol

## Phase 0: establish an auditable baseline

Before editing:

1. Record `git rev-parse HEAD`, branch, clean/dirty state, Python version, OS version and SQLite/FTS availability.
2. Read the package record, prerequisites and source/test map.
3. State the narrow change intent: one invariant, one owner, one acceptance boundary.
4. Add the acceptance and negative tests before, or in the same atomic change as, the implementation.
5. Check the existing test proves the desired behavior rather than merely preserving an old stub.

An evidence record must include command, exit code, elapsed time, exact source SHA, platform, Python version, raw-log path/checksum and changed file list. Never copy a pass count from another commit.

## Phase 1: design before implementation

Each package must define:

- API/input-output contract and backward-compatibility impact.
- Owner of every resource: JSONL writer, SQLite connection, worker, lock, timer, executor and temporary artifact.
- Failure vocabulary and which errors are sanitized.
- Authorization point and proof that it precedes candidate discovery.
- Freshness policy: required consistency level, bounded wait, stale response and watermark fields.
- Platform behavior: supported, explicitly unsupported, or fail-closed. “Best effort” is not a release claim.
- Rollback/cleanup behavior and any migration/rebuild consequence.

An agent must submit this design for review when it changes an invariant, public contract, on-disk format, lock/path primitive or Hermes host interface.

## Phase 2: implementation rules

- Make the smallest vertical slice. Do not combine refactors, new features, formatting sweeps and a correctness fix.
- Keep `zero_mem` public modules transport/storage-neutral. Depend on protocol interfaces and injected services, not `src` implementation imports.
- Reuse `AuthorizedReadService`, ingestion, recovery and sidecar owners. No duplicate query, policy or canonical-writer paths.
- Bound queues, timeouts, retries, allocations and executor lifetime. `while True`, retry loops, background threads and process locks require a finite exit condition and test.
- Preserve immutable canonical events. A repair creates/derives state; it never edits historical JSONL lines.
- Never log request payloads, unredacted exceptions, absolute home paths, credentials, or raw user secret data in fixtures/evidence.

## Phase 3: verification ladder

Run, in this order:

1. Static/import/format checks for changed modules.
2. New focused unit tests.
3. Dependency tests named in [02-CODE-AND-TEST-MAP.md](02-CODE-AND-TEST-MAP.md).
4. Failure, security, concurrency and restart tests.
5. Direct API → sidecar → Hermes parity E2E where the package touches a public path.
6. Platform matrix rows affected by the change.
7. Full isolated regression and clean-install smoke before release qualification.

A failure is classified as `PRODUCT`, `TEST`, `ENVIRONMENT`, or `UNSUPPORTED_PLATFORM` only with reproduction and rationale. A classification does not waive an affected release gate.

## Phase 4: evidence and status

Use [07-WORK-PACKAGE-TEMPLATE.md](07-WORK-PACKAGE-TEMPLATE.md). The package can become `VERIFIED` only when every acceptance item is mapped to executable evidence. An independent reviewer must inspect the diff, failure paths, evidence reproducibility and all modified public boundaries.

## Prohibited shortcuts

- Do not replace a failing behavioral test with an assertion that a capability is unavailable.
- Do not hide platform failures by unconditional skip. A skip must be tied to declared support policy and covered by a visible matrix row.
- Do not make a global runtime state satisfy a local adapter configuration.
- Do not call internal SQLite/FTS code directly from public API or transport code to avoid authorization/freshness checks.
- Do not call an external host integration “production” based only on a local mock with a narrower contract.
