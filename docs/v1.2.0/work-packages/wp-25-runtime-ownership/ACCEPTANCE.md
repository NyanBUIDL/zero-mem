# WP-25 Acceptance

**STATUS: VERIFIED**

## Functional acceptance

- [x] Enabled runtime opens one canonical writer for the configured root.
- [x] Disabled runtime opens no writer and reports `ZERO_MEM_DISABLED`.
- [x] Registration adapter consumes the runtime-owned writer.
- [x] Runtime close releases the writer and is idempotent.

## Negative and failure-path acceptance

- [x] Writer access after close fails with a typed runtime error.
- [x] Writer construction failure does not produce an open runtime.
- [x] Adapter shutdown does not recreate or silently replace the writer.
- [x] Existing canonical append failure behavior remains fail-closed.

## Security/data-integrity acceptance

- [x] No adapter-local `JsonlCaptureStore` construction remains in the production path.
- [x] No path inference from cwd, request payload, or arbitrary environment occurs.
- [x] Runtime does not write SQLite/derived state or mutate canonical history during shutdown.

## Regression acceptance

- [x] WP-25 focused tests pass.
- [x] Existing M7.1, M1, WP-02, WP-08, WP-11, WP-14, and WP-24 tests pass.
- [x] Isolated full suite has no new failures.
- [x] `compileall` and `git diff --check` pass.

## Review and evidence gate

- [x] Independent review has no blocking security or logic findings.
- [x] EVIDENCE.md records actual commands/results and pre-existing baseline deviations.
- [x] Project state and WP index are updated only after executable evidence exists.

## Exit gate

Transition to `VERIFIED` only when every checked item above passes and no escalation boundary is active.
