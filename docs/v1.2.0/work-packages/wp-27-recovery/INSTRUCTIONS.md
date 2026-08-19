# WP-27 Instructions

## Objective

Provide fail-closed detection and deterministic recovery of missing, stale, corrupt, incompatible, or interrupted derived state from canonical JSONL and approved rebuild functions.

## Dependencies

- WP-25 Runtime Ownership — VERIFIED.
- WP-26 Projection — VERIFIED.

## Scope

- Diagnose derived-state health against canonical checkpoints/schema.
- Rebuild disposable SQLite/projection state from canonical JSONL using existing rebuild paths.
- Handle missing DB, stale checkpoint, corruption, incompatible schema, interrupted rebuild, and backup/restore interruption.
- Preserve canonical bytes and provenance; expose sanitized recovery status.

## Out of scope

No canonical rewrite/deletion, destructive historical migration, authorization/API/sidecar/Hermes/context/retrieval, or release publication. No repair of canonical history from SQLite.

## Required invariants

- Canonical JSONL remains authoritative and read-only.
- Derived state is rebuildable and never promoted to truth.
- Recovery fails closed on source identity/hash/schema mismatch.
- Rebuild is atomic or leaves an explicitly unavailable derived state.
- No infinite retry; interrupted work is resumable or safely restartable.
- Diagnostics contain no payload, secrets, or exception text.

## Allowed changes

New recovery coordinator/diagnostic helpers, bounded tests, and narrow reuse of existing `diagnose`, `rebuild_from_jsonl`, SQLite backup, and migration APIs.

## Escalation conditions

Escalate if recovery requires destructive canonical operations, irreversible schema migration, a new source of truth, or cannot preserve canonical/rebuild invariants.

## Completion conditions

Planning package validated; all failure/rebuild/restart/backup tests pass; independent review passes; evidence and project state are updated to `VERIFIED`.
