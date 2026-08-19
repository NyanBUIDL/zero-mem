# WP-26 Implementation Plan

**STATUS: VERIFIED**

## Baseline

- Workspace: `/home/lenovo/Hermes Workspace/zero-mem-v1.1`
- Baseline HEAD: `7d871a95017c250f2d27a6e284ccfc6ad6f3c02e`
- Dependency: WP-25 `VERIFIED`
- Authorization: `AUTONOMOUS_EXECUTION_AUTHORIZATION`, scope `WP-24..WP-35`; per-WP approval not required; architecture escalation required; release publication not authorized.

## Current implementation and gap

`src/storage/ingest.py` already provides transactional, resumable derived ingestion from canonical JSONL, including `zm_ingest_checkpoint`, consumed-prefix hashing, and rebuild helpers. There is no bounded coordinator that decouples canonical append from projection availability, owns a worker lifecycle, or exposes a derived watermark/freshness snapshot.

WP-25 now provides the runtime composition root and canonical writer lifecycle. WP-26 will add only a derived projection coordinator; it will not alter the canonical append contract or implement public retrieval.

## Exact increments

1. Define immutable `ProjectionConfig`, `ProjectionWatermark`, and typed projection status.
2. Implement a bounded `queue.Queue` coordinator with one worker per coordinator instance.
3. Submit source notifications after canonical append; queue-full returns `DERIVED_PENDING` while preserving canonical success.
4. Worker invokes existing ingestion and updates derived watermark only after successful committed ingestion.
5. Implement bounded `flush()` and deterministic `close()`; worker failure becomes `DERIVED_UNAVAILABLE` without infinite retry.
6. Add tests for queue bounds, stale/current transitions, worker failure, restart/close, and canonical JSONL immutability.

## Expected files

- `src/storage/projection.py` (new)
- `src/integration/zero_mem_runtime.py` only if bounded coordinator ownership is directly required by the runtime composition root.
- `src/integration/hermes_registration.py` only for narrow notification wiring if tests prove the path is needed.
- `tests/unit/test_wp26_projection.py` (new)
- Relevant existing integration tests only when contract adaptation is necessary.

## Interfaces

- `ProjectionConfig(queue_capacity: int, batch_size: int, source_root: Path)` — validated positive bounded values and explicit absolute source boundary.
- `ProjectionWatermark(canonical_sequence: int, derived_sequence: int, status: ProjectionStatus)`.
- `ProjectionCoordinator.start() -> None`.
- `ProjectionCoordinator.submit(source_path: Path, source_id: str, canonical_sequence: int) -> ProjectionStatus`; returns `PROJECTION_ENQUEUED` only after insertion, `DERIVED_PENDING` when caller retry is required.
- `ProjectionCoordinator.snapshot() -> ProjectionWatermark`.
- `ProjectionCoordinator.flush(timeout: float | None = None) -> ProjectionStatus`.
- `ProjectionCoordinator.close(timeout: float | None = None) -> None`.

Exact default limits remain configuration-owned; no unapproved magic values will be embedded.

## Schema and migration impact

No schema change planned. Existing ingestion checkpoints and derived tables remain the source for derived watermark observation. If an additional metadata column is required, stop and reconcile against approved schema before implementation.

## Concurrency and lifecycle

One daemon worker thread per coordinator; bounded `queue.Queue`; condition/event for flush and shutdown; no unbounded task creation. The daemon choice prevents a stuck external projector from blocking process termination; normal projectors must return within the caller's deadline. Worker terminates on close or terminal error. No retry loop after terminal failure.

## Security/provenance impact

The coordinator transports source identifiers and watermarks only. It does not authorize reads, rank records, or expose payloads. It must sanitize worker failure status and preserve source identity for provenance.

## Rollback

Coordinator is disposable and can be disabled without touching canonical JSONL. Rollback removes coordinator integration and test files; existing derived state remains rebuildable by current ingestion/rebuild tools.

## Test strategy

TDD vertical slices:

- RED/GREEN bounded queue acceptance and queue-full behavior.
- RED/GREEN transactional watermark/currentness transition.
- RED/GREEN worker failure and no infinite retry.
- RED/GREEN close/flush timeout and canonical file unchanged.
- Regression: WP-24/WP-25, M1/M2/M8.1 storage suites, isolated full suite.
- Static/diff checks and Graphify final local-tree analysis.

## Plan validation

Validated against Master Plan Phase 1 §1.2, existing `ingest.py` transaction/checkpoint implementation, WP-25 runtime ownership, and canonical-storage ADR-009. No architecture conflict identified.

## Open questions

- Exact coordinator integration point into runtime notification flow must be resolved by the first vertical test. If it requires a public API or Hermes lifecycle feature, defer that integration to WP-28/WP-31 rather than expanding WP-26.
