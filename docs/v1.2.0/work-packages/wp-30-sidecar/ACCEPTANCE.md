# WP-30 Acceptance

**STATUS: VERIFIED**

## Functional/parity

- Valid sidecar requests map to the same canonical capability and authorization path as direct API.
- Explicit identity is preserved; direct/sidecar normalized responses have semantic parity.
- Invalid envelopes and unsupported tools fail with typed sanitized status.

## Bounds/failure

- Request and response byte limits are enforced before unbounded allocation/serialization.
- Concurrency and queue are bounded; full admission returns `OVERLOADED`.
- Deadline returns `DEADLINE_EXCEEDED`; no infinite retry.
- Downstream exception, unavailable runtime, and close/restart paths are sanitized and bounded.

## Security

- Static checks prove no SQL, JSONL, authorization, ranking, or alternate retrieval implementation in sidecar.
- No raw exception/path/secret/credential leakage.
- Identity and authorization leakage-negative tests pass through sidecar.

## Regression

- Existing M6/Hermes registration and WP-24..WP-29 tests pass.
- Isolated full regression excluding the known baseline artifact mismatch passes.
- Compile, `git diff --check`, final Graphify, and independent fail-closed review pass.

## Exit gate

WP-30 cannot be VERIFIED without executable boundedness, parity, overload, deadline, identity, restart, and security evidence.
