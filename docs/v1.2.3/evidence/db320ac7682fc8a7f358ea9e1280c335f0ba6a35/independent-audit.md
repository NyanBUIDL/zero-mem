# R-01 Independent Audit

**Verdict:** PASS
**Reviewed HEAD:** `4e427f102803a67a3a63b0f85e4863a540e77767`
**Artifact source:** `db320ac7682fc8a7f358ea9e1280c335f0ba6a35`
**Reviewer mode:** fresh read-only exact-tree review

## Confirmed

- One supported public construction path: `zero_mem.open_local_client()`.
- One runtime owns the canonical JSONL writer, derived SQLite store, and projection coordinator.
- Public caller test imports only `zero_mem` and uses real capture plus derived reads.
- Search, trace, task-state, and decision methods return typed results through the authorized read adapter.
- Authorization remains before query execution; denied scope returns no items or provenance.
- Disabled composition creates no runtime root; restart reopens durable data.
- Focused R-01 tests: `42 passed`.
- Full isolated suite at the exact source tree: `3300 passed, 5 skipped, 0 failed`.
- v1.2.3 verifier passed; all three evidence checksum entries passed.
- Git status clean; artifact source is an exact ancestor; post-source delta is allowlisted evidence only.

## Review note

An additional exploratory probe reported search `UNAVAILABLE` because it did not reproduce the production test’s required synchronization/query setup. The reviewer treated this as a non-blocking probe setup discrepancy; the authoritative E2E and exact evidence remained green.

## Remaining scope

R-01 does not qualify sidecar R-02, Hermes host R-03, Windows/macOS R-04, or packaging/R-05.
