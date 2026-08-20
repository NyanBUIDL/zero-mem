# V122-03 Public Authorized Reads Handoff

**Status:** `VERIFIED_LINUX_SCOPED`
**Current tree fingerprint:** `ba9cd2d8719bcb00e8562b4a7baf07dfb69cceb0616c134c519d7ec99f5a3bdc`

## Changed

- `zero_mem/api.py`: public `search`, `get_trace`, `get_task_state`, and `get_decisions` now use an injected storage-neutral `PublicReadService` protocol. Existing no-service callers retain typed unavailable compatibility.
- `zero_mem/__init__.py`: exports the protocol.
- `src/integration/public_read_adapter.py`: maps public requests to validated `AccessRequest` and routes to `AuthorizedReadService`; denial is before discovery, results are bounded by the underlying service, and statuses are typed as READY/DENIED/STALE/TIMEOUT/UNAVAILABLE/INVALID.
- `src/integration/zero_mem_runtime.py`: opens the derived database through `retrieval.db.open_readonly` and constructs the adapter; no public API imports SQL/storage.

## Invariants

Authorization is delegated to `AuthorizedReadService`; the public module contains no SQL, JSONL, Hermes, or storage imports. `require_current`, `bounded_wait`, and `allow_stale` are explicit consistency values. Freshness/provenance are included in adapter results. Denials contain no candidate data.

## Verification

- Existing public API compatibility and neutrality tests pass.
- Focused combined V122 run: `82 passed`.
- Source inspection confirms `zero_mem/api.py` has no `src` or `sqlite` imports.

## Risk / next

The adapter requires an explicitly injected `AuthorizedReadService` and does not infer identity. Independent exact-tree review must confirm result-shape compatibility with all intended callers and the bounded-wait implementation before closure.
