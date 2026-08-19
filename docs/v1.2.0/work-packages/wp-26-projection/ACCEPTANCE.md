# WP-26 Acceptance

**STATUS: VERIFIED**

## Acceptance objectives

- [x] A coordinator provides a bounded queue and explicit worker lifecycle.
- [x] Successful canonical append remains independent from projection availability.
- [x] Derived watermark advances only after committed ingestion/checkpoint state.
- [x] Currentness is explicit and never inferred from queue acceptance.

## Functional tests

- [x] Submit accepted notification reaches derived ingestion and becomes current.
- [x] Multiple notifications are processed deterministically.
- [x] Flush returns a bounded status and close is idempotent.

## Failure-path tests

- [x] Queue full returns `DERIVED_PENDING` without altering canonical truth.
- [x] Worker/ingestion failure returns `DERIVED_UNAVAILABLE` and stops retrying.
- [x] Close/flush timeout does not deadlock or leak a worker.
- [x] Missing/stale derived state is not reported current.

## Security/data-integrity tests

- [x] Canonical JSONL bytes remain unchanged by projection.
- [x] Source identity/path is explicit and no cwd/request path inference occurs.
- [x] Diagnostics contain no payload, secret, or exception text.
- [x] SQLite remains derived and rebuildable.

## Regression requirements

- [x] WP-24 and WP-25 focused/regression tests pass.
- [x] Existing M1/M2/M8.1 storage tests pass.
- [x] Isolated full suite has no new failures.
- [x] `compileall` and `git diff --check` pass.

## Exit gate

Transition to `VERIFIED` only after all checks, independent review, evidence, and project-state update pass without escalation.
