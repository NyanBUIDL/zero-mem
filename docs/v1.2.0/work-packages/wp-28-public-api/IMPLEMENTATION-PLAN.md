# WP-28 Implementation Plan

**STATUS: VERIFIED**

## Baseline

- Workspace: `/home/lenovo/Hermes Workspace/zero-mem-v1.1`
- Baseline SHA: `7d871a95017c250f2d27a6e284ccfc6ad6f3c02e`
- Current state: WP-24..WP-27 `VERIFIED`; WP-28 `PLANNING`.
- Existing public surface: `zero_mem/api.py`, `zero_mem/core.py`, `zero_mem/__init__.py`.
- Existing tests: `tests/unit/test_wp08_public_api.py`, `tests/integration/test_wp08_generic_client.py`, plus API/core regression tests.

## Gap analysis

The repository already has a useful public client and four typed unavailable capability placeholders. Planning is required to verify contract stability, request validation, status vocabulary, async boundedness, shutdown parity, and export isolation. No new storage or authorization behavior is needed for this WP.

## Exact scope and increments

1. Freeze the public contract matrix and export list from current implementation and WP-08 authority.
2. Add contract-negative tests for malformed identity/payload/deadline/queue settings, disabled/unconfigured capture, closed use, and sanitized errors.
3. Verify four capability mappings remain typed `CAPABILITY_UNAVAILABLE` until owned by later WPs; do not implement retrieval here.
4. Verify sync/async lifecycle and shutdown parity, bounded queue/deadline behavior, and writer ownership boundaries.
5. Apply only minimal implementation fixes required by failing contract tests.

## Expected files

- `zero_mem/api.py`, `zero_mem/core.py`, `zero_mem/__init__.py` if required.
- `tests/unit/test_wp28_public_api.py` and/or extensions to existing public API tests.
- `tests/integration/test_wp28_generic_client.py` if a new integration contract is needed.
- WP-28 documentation/evidence/state files.

## Interfaces/contracts

- `PublicClient.open`, `session_start`, `observe_message`, `observe_tool_call`, `sync`, four capability methods, `health`, `shutdown`.
- `AsyncClient.open`, async lifecycle/capture/sync/health, `aclose`.
- Typed `CapabilityResult`, `CaptureResult`, `Health`, `ZeroMemAPIError` subclasses.
- `API_VERSION` remains independent from package version.

## Migration/compatibility/security impact

No schema or migration. Preserve v1.1 public imports and generic-agent behavior. Keep storage and authorization behind adapters; no secret or raw payload in public errors. Capture remains explicit-writer and durable-receipt gated.

## Rollback

Revert WP-28-only source/tests/docs changes; canonical JSONL and derived state are untouched.

## Test strategy

TDD contract tests first, then focused WP-28 plus WP-24..WP-27/API regressions, then isolated full suite. Inspect public module source for forbidden internal imports and run compile/diff checks.

## Open questions

None blocking. Whether read capabilities become implemented is explicitly deferred to WP-29/WP-32/WP-33 according to ownership.

## Plan validation

Validated against Master Plan WP-28 dependencies/objective, WP-08 task packet/handoff, current public source/tests, canonical-storage architecture, and verified WP-25/WP-26/WP-27 state. No architecture conflict identified.
