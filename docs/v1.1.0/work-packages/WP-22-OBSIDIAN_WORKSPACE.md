# Work Package: WP-22 — Obsidian Knowledge Workspace, Projection, and Write-Back

**ID:** WP-22

**Status:** NOT STARTED

**Priority:** P1

## Objective

Deliver the canonical one-Vault Obsidian workspace as a provenance-complete, rebuildable projection with required operating views and a reviewed, authorized, append-first write-back lifecycle.

## Why

Exact master M9 verifies a safe deterministic one-way projection and edit-conflict preservation but explicitly excludes write-back and Candidate Review. The canonical specification requires controlled bidirectional synchronization and makes Obsidian the main human-facing knowledge workspace.

## Canonical Requirements and Sources

REQ-OBS-001 through REQ-OBS-012 and related lifecycle/security requirements in `SPEC_TRACEABILITY.md`; canonical DOCX §§5, 9, 12, 14.4, 18 stage 9, 20, 21.1; ADR-008; `OBSIDIAN_WORKSPACE_CONTRACT.md`.

## Scope

- Required Vault views, namespace, note schema/provenance, projection trigger/version/idempotency/stale/delete behavior.
- Human ownership/path/symlink protection compatible with exact-master M9.
- Candidate detection, review queue, validation, authorization, conflict detection, approved/rejected write-back, canonical append, and regeneration.
- Projection/write-back security, recovery, migration, performance, and operator runbook.

## Out of Scope

Using Obsidian as raw/canonical storage or retrieval engine, writing outside managed subtree, modifying `.obsidian/`, direct raw-trace overwrite, auto-approval of arbitrary edits, mandatory plugin dependence, or routine LLM use.

## Dependencies

WP-04, WP-05, WP-08, WP-13, WP-14, WP-15, WP-20; ADR-008.

## Architecture Constraints

Projection is rebuildable and provenance-complete; raw traces are append-first; authorization precedes projection and write-back; human/unknown files are preserved; conflicts remain visible; secrets are rejected before any queue/manifest/canonical write; operations are deterministic/local with zero routine LLM calls.

## Files / Components Expected to Change

Future authorization may name the minimum subset of `src/projection/**`, project-memory readers, canonical write-back/candidate contracts, migration/config/status/CLI modules, and direct tests/benchmarks/runbooks. Exact paths require maintainer authorization.

## Files / Components That Must Not Change

Hermes core, human-owned Vault paths, `.obsidian/`, raw historical traces in place, unrelated source, or any executable path before authorization. Planning phase permits only `docs/**`.

## Implementation Tasks

1. Preserve and inventory M9 projection/ownership/security compatibility.
2. Implement required views and provenance-complete note schema.
3. Implement explicit projection triggers, manifest/version/watermark, stale/delete, clean rebuild, and no-loop origin markers.
4. Implement the write-back/review state machine and canonical append integration.
5. Bind conflict taxonomy to WP-14 and profile/write authorization to WP-20.
6. Add migration, recovery, status, benchmarks, and operator documentation.

## Acceptance Criteria

- Every required view and note field in `OBSIDIAN_WORKSPACE_CONTRACT.md` is present and source-traceable.
- Approved, rejected, conflict, duplicate, stale, concurrent, unauthorized, malformed, delete/tombstone, isolation, idempotency, rebuild, security, and no-loop scenarios all pass.
- No note edit directly overwrites raw trace, verified state, or derived SQLite; only an approved candidate creates one append-first canonical record.
- A clean rebuild from canonical records, artifacts, approved write-back records, and policy/config reproduces byte-equivalent eligible projections.
- Vault content remains readable without a required plugin; `.obsidian/` and non-managed human files remain byte-identical.

## Negative and Regression Tests

All `OBSIDIAN_WORKSPACE_CONTRACT.md` scenarios plus exact-master M9 ownership, injection escaping, authorization, sensitivity, symlink, real-vault integrity, deterministic manifest, human-edit preservation, and zero-write-back regressions until the new reviewed path is explicitly invoked.

## Migration and Compatibility Impact

Existing M9 managed files/manifests must load safely. Pre-v1.1 human edits become candidates/conflicts without overwrite. Projection schema/version migration is previewable, idempotent, backed up, interruptible, and rollback-capable.

## Security / Privacy Impact

High-impact human-edit/write boundary. Enforce managed-root containment, explicit identity/write authorization, privacy ceiling, secret rejection, non-probing errors, content-safe conflict metadata, and no implicit trust of local edits.

## Performance Impact and Benchmarks

Measure initial projection, incremental update, unchanged rerun, candidate scan, validation, conflict generation, approved write-back, regeneration, rebuild, memory, disk, and note-count scaling. Projection is batch/event-important, not every agent turn.

## Observability

Expose projection/canonical watermark, version, eligible/created/updated/retired/skipped counts, pending review/conflict counts, last safe error, and backlog without note content or hidden source IDs.

## Rollback

Restore prior projection/config/manifest from backup or rebuild managed output. Approved canonical write-back records are never silently deleted; reversing them requires an authorized compensating/superseding record. Human files remain preserved.

## Exit Gate and Traceability

Exit requires ADR-008 approval, all required-view/write-back/conflict/security/performance/migration tests passing, exact-master M9 regressions green, and all mandatory REQ-OBS rows `COVERED` with evidence.

## Planning and Implementation Authorization

This package is design-only in the current phase. Proposed source/test scopes are not authorization.
