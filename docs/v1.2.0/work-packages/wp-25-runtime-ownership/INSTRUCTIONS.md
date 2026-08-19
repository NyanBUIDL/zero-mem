# WP-25 Instructions

## Objective

Establish one explicit `ZeroMemRuntime` composition root that owns the canonical JSONL writer lifecycle and exposes a bounded runtime handle to adapters.

## Dependencies

- WP-24 — VERIFIED.

## Scope

- Add validated runtime configuration for the canonical capture root.
- Open the canonical writer only through `ZeroMemRuntime`.
- Make runtime shutdown deterministic and idempotent.
- Migrate the Hermes registration adapter to consume the runtime-owned writer.
- Preserve the existing master enable/disable gate and injected test seams.

## Out of scope

- Projection queues, workers, watermarks, or SQLite projection lifecycle (WP-26).
- Recovery/rebuild implementation (WP-27).
- Public read contracts and authorization (WP-28/WP-29).
- Hermes core changes or new transport integration.

## Required invariants

- JSONL remains the canonical event source of truth.
- Runtime is the only production composition root that opens `JsonlCaptureStore`.
- Adapters do not infer paths or instantiate canonical stores.
- No uncontrolled global mutable writer ownership.
- `ZeroMemRuntime` has explicit lifecycle: open once, close safely, no use after close.
- Master `ZERO_MEM_ENABLED` semantics remain strict and restart-scoped.
- Canonical append failures remain fail-closed through the WP-24 receipt contract.

## Allowed changes

- `src/integration/zero_mem_runtime.py`.
- `src/integration/hermes_registration.py` and directly related tests.
- New WP-25 unit/integration tests and planning/evidence documents.

## Prohibited changes

- No schema migration or derived-state write.
- No projection implementation.
- No new runtime dependency.
- No global writer singleton.
- No source-of-truth change, destructive operation, release, tag, push, or publication.

## Required inputs

- Validated `BridgeConfig`/capture root.
- Existing `JsonlCaptureStore` and `CaptureStoreConfig`.
- Existing WP-24 receipt/capture contracts.

## Required outputs

- Runtime-owned canonical writer.
- Explicit lifecycle methods and runtime health state.
- Adapter path proving writer ownership is not recreated locally.
- Focused ownership, lifecycle, failure, and regression evidence.

## Security and data-integrity boundaries

Only the runtime resolves the configured capture path and opens the writer. Path validation remains delegated to the validated configuration boundary. Runtime shutdown must not delete, rewrite, or repair canonical data.

## Escalation conditions

Escalate only for an authority conflict, a required trust-boundary change, a destructive canonical operation, or a need to implement WP-26+ behavior in this WP.

## Completion conditions

Planning files are self-consistent; runtime ownership tests, existing M7/M1 integration tests, focused regressions, and static/diff checks pass; independent review finds no blocking issue; evidence is recorded and state is transitioned to `VERIFIED`.
