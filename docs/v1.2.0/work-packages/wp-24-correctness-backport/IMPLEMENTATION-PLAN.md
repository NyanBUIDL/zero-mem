# WP-24 Implementation Plan — Correctness Backport

**Status:** `VERIFIED`
**Baseline SHA:** `7d871a95017c250f2d27a6e284ccfc6ad6f3c02e`
**Workspace:** `/home/lenovo/Hermes Workspace/zero-mem-v1.1`
**Branch:** `NyanBUIDL-Zero-mem`
**Authorization:** `AUTONOMOUS_EXECUTION_AUTHORIZATION`, scope `WP-24..WP-35`; per-WP approval not required; release publication not authorized.

## Current repository state

The repository contains the v1.1 JSONL capture implementation in `src/storage/jsonl_capture.py` and a generic client in `zero_mem/core.py`. `EventWriter.append()` is typed as returning `None`; `ZeroMemClient.capture()` ignores the append result and returns `CAPTURED` whenever no exception is raised. The concrete writer already returns `AppendResult` and performs `flush`/`fsync`, so the smallest safe correction is to formalize that receipt at the client boundary and map non-durable outcomes to typed non-success. `zero_mem/recovery.py` currently queries the obsolete `memories` table, while the actual derived substrate uses `zm_*` tables and checkpoint/watermark metadata.

The worktree was dirty before this WP. Pre-existing changes include the v1.2 governance scaffolding, planning/state documents, and historical evidence artifacts. They are not treated as WP-24 implementation changes.

## Gap analysis

| Requirement | Current evidence | Gap |
|---|---|---|
| Durable capture acknowledgement | `JsonlCaptureStore` fsyncs and returns `AppendResult`; client returns success on any non-raising append | Client contract must inspect a typed receipt and require canonical durability |
| Failure cannot report success | Existing exception path is non-success, but a writer can reject/return non-durable without raising | Add explicit receipt status and defensive failure mapping |
| Recovery uses real schema | `diagnose()` executes `SELECT COUNT(*) FROM memories` | Inspect `zm_meta`, migration/checkpoint/watermark tables and classify missing/corrupt/stale/incompatible derived state |
| Artifact/release evidence | Historical v1.1 evidence exists; no WP-24 source-bound artifact check | Add a deterministic local artifact evidence command/test, without tag/publish |

## Exact implementation scope

1. Introduce a frozen, transport-neutral `AppendReceipt`/equivalent result contract at the canonical writer boundary, retaining compatibility with the concrete JSONL writer's duplicate/append information.
2. Update `ZeroMemClient.capture()` to return `CAPTURED` only when `canonical_durable` is true; map rejected, failed, duplicate, pending, and unavailable outcomes to typed statuses according to the implemented contract.
3. Update the concrete JSONL adapter only as needed to produce the receipt fields without changing append-only semantics, locking, sequence, deduplication, or durability order.
4. Replace obsolete recovery table access with read-only inspection of actual derived schema and checkpoint/watermark state. Recovery remains diagnostic/read-only in WP-24.
5. Add tests first for failed/non-durable append, successful durable append, duplicate classification, real-schema recovery, malformed/missing/corrupt/stale derived state, and immutability.
6. Add deterministic local artifact evidence for wheel/sdist build metadata/content/hash where the existing packaging conventions support it; do not publish or claim release readiness.

## Planned increments

### Increment A — Receipt contract and capture failure semantics

- RED: tests proving a non-durable/failed receipt cannot yield `CAPTURED`.
- GREEN: minimal receipt dataclass/protocol and client mapping.
- Regression: existing public API and JSONL capture tests.

### Increment B — Recovery schema correction

- RED: real derived database fixture with `zm_meta` and checkpoint/watermark state; prove obsolete `memories` query is not used.
- GREEN: read-only schema inspection and typed diagnosis.
- Regression: existing recovery and M2/M3 rebuild/read-only tests.

### Increment C — Artifact evidence and WP acceptance

- Run existing package build/acceptance helpers in isolated project-local environment.
- Record actual hashes/results and limitations; no publish/tag.
- Run self-review, diff/path audit, focused and full regression.

## Expected files/modules

Likely production files:

- `zero_mem/core.py`
- `src/storage/capture_boundary.py`
- `src/storage/jsonl_capture.py` only if receipt adaptation is required
- `zero_mem/recovery.py`

Likely tests:

- new WP-24 tests under `tests/unit/` or `tests/integration/`
- existing `tests/unit/test_wp08_public_api.py`, `tests/unit/test_wp14_recovery.py`, M1/M2 capture/rebuild tests

Documentation/evidence:

- `docs/v1.2.0/work-packages/wp-24-correctness-backport/*`
- `project-state.yaml` / `implementation-plan.json` only for scoped authorization and verified state metadata

## Interfaces/contracts

The receipt must expose at least: `status`, `event_id`, `sequence`, `canonical_durable`, `duplicate_class`, and `reason_code`. Exact status vocabulary must be closed and documented in the technical design. The client must not infer success from absence of an exception.

## Migration and compatibility impact

No schema migration is authorized or expected. Recovery reads existing derived schema in read-only mode. Existing v1.1 stores and historical JSONL remain untouched. Existing writers returning `None` are not silently treated as durable; compatibility behavior must be explicit and tested.

## Security and provenance impact

No new authorization surface. Preserve sanitized errors and redaction-before-persist. Receipt provenance identifies canonical event/sequence and derived condition without exposing raw payload or secrets.

## Recovery and rollback

Changes are additive and reversible by restoring the touched modules/tests. No destructive data operation is allowed. Recovery must not write either canonical JSONL or derived SQLite. If compatibility requires a destructive or ambiguous migration, stop and escalate.

## Test strategy

- Strict TDD for each production behavior: write one failing test, run it, implement the minimal correction, rerun focused test, then regression.
- Use `pytest` with isolated HOME/XDG roots where commands can touch user state.
- Run focused WP-24 tests, relevant v1.1/API/recovery tests, then the canonical suite.
- Run `git diff --check` and static secret/path scans on added lines.
- Run packaging evidence only with existing project tooling and no system-wide mutation.

## Open questions

- Exact canonical receipt field naming must follow the existing public contract and concrete `AppendResult`; resolve from source/tests during Increment A, not by inventing a competing status model.
- Exact derived checkpoint/watermark table columns must be read from the current migrations before implementation; no guessed `memories` schema.
- Artifact evidence threshold is evidence-only in WP-24; final release qualification belongs to WP-35.

## Plan validation

Validated against the current source, tests, Master Plan, Spec Amendment 001, ADR-009, and the WP-24 acceptance objectives. No unresolved architecture decision is required for the bounded correction. Plan status: `READY`.
