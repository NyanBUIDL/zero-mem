# Work Package: WP-00 — Baseline Reconciliation and Delta Audit

**ID:** WP-00

**Title:** Baseline Reconciliation and Delta Audit

**Status:** READY FOR REVIEW

**Priority:** P1

**Categories:** Governance, Baseline, Audit, Release Control

## Objective

Bind the existing v1.1.0 plan to exact `origin/master`, reconcile the released v1.0.0 tag and all finding/authority evidence, and prove that implementation remains frozen before any implementation WP can be approved.

## Why This Exists

Planning cannot be implementation-ready when it is bound only to audit findings but not to the canonical product requirements. WP-00 prevents baseline drift, silent authority inversion, stale planning claims, and implementation authorization from being inferred from documentation approval.

## Related Findings

F-001 through F-014 are reconciliation inputs. WP-00 closes none of them. PKG7-AUD-001 through PKG7-AUD-004 remain resolved historical findings and are not reintroduced into the v1.1.0 backlog.

## Canonical Requirements

All requirements are discovery/reconciliation inputs; `SPEC_TRACEABILITY.md` is the normative requirement map. Canonical source is `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` at exact master, with historical architecture/acceptance and exact-master source used only for compatibility/feasibility evidence.

## Current State on master

- Exact master: `78c4bb46b88b8ce9987c6882b24201e08b82a7f0`, verified 2026-08-14.
- Annotated tag `v1.0.0` resolves to `79989f34ce3578f275a7b910c8a189896ce9ad57` and is the merge base.
- Master is one commit ahead: `78c4bb46` (`docs: organize post-v1 repository documentation`).
- The delta reorganizes documents and updates path references in manifests, comments/docstrings, a repository verification script, and tests.
- Every implementation/package blob named by F-001 through F-014 is identical at the tag and exact master.
- No implementation WP is authorized or in progress.

## Evidence

- [V1.0.0 baseline](../../baseline/V1.0.0_BASELINE.md)
- [Exact-master reconciliation](../../audit/MASTER_RECONCILIATION.md)
- [Finding reconciliation](../../audit/FINDINGS_RECONCILIATION.md)
- [Findings index](../../audit/FINDINGS_INDEX.md)
- [Traceability](../TRACEABILITY.md)
- [Canonical requirement traceability](../SPEC_TRACEABILITY.md)
- [Canonical alignment gap analysis](../reviews/SPEC_ALIGNMENT_GAP_ANALYSIS.md)
- Upstream [`project-state.yaml`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/project-state.yaml), [`implementation-plan.json`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/implementation-plan.json), [`docs/acceptance/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/docs/acceptance), and [`docs/audits/audit-pkg7.md`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/docs/audits/audit-pkg7.md)

## Read Scope

Read repository history, tag metadata, diff, product specification, governance files, acceptance/audit records, every WP/ADR, and source/test files necessary to validate F-001–F-014 against the exact master commit.

## Planning Write Scope

`AGENTS.md` and Markdown under `docs/**` only, including baseline, audit, v1.1.0 status, master plan, traceability, ADR annotations where needed, and WP metadata.

## Proposed Implementation Write Scope

None. WP-00 is documentation/audit work only and proposes no implementation, test, benchmark, schema, configuration, CI, or release-artifact mutation.

## Forbidden Scope

`zero_mem/`, `src/`, `tests/`, `benchmarks/`, `packaging/`, scripts, schemas, migrations, dependency metadata, runtime configuration, CI, tags, releases, and all Git publication mutations until separately authorized.

## Affected Components

Planning governance, baseline identity, finding ownership/status, work-package dependency order, release gates, and future implementation authorization.

## Files / Modules to Inspect

- [`AGENTS.md`](../../../AGENTS.md)
- [`docs/baseline/`](../../baseline/)
- [`docs/audit/`](../../audit/)
- [`docs/v1.1.0/`](../)
- Exact-master repository tree, especially the 14 finding paths listed in [FINDINGS_RECONCILIATION.md](../../audit/FINDINGS_RECONCILIATION.md)

## Desired State

One reviewable planning layer identifies the released baseline, exact reconciliation point, delta types, authority order, reconciled finding states/owners/closure tests, complete canonical requirement map, complete WP set, acyclic dependency graph, source freeze, and Git publication gate.

## Constraints

- Do not treat a finding as authorization to fix it.
- Do not treat historical milestone approval or a planning PR merge as v1.1.0 implementation authorization.
- Do not mark a finding resolved without source, test, or history evidence.
- Preserve the product invariants, canonical-data model, authorization-first behavior, and rebuild contracts.
- If master changes, rerun the delta check before publication.

## Reconciliation Tasks

1. Verify the annotated release tag, exact-master SHA, ancestry, and changed-path classification.
2. Reconcile F-001 through F-014 and preserve closed PKG-7 findings unless regression evidence exists.
3. Extract canonical requirements, build the 1:1 specification matrix, and record the pre-correction gap analysis.
4. Reconcile MASTER_PLAN, ADR ownership, work-package scope, dependencies, acceptance gates, and release gates.
5. Run an independent canonical-to-planning second pass and record structural, link, dependency, and source-freeze evidence.
6. Present the review packet and proposed Git publication separately; perform neither implementation nor Git mutation without explicit maintainer authorization.

## Recommended Direction

Approve this reconciliation as the planning baseline, publish it in a documentation-only draft PR, then review WP-01 as the first design package. Do not authorize source edits until WP-00 is maintainer-verified and the selected implementation WP receives a separate exact write scope.

## Dependencies

None.

## Blocks

WP-01 through WP-22 design approval and every future implementation authorization.

## Compatibility Impact

None at runtime. The reconciliation makes existing compatibility uncertainty explicit and routes it to WP-09/WP-10/WP-13.

## Performance Impact

None at runtime. Historical benchmark evidence is preserved; no new benchmark result is claimed.

## Migration Impact

None at runtime. It binds future WP-17 work to the annotated v1.0.0 tag and exact-master planning point.

## Tests Required

- Verify tag/master ancestry and exact SHAs.
- Verify every finding path's blob identity or inspect its delta.
- Verify F-001–F-014 coverage, primary owner uniqueness, and closure-test assignment.
- Verify WP-00–WP-22 presence and required/equivalent sections.
- Verify authority/status consistency and source freeze.

### Negative Tests

- A mismatched, missing, or non-ancestor release tag/exact-master SHA prevents review readiness.
- Any mandatory canonical requirement at `MISSING`, `PARTIAL`, or `CONFLICT` prevents review readiness.
- Any dependency cycle, broken local link, unpinned exact-master source link, duplicate primary owner, or active unauthorized WP fails reconciliation.
- Any changed executable/source path or attempted Git publication without explicit approval fails the source-freeze/publication gate.

### Regression Tests

- Re-run exact-master/tag identity and finding-path blob checks after any upstream change.
- Re-run canonical requirement/status/owner counts, dependency-cycle, WP-quality, link, and source-freeze checks after every planning edit.
- Confirm historical PKG-7 closures remain closed and implementation WPs remain NOT STARTED unless explicitly authorized.

## Benchmarks Required

None for reconciliation. Future performance closure benchmarks remain assigned to the owning WPs and WP-16.

## Acceptance Criteria

- Exact master and annotated v1.0.0 tag are recorded with their relationship.
- The intervening delta is classified as document/path, test/evidence, source behavior, completed remediation, open finding, or uncertainty.
- F-001–F-014 each have one reconciliation state, exact-master location, reason, primary owner, and closure validation.
- PKG-7 closures are preserved.
- Authority order covers product specification, implementation, historical evidence, observed audit, planned truth, operational status, and implementation authorization.
- WP-00–WP-22 contain every mandatory/equivalent field; no implementation WP is active or authorized.
- Dependency graph is acyclic, local links resolve, exact-master code links resolve, and no duplicate finding/canonical responsibility owner exists.
- `SPEC_TRACEABILITY.md` maps every extracted normative requirement; only canonical “Sau MVP” capabilities may be `DEFERRED`, and no mandatory row is `MISSING`, `PARTIAL`, or `CONFLICT`.
- `git diff --check` and `git status --short` are recorded; every changed path is `AGENTS.md` or `docs/**`.
- Canonical requirement extraction, gap analysis, owner uniqueness, and second-pass parity audit are recorded; mandatory `MISSING`, `PARTIAL`, or `CONFLICT` prevents READY FOR REVIEW.

## Security / Privacy, Observability, and Rollback

Reconciliation reads only and records no secret or user-memory payload. Evidence reports exact source/version/hash and uncertainty. Planning rollback is a documentation revert only; it cannot change the frozen implementation or historical evidence.

## Exit Gate and Traceability

WP-00 is review-ready only when the exact-master baseline, F-001–F-014, canonical requirements, ADR/WP ownership, acyclic dependency graph, local links, source freeze, and both traceability files validate together. Maintainer verification remains required.

## Definition of Done

WP-00 reaches `READY FOR REVIEW` only after all acceptance checks pass. It reaches `VERIFIED` only when a maintainer reviews the assessment and explicitly accepts this reconciliation. Verification does not authorize publication or implementation unless those permissions are stated separately.

## Out of Scope

Fixing findings, running source formatters, changing runtime/test/configuration artifacts, selecting implementation details not approved by ADR review, committing, pushing, opening/merging a PR, tagging, or releasing.
