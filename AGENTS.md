# Zero-Mem Agent Guide

## Project State

- Released baseline: **v1.0.0**, annotated tag `v1.0.0` at commit `79989f34ce3578f275a7b910c8a189896ce9ad57`.
- Reconciliation point: `origin/master` at `78c4bb46b88b8ce9987c6882b24201e08b82a7f0`, verified 2026-08-14.
- Target: **v1.1.0**.
- Current phase: **V1.1.0 RE-PLANNING**.
- Current work package: **WP-00 — Baseline Reconciliation and Delta Audit**.
- Source modification: **NOT AUTHORIZED**.
- Git publication: **WAITING FOR MAINTAINER APPROVAL**.

The reconciliation point is one commit after the v1.0.0 tag. That commit reorganizes repository documentation and updates references to the moved paths. It does not remediate F-001 through F-014; all source blobs named by those findings are identical at the tag and reconciliation point.

## Source Freeze

Treat implementation and executable artifacts at the exact reconciliation point as read-only. Findings, plans, approval of planning text, merge of a planning PR, or a request to “continue” do not authorize a fix.

During V1.1.0 RE-PLANNING, do not modify `zero_mem/`, `src/`, `tests/`, `benchmarks/`, `packaging/`, scripts, migrations, schemas, dependency metadata, runtime configuration, CI, tags, or releases. The only writable area is `AGENTS.md` and `docs/`.

Implementation begins only after a maintainer names one work package, its objective, its exact implementation write scope, required tests/benchmarks, and branch/PR workflow.

## Authority Order

Authority is domain-specific; a later status record does not rewrite product intent, and a specification does not override observed source behavior.

| Domain | Authority | Rule |
|---|---|---|
| Product specification | `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` at the reconciliation point | Defines product goals and invariants. Where v1.1.0 narrows or defers an objective, the approved ADR and master plan must say so explicitly. |
| Implementation truth | Source, tests, schemas, migrations, packaging, configuration, and Git history at exact `origin/master` | Read the code and executable evidence. Do not infer behavior from plans or acceptance prose. |
| Historical implementation/acceptance evidence | `project-state.yaml`, `implementation-plan.json`, and `docs/acceptance/` at exact `origin/master` | Records milestone evidence and prior approvals; it does not authorize v1.1.0 work or prove current behavior beyond its bound commit/environment. |
| Observed audit truth | `docs/audit/` | Records findings, measurements, reconciliation status, and uncertainty. A finding is never implementation authorization. |
| Planned v1.1.0 truth | `docs/v1.1.0/MASTER_PLAN.md`, approved ADRs, `TRACEABILITY.md`, and work packages | Defines proposed target behavior and release gates. Proposed write scope is not current authorization. |
| Operational v1.1.0 status | `docs/v1.1.0/STATUS.md` | Names the one active WP and current authorization state. Historical milestone status files cannot mark a v1.1.0 WP active. |
| Implementation authorization | Explicit maintainer instruction plus the corresponding `STATUS.md`/WP update | Must name the WP and file scope. Chat history, prior plan approval, a commit, or a merged planning PR is insufficient by itself. |

If authorities conflict, preserve the conflict in audit/planning documentation and ask the maintainer. Do not silently choose an implementation outcome. Chat history is not project truth; it can provide the current instruction or authorization, which must be recorded in the repository governance documents before implementation.

## Product Invariants to Preserve

- Hermes remains an optional orchestration/adapter layer; the core must stay agent-agnostic.
- Sanitized canonical trace data remains append-first; SQLite/FTS indexes and projections remain rebuildable unless an approved ADR explicitly changes that model.
- Obsidian is a human-facing curated projection, not canonical raw storage or the retrieval engine.
- Authorization precedes influence; isolated or source-restricted reads must not leak scope.
- Verified state outranks assistant self-report; conflicts and provenance remain visible.
- Secrets are redacted or rejected before persistence.
- Normal memory operations use deterministic/local mechanisms and make no mandatory LLM call.

## Mandatory Reading Order

1. This file.
2. `docs/baseline/V1.0.0_BASELINE.md`.
3. `docs/v1.1.0/STATUS.md`.
4. `docs/v1.1.0/MASTER_PLAN.md`.
5. `docs/audit/FINDINGS_INDEX.md` and its current reconciliation record.
6. The active work package in `docs/v1.1.0/work-packages/`.
7. ADRs named by that work package.
8. Only then, the source/test/evidence files listed by that package at the exact reconciliation commit.

## Work Package Protocol

- The active work package is the single `Current Work Package` named in `STATUS.md`.
- Valid statuses: `NOT STARTED`, `IN REVIEW`, `APPROVED`, `IN PROGRESS`, `BLOCKED`, `READY FOR REVIEW`, `VERIFIED`.
- During re-planning, `APPROVED` means design-approved only. It never authorizes implementation.
- Update `STATUS.md`, the active WP, traceability, and any affected ADR together when planning status changes.
- `Proposed Implementation Write Scope` is a future proposal. Only explicit maintainer authorization converts a subset of it into an allowed scope.
- WP-00 must be `VERIFIED` by a maintainer before any implementation WP can be approved for implementation.

## Findings and Uncertainty

- Finding IDs are stable. Record new observed issues with the next unused `F-###` ID; never reuse a resolved identifier.
- Reconciliation states are `CONFIRMED OPEN`, `PARTIALLY RESOLVED`, `RESOLVED`, `SUPERSEDED`, and `NEEDS VERIFICATION`.
- Do not reopen the resolved PKG-7 findings without regression evidence or proof that the closure evidence is insufficient.
- Do not turn limitations or uncertainty into defects or decisions. Use `NEEDS VERIFICATION` and route architectural choices through ADRs.
- Every planned change must trace to a finding or an approved product/release goal in `TRACEABILITY.md`.

## Git and Publication Gate

Reconciliation may edit only `AGENTS.md` and `docs/**`. Before any commit or push, present the assessment, findings table, files changed, critical path, validation results, and proposed branch/commit/PR to the maintainer. Do not create a branch, stage, commit, push, tag, release, or PR until the maintainer explicitly authorizes that Git mutation.

Default publication proposal after approval:

- Branch: `codex/v1.1-planning`
- Commit: `docs: add reconciled v1.1 development plan`
- Draft PR: `docs: reconcile Zero-Mem v1.1 development plan`

Merging the planning PR does not authorize any implementation WP.
