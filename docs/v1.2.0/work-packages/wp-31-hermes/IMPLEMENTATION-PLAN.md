# WP-31 Implementation Plan

**STATUS: VERIFIED**

## Baseline

- Workspace: `/home/lenovo/Hermes Workspace/zero-mem-v1.1`
- Baseline SHA: `7d871a95017c250f2d27a6e284ccfc6ad6f3c02e`
- Dependencies WP-25, WP-29, WP-30 are VERIFIED.
- Existing implementation: `src/integration/hermes_registration.py`, `hermes_read_adapter.py`, `zero_mem_runtime.py`, M6 dispatcher, and existing M1/M6/M7 tests.

## Gap analysis

The repository already has separate observer and read adapters, a runtime gate, and lifecycle tests. WP-31 must prove the end-to-end composition uses the single runtime owner, that read calls use the sidecar/authorized service path, that hook failures are isolated/observable, and that restart does not duplicate registration or writers. Context injection remains controlled and no-op unless explicitly supported by current integration.

## Increments

1. Add WP-31 tests for bootstrap master-disabled/enabled, real runtime ownership, hook/read registration, payload non-interference, callback failure isolation, shutdown/restart, and context-injection control.
2. Fix only verified lifecycle/ownership/integration defects.
3. Run Hermes/M1/M6/M7/WP-24..WP-30 regressions, full isolated suite, static checks, final Graphify, and independent review. Completed with documented SQLite WAL environment limitation.

## Expected files

Existing integration modules only if needed; new focused tests and WP-31 docs/evidence/state. No Hermes core files.

## Security/rollback

No new dependency/schema/canonical authority. Rollback is WP-31-only source/test/doc reversal; existing capture history remains untouched.

## Plan validation

Validated against Master Plan WP-31, current runtime/read/capture adapters, WP-29 authorization and WP-30 sidecar boundaries, and existing M1/M6/M7 tests. No architecture conflict identified.
