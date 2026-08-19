# WP-31 Acceptance

**STATUS: VERIFIED**

## Functional

- Enabled bootstrap uses the real runtime and registers only approved hooks/read tools.
- Disabled master gate is a deterministic no-op with no DB/writer/query side effect.
- Capture and read paths use explicit runtime/sidecar ownership and authorization boundaries.
- Shutdown and restart are idempotent, bounded, and do not duplicate writers/registrations.

## Failure/security

- Hook payloads are not mutated; callback failures are isolated and observable.
- Store/startup/read/sidecar failures return sanitized bounded diagnostics.
- No Hermes-core modification, raw storage/auth/SQL/path/secret leakage, or uncontrolled context injection.

## Regression

- Existing M1/M6/M7/Hermes tests and WP-24..WP-30 tests pass.
- Isolated full regression excluding known baseline artifact mismatch passes.
- Compile, diff check, final Graphify, and independent review pass.

## Exit gate

WP-31 is VERIFIED: restart proof, real runtime ownership, hook/read failure isolation, controlled context evidence, and current-tree independent review are recorded in EVIDENCE.md. SQLite WAL fixture failures remain environment limitations and are not product evidence.
