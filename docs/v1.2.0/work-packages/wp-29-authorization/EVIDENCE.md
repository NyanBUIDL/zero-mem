# WP-29 Evidence

## Identity and authorization

- WP: WP-29 Authorization
- Baseline SHA: `7d871a95017c250f2d27a6e284ccfc6ad6f3c02e`
- Dependencies: WP-28 `VERIFIED`; WP-25/WP-26/WP-27 also `VERIFIED`.
- Authorization: `AUTONOMOUS_EXECUTION_AUTHORIZATION`, scope `WP-24..WP-35`; release publication not authorized.

## Implementation

- Inspected existing authorization-first boundary: `src/access/contracts.py`, `policy.py`, `grants.py`, `resolver.py`, and `authorized_read.py`.
- Added `tests/unit/test_wp29_authorization.py` covering denial-before-discovery across structured, trace, search, M4, and linked read surfaces; foreign-subject/WRITE grant rejection; and denial metadata leakage.
- No new dependency, schema, transport, Hermes integration, ranking, or canonical mutation was added.

## Verification

- Focused authorization/security suite: `221 passed`.
- Full isolated regression excluding known baseline artifact test: `3199 passed, 5 skipped in 63.57s`.
- Graphify final local-tree analysis: `7173 nodes, 21165 edges, 205 communities`; disposable output `/home/lenovo/graphify-zero-mem-v1.2-wp29-final`.

## Acceptance status

`VERIFIED`.

Independent fail-closed review: `passed: true`; `security_concerns: []`; `logic_errors: []`. Reviewer confirmed authorization-before-discovery across inspected read surfaces, no candidate/count/pagination/identifier/error/scope leakage, explicit identity, READ/WRITE separation, lifecycle/state filtering, and canonical immutability. Suggestions are non-blocking: deterministic resolver ordering test and omitted-resource-type restricted-grant test.

## Known baseline

The unfiltered full suite retains the previously recorded baseline artifact wording mismatch; the test remains unchanged.

## Final verification state

Not yet `VERIFIED`; WP-30 and later WPs remain blocked on this security gate.
