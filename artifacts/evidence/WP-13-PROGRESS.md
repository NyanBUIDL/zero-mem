# WP-13 Progress Evidence

## Confirmed

WP-13 remains active in Phase B. Production consumers are setup, doctor, integration configuration, runtime adapters, projection/workspace configuration, and the public client boundary.

## Changed

- Reconciled relative default capture-root validation while preserving explicit real-home rejection.
- Added immutable `EffectiveConfig` and deterministic explicit → environment → descriptor/default resolution.
- Added source-labelled, content-free diagnostics and fail-closed unknown/invalid field handling.
- Converged explicit integration identity, capture root, Hermes home, Obsidian vault, and managed-directory inputs into the effective configuration object.
- Integrated effective configuration validation into setup and doctor.
- Added focused, integration, negative, and benchmark coverage.

## Verified

- WP-13 focused/integration/setup tests: `12 passed`.
- Full regression: `3153 passed, 5 skipped, 0 failed`.
- Configuration benchmark: `1000` loads in approximately `0.047378s`.
- `git diff --check`: pass.

## Remaining

The final WP closure still requires explicit migration/deprecation evidence for the supported legacy environment/configuration inputs, final source-bound handoff, and a closure review. WP-13 is not yet marked VERIFIED.
