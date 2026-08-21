# Zero-Mem v1.2.3 R-00 Evidence Manifest

Parent SHA: `5f1a329b6e5a18833fb4186cad7c91807a40b79e`
Branch/ref: `release/v1.2.3`
Baseline timestamp: `2026-08-21T03:52:00Z`
Evidence refresh timestamp: `2026-08-21T04:05:32Z`
Operator: `Hermes zero-mem-build`
OS/architecture: `Linux x86_64`
Python/SQLite/FTS5: `Python 3.11.16; SQLite runtime verified by test suite; FTS5 exercised by existing tests`
Build command: `not applicable to R-00; packaging deferred to R-05`
Collection count: `3296 passed, 5 skipped, 0 failed`
Focused test count: `4 passed`
Changed files: `scripts/verify_v123_evidence.py; tests/unit/test_v123_evidence_verifier.py; docs/v1.2.3 control/work-package artifacts`
Reviewer: `pending fresh independent exact-tree review`

## Identity model

`ARTIFACT_SOURCE_SHA=db6a594eaaa309f939ddd86f9b6f05ffa95f9c15` is the exact source commit tested by the focused and full isolated suites. The evidence commit is intentionally derived by the verifier from the current checkout HEAD and is not self-embedded in this tracked manifest. `RELEASE_COMMIT_SHA` remains pending final R-05 reconciliation.

## Platform status

- Linux: `PASS` for the recorded isolated Python 3.11 suite.
- Windows: `NOT_RUN`; no real runner evidence in this bundle.
- macOS: `NOT_RUN`; no real runner evidence in this bundle.
