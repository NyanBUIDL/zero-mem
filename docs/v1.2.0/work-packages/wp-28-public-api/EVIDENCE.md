# WP-28 Evidence

## Identity and authorization

- WP: WP-28 Public API
- Baseline SHA: `7d871a95017c250f2d27a6e284ccfc6ad6f3c02e`
- Dependencies: WP-25 and WP-26 `VERIFIED`; WP-27 also `VERIFIED` in current state.
- Authorization: `AUTONOMOUS_EXECUTION_AUTHORIZATION`, scope `WP-24..WP-35`; per-WP approval not required; release publication not authorized.

## Implementation

- Existing public API surface inspected: `zero_mem/api.py`, `zero_mem/core.py`, `zero_mem/__init__.py`.
- Added `tests/unit/test_wp28_public_api.py` covering capability matrix, disabled/invalid input, bounded async deadline behavior, and public-module isolation.
- No new dependency, schema, storage path, authorization implementation, transport, or Hermes-specific code was added.

## Verification

- Focused WP-24..WP-28/API suite: `37 passed`.
- Full isolated regression excluding known baseline artifact test: `3196 passed, 5 skipped in 64.27s`.
- `compileall` and `git diff --check` pass for the implementation/test tree.
- Graphify final local-tree analysis: `7164 nodes, 21138 edges, 199 communities`; disposable output `/home/lenovo/graphify-zero-mem-v1.2-wp28-final`.

## Acceptance status

`VERIFIED`.

Independent fail-closed review: `passed: true`; `security_concerns: []`; `logic_errors: []`. Reviewer found no blocking contract, security, logic, or scope defects.

## Known baseline

The unfiltered full suite retains the pre-existing baseline artifact wording mismatch; it is excluded only as previously recorded and the test remains unchanged.

## Final verification state

Not yet `VERIFIED`; independent review is required before state transition.
