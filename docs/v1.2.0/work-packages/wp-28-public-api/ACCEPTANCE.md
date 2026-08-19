# WP-28 Acceptance

**STATUS: VERIFIED**

## Functional

- [x] Public generic caller can open, start a session, observe message/tool calls, sync, health-check, and shutdown using only `zero_mem` imports.
- [x] Four standard capabilities return typed, deterministic unavailable results until their owning WPs implement them.
- [x] API version is stable and independent of package patch version.

## Negative/failure

- [x] Invalid identity/session/payload/configuration/deadline/queue values fail with typed errors or sanitized typed status.
- [x] Disabled and unconfigured capture never reports success.
- [x] Writer exceptions and non-durable receipts never report capture success.
- [x] Closed clients reject operations; shutdown is idempotent.

## Security/compatibility

- [x] Generic API source contains no internal `src` or Hermes import.
- [x] No storage handle/path/SQL/raw exception leaks through public responses.
- [x] Explicit identity and writer ownership are preserved.

## Async/boundedness

- [x] Async queue capacity is bounded and invalid values fail closed.
- [x] Deadline distinguishes queue acquisition timeout from operation timeout.
- [x] Async shutdown closes the owned worker deterministically.

## Regression

- [x] WP-24..WP-27 focused/API suites pass.
- [x] Existing WP-08 public API and generic integration tests pass.
- [x] Isolated full regression excluding only the recorded pre-existing baseline artifact mismatch passes.
- [x] Compile, `git diff --check`, and independent review pass.

## Exit gate

Transition to `VERIFIED` only with executable evidence for all functional, negative, compatibility, boundedness, and regression checks plus independent fail-closed review.
