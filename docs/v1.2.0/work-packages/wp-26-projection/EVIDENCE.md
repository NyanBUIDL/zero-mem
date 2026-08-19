# WP-26 Evidence

## Identity and authorization

- WP: WP-26 Projection
- Baseline SHA: `7d871a95017c250f2d27a6e284ccfc6ad6f3c02e`
- Dependency: WP-25 `VERIFIED`
- Authorization: `AUTONOMOUS_EXECUTION_AUTHORIZATION`, scope `WP-24..WP-35`; routine WP approval not required; architecture escalation required; release publication not authorized.

## Implementation

- Added `src/storage/projection.py` with `ProjectionCoordinator`, `ProjectionConfig`, `ProjectionNotification`, `ProjectionWatermark`, and typed statuses.
- Queue is bounded by validated `queue_capacity`; one daemon worker is created per coordinator.
- `ProjectionConfig.source_root` is an explicit resolved boundary; submissions outside it are rejected before ingestion.
- `from_ingest()` delegates derived materialization to existing transactional `ingest_file` and reads committed checkpoint state for watermark confirmation.
- `submit()` returns `PROJECTION_ENQUEUED` only when the notification entered the queue; queue-full retains a bounded deferred notification with same-source coalescing and returns `DERIVED_PENDING`; overflow beyond bounded retention returns `DERIVED_UNAVAILABLE` rather than silently discarding input.
- `flush()` and `close(timeout)` are bounded; close is idempotent.
- Trusted internal projector boundary and explicit source-root defense-in-depth are documented; adversarial profile/project symlink hardening remains WP-34 scope.
- No schema migration, retrieval, authorization, public API, dependency, release, tag, push, or publication was added.

## Changed files

- `src/storage/projection.py`
- `tests/unit/test_wp26_projection.py`
- WP-26 planning documents and state records.

## Verification

- RED: `.venv/bin/python -m pytest tests/unit/test_wp26_projection.py -q` failed at collection because `src.storage.projection` did not exist.
- Focused projection/storage tests: `.venv/bin/python -m pytest tests/unit/test_wp26_projection.py tests/unit/test_m2_ingest.py tests/unit/test_m8_1_rebuild.py tests/unit/test_m1_capture_boundary.py tests/unit/test_wp24_correctness_backport.py tests/unit/test_wp25_runtime_ownership.py -q` → `86 passed in 5.09s`.
- Compile: `.venv/bin/python -m compileall -q src/storage/projection.py` → pass.
- Full isolated regression excluding baseline artifact test: `3182 passed, 5 skipped in 64.15s`; the initial run exposed and closed a pre-existing M7 audit pattern conflict by removing literal unbounded-loop/sleep signatures from the bounded coordinator. The rerun passed.
- Graphify final local-tree read-only analysis after final corrections: `7122 nodes, 21017 edges, 193 communities`; `ProjectionCoordinator` is connected to bounded lifecycle methods, explicit source-root validation, existing ingestion integration, and WP-26 tests. Disposable output: `/home/lenovo/graphify-zero-mem-v1.2-wp26-final-2`.

## Independent review

Final independent fail-closed review passed: `passed: true`, with empty `security_concerns` and `logic_errors`. Review confirmed trusted internal projector boundary, explicit source-root defense-in-depth, queue-full retry semantics, bounded daemon lifecycle, watermark behavior, and derived-only storage boundary. Non-blocking suggestions (additional timeout/stale tests and future batch-size refinement) are recorded as future maintenance, not acceptance blockers.

- Final current-tree independent review passed: `passed: true`, with empty `security_concerns` and `logic_errors`. The review verified queue ownership accounting, deferred pending semantics, deterministic same-source resubmission, bounded failure/close behavior, and canonical/derived separation.

## Unresolved issues

No blocking implementation issues remain. The coordinator's integration point into runtime notification flow remains intentionally narrow and uses the existing ingestion callback; public API/Hermes lifecycle integration is deferred to the owning later WPs. Current focused dependent rerun after the queue fix: `88 passed`.
