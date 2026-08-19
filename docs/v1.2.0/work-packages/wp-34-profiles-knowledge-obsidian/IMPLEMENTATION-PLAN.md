# WP-34 Implementation Plan

**Status:** VERIFIED
**Baseline SHA:** `7d871a95017c250f2d27a6e284ccfc6ad6f3c02e`

## Current repository state

The canonical tree already contains the M9.1–M9.6 projection surface under `src/projection/`, the controlled CLI `scripts/project_to_obsidian.py`, M9 acceptance/runbook documentation, and focused tests covering paths, identity, security, projection, manifest lifecycle, ownership/edit conflicts, and hardening. `project-state.yaml` records M9 as verified, while the v1.2 WP-34 package scaffold was not yet reconciled. This WP therefore qualifies existing behavior rather than duplicating M9.

Relevant existing surfaces:

- `src/projection/config.py`, `paths.py`, `contracts.py`, `identity.py`: explicit configuration, closed vocabulary, scope-aware identity, path boundary.
- `src/projection/engine.py`, `eligibility.py`, `render.py`: authorized-read orchestration, deterministic eligibility, DATA-only rendering.
- `src/projection/manifest.py`, `reconcile.py`, `ownership.py`, `writer.py`: rebuildable derived lifecycle, safe retirement, human ownership/edit conflict handling.
- `src/projection/links.py`, `conflicts.py`: provenance navigation and unresolved conflict presentation.
- `scripts/project_to_obsidian.py`: dry-run-first controlled operator entry point.

## Gap analysis

1. WP-34 package documentation is a scaffold and does not record the existing M9 implementation.
2. Existing M9 acceptance is historical evidence; WP-34 must rerun relevant tests against the current v1.2 working tree and its WP-29/WP-32 boundaries.
3. Knowledge-space isolation must be explicitly checked against current contracts; if no existing projection surface can safely expose it, the result is a documented limitation, not an invented field or fallback.
4. No hybrid/vector or new Obsidian subsystem is justified or required.

## Planned increments

1. Planning reconciliation and self-review of current M9 code, authorities, and tests.
2. Focused WP-34 acceptance: M9.1–M9.6 tests plus cross-scope/authorization parity checks.
3. Minimal correction only for a demonstrated current-tree failure.
4. Isolated full regression, compile/diff/security checks, final Graphify, independent review.
5. Evidence/state transition to VERIFIED; no real-vault apply.

## Expected files

Primary expected changes are package documentation and, only if a failing acceptance case requires it, a minimal existing `src/projection` or test change. No new package, schema, dependency, or canonical-storage file is planned.

## Contracts and data flow

`ProjectionRequest` → explicit `AccessRequest` per resource type → `AuthorizedReadService` → authorized M4 views → deterministic eligibility → deterministic render → bounded managed-root writer/reconcile. Canonical JSONL and SQLite remain read-only inputs; Markdown and manifest are disposable derived projection state.

## Migration / compatibility / rollback

No migration and no public API change are planned. Existing v1.1/M9 callers remain compatible. Rollback is removal of WP-34 documentation or a minimal reverted correction; no canonical or real-vault rollback is authorized or needed.

## Security and provenance

Authorization precedes any note materialization. Scope and `resource_type` are preserved. Note identity includes canonical scope/resource fields. Provenance contains source references without promoting projection data to authority. Path containment, symlink rejection, ownership signals, secret baseline, and hostile Markdown escaping remain mandatory.

## Test strategy

- Focused: `tests/unit/test_m9_1_paths.py`, `test_m9_1_identity.py`, `test_m9_1_security.py`, `test_m9_2_projection.py`, `test_m9_3_provenance_links_conflict.py`, `test_m9_4_manifest_lifecycle.py`, `test_m9_4_integration.py`, `test_m9_4_incremental_retirement.py`, `test_m9_5_ownership_edit_boundary.py`, `test_m9_6_hardening.py`.
- Relevant regressions: WP-29 authorization, WP-32 context, M5/M6.6/M7/M8 integration as required by acceptance.
- All vault/store fixtures use isolated temporary runtime paths; no real-vault apply is performed.

## Open questions

- Knowledge-space projection is only accepted where an existing authorized contract exposes it; otherwise record `NOT_PRESENT_IN_CURRENT_SURFACE` without inventing a new schema.
- Historical M9 evidence references a different development repository; current verification will rely on current-tree execution, not historical claims.

## Plan validation

This plan is validated against the current repository: WP-29, WP-32, and WP-33 are VERIFIED; M9 source/tests are present; no architecture escalation is required for routine qualification. Status remains PLANNING until the package self-review and acceptance commands are executed.
