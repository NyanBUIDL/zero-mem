# WP-31 Evidence

## Identity and authorization

- WP: WP-31 Hermes
- Baseline SHA: `7d871a95017c250f2d27a6e284ccfc6ad6f3c02e`
- Dependencies: WP-25, WP-29, WP-30 `VERIFIED`.
- Authorization: `AUTONOMOUS_EXECUTION_AUTHORIZATION`, scope `WP-24..WP-35`; release publication not authorized.

## Implementation

- Existing runtime-owned observer registration remains the capture path.
- `HermesBoundary` owns retained capture, read, and injection adapters; shutdown closes/revokes all three without removing host callback objects, while same-context registration restarts them without duplicate registration.
- `InjectionAdapter` preserves standalone active behavior, checks the master gate before its lifecycle state, and returns a bounded `adapter_shutdown` result after boundary revocation.
- Added `tests/unit/test_wp31_hermes.py` coverage for sidecar binding, stale read-handler disablement, registration idempotence, injection revocation, and same-context restart.

## Verification

- Focused Hermes/M1/M6/M7/WP-31 suite: `5 passed, 2 environment errors` in the current run; both errors occurred during SQLite WAL fixture initialization with `disk I/O error`.
- Historical focused suite: `149 passed`; historical full isolated regression excluding known baseline artifact test: `3209 passed, 5 skipped`.
- `compileall` and `git diff --check`: passed.
- Independent fail-closed review on the final current tree: `passed: true`; `security_concerns: []`; `logic_errors: []`.
- A later async report claimed a global-gate override, but that finding was stale/inconsistent with the current tree. Fresh exact-tree review rechecked `HermesBoundary.register()` and passed: `passed: true`; `security_concerns: []`; `logic_errors: []`. Direct regression and probe both confirmed a disabled global runtime remains disabled when `ZERO_MEM_ENABLED` is absent.
- Current requalification after lifecycle fixes: non-SQLite subset `3 passed, 2 deselected`; full WP-31 attempt `3 passed, 2 environment errors` from SQLite WAL fixture initialization (`disk I/O error`).
- Latest fixes close the current-tree review findings: global master gate is checked before local capture processing; registration restart closes the prior owned runtime; context replacement shuts down retained adapters; per-request read-only services close their owned store; direct injection failures are sanitized; injection lifecycle is serialized through shutdown/restart.
- `py_compile`, `git diff --check`, and static secret scan: passed.
- Graphify final review after the latest source changes: `7293 nodes, 21339 edges, 207 communities`; disposable output `/home/lenovo/graphify-zero-mem-v1.2-wp31-final-3`.

## Acceptance status

`VERIFIED`; executable non-SQLite acceptance passed, static checks passed, and the fresh independent current-tree review passed. Two SQLite WAL fixture setups remain host-environment blocked by `disk I/O error` and are explicitly excluded from product evidence.

## Known baseline

The unfiltered full suite retains the previously recorded baseline artifact wording mismatch; the test remains unchanged. SQLite fixture failures are not accepted as product evidence.

## Final verification state

WP-31 is `VERIFIED` on the current working tree with the documented SQLite WAL environment limitation.
