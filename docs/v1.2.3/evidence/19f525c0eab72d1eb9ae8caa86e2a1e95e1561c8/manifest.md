# Zero-Mem v1.2.3 R-01 Evidence Manifest

Parent SHA: `738afaca58af9b996fac205b9ad6d1f721a1dd8c`
Branch/ref: `release/v1.2.3`
Baseline timestamp: `2026-08-21T11:24:00Z`
Evidence refresh timestamp: `2026-08-21T11:30:00Z`
Operator: `Hermes zero-mem-build`
OS/architecture: `Linux x86_64`
Python/SQLite/FTS5: `Python 3.11.16; SQLite/FTS5 exercised by full suite`
Build command: `not applicable to R-01; packaging deferred to R-05`
Collection count: `3300 passed, 5 skipped, 0 failed`
Focused test count: `42 passed`
Changed files: `zero_mem/local.py; zero_mem/__init__.py; src/integration/public_read_adapter.py; tests/integration/test_v123_public_composition.py`
Reviewer: `pending fresh independent exact-tree review`

## Contract

A consumer imports only `zero_mem`, calls `open_local_client()`, captures a real fixture through the canonical JSONL writer, waits for derived projection, and receives typed results from search, trace, task-state, and decision reads. The factory owns the runtime, projection coordinator, and authorized read service. Disabled composition creates no runtime root.

## Platform status

- Linux: `PASS` for the recorded isolated Python 3.11 suite.
- Windows: `NOT_RUN`; R-04 scope.
- macOS: `NOT_RUN`; R-04 scope.
