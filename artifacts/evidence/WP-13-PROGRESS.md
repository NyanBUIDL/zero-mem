# WP-13 Progress Evidence

## Confirmed

WP-13 is active in Phase B. Production consumers include setup, doctor, integration configuration, runtime adapters, and the public client boundary.

## Changed

- Reconciled relative default capture-root validation while preserving explicit real-home rejection.
- Added immutable `EffectiveConfig` and deterministic explicit → environment → descriptor/default resolution.
- Added fail-closed unknown-field and invalid-value handling.
- Added source-labelled, content-free diagnostics.
- Integrated effective configuration validation into setup.

## Verified

- WP-13 focused tests: `9 passed`.
- Full regression: `3150 passed, 5 skipped, 0 failed`.
- Configuration benchmark: `1000` loads in approximately `0.029612s`.
- `git diff --check`: pass.

## Remaining WP-13 obligations

Complete schema coverage for all runtime/integration/workspace fields, doctor convergence, deprecated-key handling, migration-source reporting, and final WP evidence/closure. WP-13 is not yet marked VERIFIED.
