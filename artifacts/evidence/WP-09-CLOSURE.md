# WP-09 Closure Evidence

## Policy decision applied

The maintainer-approved matrix is machine-readable at `artifacts/control/COMPATIBILITY-MATRIX.yaml` and documented at `docs/v1.1.0/benchmarks/WP-09-COMPATIBILITY-MATRIX.md`.

## Classifications

- Linux x86_64: `SUPPORTED`, locally `VERIFIED` for Linux 7.0.0-29-generic x86_64, Python 3.11.16, SQLite 3.53.1, FTS5 enabled.
- Linux arm64: `SUPPORTED_IF_QUALIFIED`, `QUALIFICATION_PENDING`.
- macOS arm64: `SUPPORTED_IF_QUALIFIED`, `QUALIFICATION_PENDING`.
- macOS x86_64: `BEST_EFFORT_UNVERIFIED`, `QUALIFICATION_PENDING`.
- Native Windows: `NOT_SUPPORTED` for v1.1.0.
- WSL2: `SUPPORTED_IF_QUALIFIED`, `QUALIFICATION_PENDING`; Linux-side state authoritative.
- Docker on Linux: `SUPPORTED_IF_QUALIFIED`, `QUALIFICATION_PENDING`; durable state requires an explicit mounted volume.
- Python: `>=3.11,<3.14`.
- SQLite FTS5: required for FTS-backed retrieval; unavailable capability remains typed unavailable.

## Qualification

Current executor qualification passed Python-bound, SQLite-version, FTS5, path/configuration, setup/doctor, and typed unavailable capability tests. Unavailable environments remain pending; no cross-platform evidence was inferred.

## Evidence

- WP-09 focused compatibility/setup/doctor tests: `15 passed`.
- Full regression: `3163 passed, 5 skipped, 0 failed`.
- `git diff --check`: pass.

## Decision

`PASS — WP-09 VERIFIED WITH HONEST UNVERIFIED MATRIX ROWS`
