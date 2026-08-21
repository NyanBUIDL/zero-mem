# R-01 — Public Composition

**Status:** OPEN
**Baseline SHA:** `5f1a329b6e5a18833fb4186cad7c91807a40b79e`
**Finding closed:** Public external consumer cannot yet construct a fully wired local runtime through `zero_mem` alone.
**Allowed paths:** `zero_mem/**`, `src/integration/public_read_adapter.py`, focused R-01 tests, v1.2.3 evidence/work-package documentation.
**Public boundary tested:** `import zero_mem` only; real canonical JSONL plus derived SQLite fixture.
**Platform scope:** Linux first; platform-neutral API contract.

## Observable problem

`zero_mem.PublicClient.open()` accepts an injected read service but does not own construction of the canonical runtime/read surface. A caller must not import `src.*`, know database paths, or inject an internal-only service.

## Contract decision

Add the smallest documented `zero_mem` factory that owns runtime construction and returns typed real reads through the existing authorization adapter. Preserve one runtime and JSONL-canonical/SQLite-derived semantics.

## Negative cases

Denied scope, missing derived state, stale policy, timeout, disabled runtime, restart, and no direct SQL/public `src.*` import.

## Evidence

To be populated only after R-00 is verified and R-01 focused, regression, security, provenance, and independent-review gates pass.
