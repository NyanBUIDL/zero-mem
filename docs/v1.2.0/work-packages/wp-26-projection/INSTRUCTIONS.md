# WP-26 Instructions

## Objective

Add a bounded write-through projection coordinator that consumes successful canonical event notifications, invokes the existing derived ingestion path, and exposes explicit watermark/freshness states without making derived state canonical.

## Dependencies

- WP-25 — VERIFIED.

## Scope

- Add a process-local projection coordinator/worker around existing `ingest_file`/checkpoint primitives.
- Use a bounded queue and deterministic lifecycle.
- Track canonical and derived watermarks separately.
- Report `DERIVED_CURRENT`, `DERIVED_PENDING`, and `DERIVED_UNAVAILABLE` without false currentness.
- Keep canonical append independent from projection availability.

## Out of scope

- Recovery/rebuild orchestration and backup/restore (WP-27).
- Public API contracts (WP-28).
- Authorization, sidecar, Hermes core, context, retrieval, or Obsidian behavior.
- New storage engine, vector index, or schema truth source.

## Required invariants

- JSONL append-only events remain the canonical source of truth.
- Projection is disposable derived state and can be rebuilt from canonical JSONL.
- Queue capacity, batch size, and worker lifecycle are bounded.
- A stuck external projector cannot block process termination; bounded normal ingestion is required.
- Queue full returns `DERIVED_PENDING` without altering canonical truth and without silently claiming the notification was queued; the caller-visible status requires explicit retry.
- Watermark advances only after the derived transaction/checkpoint commits.
- Stale or unavailable derived state is never reported as current.
- No infinite retry, polling loop, or hidden fallback.

## Allowed changes

- New projection coordinator module under `src/storage/` or `src/integration/`.
- Directly related runtime integration and tests.
- WP-26 planning, acceptance, evidence, and project state.

## Prohibited changes

- No destructive canonical operation.
- No rewrite of JSONL from SQLite.
- No public API or authorization implementation.
- No unbounded queue/thread/task.
- No new runtime dependency.
- No release/tag/push/publication.

## Required inputs

- Runtime-owned canonical writer lifecycle from WP-25.
- Existing canonical JSONL path and `ingest_file` derived ingestion.
- Existing SQLite schema/checkpoint semantics.

## Required outputs

- Bounded coordinator with start/submit/flush/close lifecycle.
- Typed projection status and watermark snapshot.
- Negative evidence for queue-full, worker-failure, stale, and shutdown paths.

## Security and data-integrity boundaries

The coordinator receives source notifications only from the trusted runtime composition root. It is not a public transport boundary and does not accept user-controlled projector callbacks. Production uses the existing canonical read-only ingestion path; source-root validation is defense-in-depth. Profile/project symlink and TOCTOU hardening is owned by WP-34.

## Escalation conditions

Escalate if the existing ingestion contract cannot provide transactional checkpoint/watermark semantics, if a schema change is required but not approved, or if correctness requires canonical mutation or future-WP API behavior.

## Completion conditions

Planning is self-consistent; bounded queue, watermark, failure, shutdown, and canonical-independence tests pass; focused and regression suites pass; independent review has no blocking findings; evidence is recorded and state is `VERIFIED`.
