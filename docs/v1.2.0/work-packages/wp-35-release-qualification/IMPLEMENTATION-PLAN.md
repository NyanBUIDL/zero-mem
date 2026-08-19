# WP-35 Implementation Plan

**Status:** `VERIFIED`
**Baseline SHA:** `7d871a95017c250f2d27a6e284ccfc6ad6f3c02e`

## Current repository state

WP-24 through WP-34 are recorded VERIFIED in the v1.2 state. The working tree contains their uncommitted source/tests/docs plus pre-existing governance artifacts; no reset or cleanup is permitted. `pyproject.toml` declares version dynamically from `zero_mem.version`, Python `>=3.11,<3.14`, no mandatory dependencies, and optional `pdf` support. The separately authorized final metadata correction targets distribution version `1.2.0`.

Existing release-layer surfaces include `packaging/build_bundle.py`, `packaging/install.py`, `packaging/release_common.py`, `packaging/README.md`, and prior local artifact evidence. They are qualification inputs, not a license to publish.

## Planned increments

1. Planning reconciliation and package self-review.
2. Run targeted v1.2 lifecycle/E2E suites: WP-24–34, direct API, sidecar, Hermes, projection, authorization, context, recovery, and canonical immutability.
3. Run isolated full regression with controlled HOME/XDG/base temp, preserving the known baseline artifact wording mismatch.
4. Build wheel/sdist twice under `SOURCE_DATE_EPOCH=315532800`; compare hashes and inspect contents.
5. Create a fresh local venv outside the repository, install the wheel offline/no-deps, run version/setup/doctor/import smoke checks, then remove only that runtime fixture.
6. Run static secret/developer-path/temp-file scans and package metadata checks.
7. Run Graphify on the final tree and obtain independent fail-closed review.
8. Record `RELEASE_CANDIDATE_READY`; stop before any publication.

## Expected files / implementation

No production source implementation is planned. Changes are limited to WP-35 documentation, evidence, project state, and canonical `artifacts/evidence/` release-qualification outputs. Temporary venvs and test roots are runtime fixtures only.

## Interfaces and lifecycle gate

The qualification path verifies the existing sequence:

`Hermes capture → canonical JSONL → AppendReceipt → projection → AuthorizedReadService → deterministic retrieval → bounded context → restart → retrieval again`.

Recovery and package install are separate gates; neither may rewrite canonical data or publish artifacts.

## Security / compatibility / migration

No schema, migration, dependency, or public API change. Artifact contents must exclude `.venv`, caches, tests, benchmarks, credentials, absolute developer paths, and temporary runtime files. Linux CPython 3.11 is the exercised support target; other platforms remain unclaimed unless independently tested.

## Failure matrix

Covered by executable existing tests where available: append failure/receipt, missing/corrupt/stale derived state, interrupted/cancelled recovery, projection queue/lifecycle, authorization leakage, sidecar timeout/overload, Hermes disable/restart, context budget/malformed input, and package installation. Disk-full, SIGKILL at arbitrary system points, and real external process crash injection are not performed destructively; record as NOT_EXECUTED with the nearest safe evidence.

## Rollback

Documentation/evidence changes are reversible. Artifact directories are disposable. No canonical, real-vault, remote, tag, or package publication rollback is needed because those actions are prohibited.

## Plan validation

Validated against current `pyproject.toml`, packaging scripts, v1.2 state, Master Plan release gates, and verified WP dependencies. No architecture escalation is required for local qualification; publication remains explicitly unauthorized.
