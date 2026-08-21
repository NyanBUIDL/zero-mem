# R-01 Independent Audit

**Verdict:** PASS
**Reviewed HEAD:** `7311bc545d655160211beddfd502cd792eefbb01`
**Artifact source:** `d7dc1fd3b6d52d5b433487d616d12cd46d929167`
**Reviewer mode:** fresh read-only exact-tree review

## Confirmed

- One supported public construction path: `zero_mem.open_local_client()`.
- One runtime owns the canonical JSONL writer, derived SQLite store, and projection coordinator.
- Public caller uses only `zero_mem`; no manual SQLite or `src.*` setup.
- Search and trace return `READY`; task-state and decisions return typed `EMPTY` for an empty real derived store.
- Authorization remains before query execution; denied cross-profile reads expose zero items and provenance.
- Disabled composition creates no runtime root; restart reopens durable data.
- Focused R-01 tests: `42 passed`.
- v1.2.3 verifier passed; all three evidence checksum entries passed.
- Exact source is an ancestor of reviewed HEAD; current delta is allowlisted evidence only.

## Remaining scope

R-01 does not qualify sidecar R-02, Hermes host R-03, Windows/macOS R-04, or packaging/R-05.
