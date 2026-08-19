# WP-35 Technical Design

**Status:** `VERIFIED`

## Technologies / dependencies

Use existing `.venv/bin/python` 3.11.16, pytest, setuptools build tooling, `pip`, standard-library hashing/inspection, and existing packaging scripts. No new dependency and no network requirement for the clean-install gate.

## Qualification algorithms

1. Establish canonical workspace identity and tested state.
2. Run targeted and full isolated tests with isolated HOME/XDG/temp roots.
3. Build artifacts twice with fixed `SOURCE_DATE_EPOCH`; compute SHA-256 and compare bytes.
4. Inspect archive members against deny patterns and package allowlist.
5. Create fresh external venv; install wheel with `--no-index --no-deps`; import package and run local CLI/setup/doctor smoke checks.
6. Record E2E/failure matrix as PASS, NOT_EXECUTED, or BLOCKED with evidence; never infer unsupported results.

## Variables / constants

- `SOURCE_DATE_EPOCH=315532800`: existing reproducible-build contract.
- Python support exercised: `3.11.16`; declared range `>=3.11,<3.14`.
- Artifact names, hashes, package members, test counts, and tested SHA: immutable evidence values owned by this run.
- `ZERO_MEM_V1_2_STATUS`: final state marker only; set to `RELEASE_CANDIDATE_READY` after all gates.

## Concurrency / retry / timeout

Tests use bounded pytest fixtures and isolated roots. Package build/install commands have finite command timeouts and are retried only after classifying an environmental failure. No infinite retry, background server, watcher, or network service.

## Data / artifact boundaries

Wheel and sdist are derived release artifacts. Canonical JSONL, SQLite, projection vaults, and user configuration are read-only inputs during qualification. Artifact evidence is stored under canonical `artifacts/evidence/`; temporary venvs/build roots are external runtime fixtures and removed after use.

## Security constraints

Do not print secrets or environment contents. Scan source/artifacts for credential-like values and developer-specific paths. Offline install must not contact indexes. No publication command is permitted. Clean install must not write into the real Hermes home or repository.

## Error/status vocabulary

Use `PASS`, `FAIL`, `NOT_EXECUTED`, `BLOCKED`, and `RELEASE_CANDIDATE_READY`. A missing artifact, failed clean install, unresolved critical/high finding, or failed required test is a release-qualification failure, not a warning.

## Compatibility / support

Only Linux CPython 3.11.16 is exercised here. Python range metadata is inspected but not claimed as runtime-tested for every interpreter. The separately authorized final metadata correction changes the package version to `1.2.0`; no runtime semantics change.

## Prohibited approaches

No tag/push/GitHub Release/PyPI, no system package installation, no sudo, no destructive chaos test, no fake E2E result, no weakening of tests, and no real-vault apply. The authorized metadata correction is limited to the package/release version.

## Open decisions

None required for local qualification. Publication remains outside this authorization.
