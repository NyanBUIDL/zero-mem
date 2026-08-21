# Zero-Mem v1.2.3 R-03 Evidence Manifest

Parent SHA: `5d10de96ffbe92ec93bc6f5e71c28c42cf321faa`
Branch/ref: `release/v1.2.3`
Baseline timestamp: `2026-08-21T11:42:00Z`
Evidence refresh timestamp: `2026-08-21T11:45:00Z`
Operator: `Hermes zero-mem-build`
OS/architecture: `Linux x86_64`
Python/SQLite/FTS5: `Python 3.11.16; SQLite/FTS5 exercised`
Build command: `not applicable; packaging deferred to R-05`
Collection count: `3301 passed, 5 skipped, 0 failed`
Focused test count: `12 passed`
Changed files: `zero_mem/sidecar.py; src/retrieval/db.py; tests/integration/test_v123_sidecar_composition.py`
Reviewer: `pending fresh independent exact-tree review`

## Contract

The sidecar advertises the four canonical callable read names, dispatches through the same `PublicClient`/authorized-read owner as direct API calls, normalizes capability/status/reason/items/provenance/freshness, and remains bounded. The read-only SQLite connection is safe for the sidecar’s owned worker thread without weakening `mode=ro` or `query_only`.

## Platform status

- Linux: `PASS` for recorded focused and full isolated suites.
- Windows: `NOT_RUN`; R-04 scope.
- macOS: `NOT_RUN`; R-04 scope.
