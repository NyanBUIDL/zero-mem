# WP-29 Acceptance

**STATUS: VERIFIED**

## Functional

- Every `AuthorizedReadService` read method evaluates identity/policy/effective grants before low-level discovery.
- Explicit authorizing READ grants produce only their own restrictive profile/project/space scopes.
- WRITE, revoked, deleted, foreign-subject, malformed, and expired/non-authorizing grants cannot authorize reads.

## Security hard gate

- DENY invokes zero low-level queries.
- Unauthorized rows cannot affect candidate sets, scores, counts, pagination, cursors, ordering, identifiers, errors, or scope metadata.
- Cross-profile, cross-project, cross-space, global/null-profile, and isolated-mode leakage-negative tests pass.
- No raw SQL, secret, local path, grant internals, or existence information leaks through denial.

## Determinism and compatibility

- Scope normalization, result merge/deduplication, ordering, and cursor binding are deterministic.
- Existing M5/M8/public API behavior and reason codes remain compatible.
- Authorization performs no canonical or derived mutation.

## Regression/recovery

- WP-24..WP-28 focused/API tests pass.
- Existing M5/M8 security and read-only tests pass.
- Isolated full regression excluding only the recorded baseline artifact mismatch passes.
- Compile, `git diff --check`, and independent fail-closed review pass.

## Exit gate

WP-29 cannot be `VERIFIED` unless leakage-negative and scope-isolation evidence is executable and independent review passes. WP-30+ may not rely on an unverified authorization boundary.
