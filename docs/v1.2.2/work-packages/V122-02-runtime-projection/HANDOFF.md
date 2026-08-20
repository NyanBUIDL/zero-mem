# V122-02 Runtime + Projection Handoff

**Status:** `VERIFIED_LINUX_SCOPED`
**Current tree fingerprint:** `ba9cd2d8719bcb00e8562b4a7baf07dfb69cceb0616c134c519d7ec99f5a3bdc`
**Parent candidate SHA:** `ad6e38eaa7ac7a764aa54bd5fee8dfcd59a5a6a6`; final release evidence is bound separately to the post-qualification release commit.

## Observed

The pre-existing bounded `ProjectionCoordinator` was not composed into the runtime. `ZeroMemRuntime` owned capture only. Canonical JSONL is the source of truth and SQLite is derived.

## Changed

- `src/integration/zero_mem_runtime.py`: runtime now composes one writer, one derived `SQLiteStore`, one bounded coordinator, deterministic close, health/watermark, projection notification, strict read-only service opening, and disabled side-effect-free behavior.
- `src/storage/projection.py`: idempotent source/sequence submission, bounded saturation, watermark lag, last successful projection time, and sanitized projection error.
- `src/storage/sqlite_store.py`: the single derived connection supports the runtime-owned worker thread (`check_same_thread=False`); the worker remains single-owner for projection writes.
- `src/integration/hermes_registration.py`: durable append notifications submit projection work; callback failure cannot convert canonical capture success into failure.

## Data flow

`capture append + fsync → AppendReceipt → bounded ProjectionCoordinator → ingest_file(JSONL read-only) → SQLite derived checkpoint → watermark/health`. Restart reconstructs derived state from canonical JSONL; no recovery path writes canonical bytes.

## Iteration ledger

| Iteration | Blockers before | Root cause | Design/changed paths | Test result | Review | After |
|---|---|---|---|---|---|---|
| 1 | runtime had no projection composition | ownership gap | runtime/coordinator composition | focused pass | pending | review pending |
| 2 | worker failed on SQLite thread affinity | connection created on main thread | thread-safe connection option, worker remains single writer | focused pass | pending | review pending |

## Verified

- `python -m compileall -q src zero_mem ...`: exit 0.
- Focused V122-02/V122-03/V122-04/V122-05/V122-01 affected run: `82 passed`.
- Direct runtime smoke: durable hook capture reached `DERIVED_CURRENT`; projection flush returned `CURRENT`.
- Full suite: `3283 passed, 5 skipped, 1 failure`; the sole failure is the pre-existing machine-home assertion observing unrelated `kanban.db-wal`/`kanban.db-shm` artifacts. It is classified environment/fixture, not a product pass.
- Graphify current-tree code-only extraction: 7,498 nodes / 24,905 edges; disposable evidence at `artifacts/evidence/v1.2.2/V122-current/graphify/graph.json`, SHA-256 `afe5d4167c9f24d5337129349e1ef69a6687f68bd16f04e801928be1a8a49efb`.

## Risk

Independent exact-tree review is required before `VERIFIED`. Projection initialization failure is intentionally non-fatal to capture and reports `PROJECTION_UNAVAILABLE`; worker failure reports sanitized `PROJECTION_FAILED`. Windows/macOS qualification remains deferred.

## Next

Run fresh exact-tree replacement review, remediate concrete in-scope findings, rerun affected/full Linux evidence, then close V122-02.
