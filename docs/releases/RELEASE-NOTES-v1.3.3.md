# Zero-Mem v1.3.3 Release Notes (V133 — defect remediation)

**Date:** 2026-08-23 · **Scope:** DEF-001 + DEF-002 (see `docs/defects/DEFECT-REGISTRY.md`)

## Fixes

### DEF-001 — M7 budget `verified_rank` enum misalignment (retrieval ordering)
`src/integration/m7/budget.py` `_order_key` compared `item.verification` against
`("verified", "confirmed")`. **Neither string is a `VerificationStatus` member**
(enum: `none`, `direct_tool_output`, `user_confirmation`, `deterministic_verification`,
`approval`; `"confirmed"` belongs to `LifecycleStatus`). Consequently genuinely
verified items never received `verified_rank = 0` — the verified-priority ordering
inside the bounded evidence budget was inert for all real memory events.

**Fix:** reuse the eligibility pattern — `frozenset(v.value for v in
VerificationStatus if v.value != "none")`, identical to `_VERIFIED_STATUSES` in
`eligibility.py` (V132-01 alignment).

**Regression evidence (RED-first):** `tests/unit/test_v133_def001_budget_verified_rank.py`
- RED (pre-fix): `1 failed in 0.38s` — `verification='direct_tool_output' must yield verified_rank 0`
- GREEN (post-fix): `51 passed in 0.90s` (4 new DEF-001 tests + full
  `test_m7_3_evidence_builder` + `test_v130_03_state_primary` regression)

### DEF-002 — distribution version drift
`zero_mem/version.py` was still `1.3.1` while tags `v1.3.2` (and now `v1.3.3`)
were published. Bumped to `1.3.3`. `pyproject.toml` version is dynamic
(`attr = zero_mem.version.__version__`), so no other hardcode exists; packaging
tests pass (`4 passed`).

### DEF-006 — version pin propagation (found during full-suite verification)
The DEF-002 bump left 8 hardcoded `"1.3.1"` strings in the packaging pins:
`release_helpers/release_common.py:127` (manifest gate — made the installer
reject any new-version bundle), plus test pins in `test_pkg1_packaging.py`,
`test_pkg2_packaging.py`, `test_pkg6_upgrade_lifecycle.py`. All updated to
read/expect `1.3.3`. RED: 13 packaging failures → GREEN after propagation.

### DEF-007 — zm_verifications missing provenance columns (found during full-suite verification)
`zm_verifications` (migrate_7) lacked the `trace_id` / `session_id` /
`profile_id` provenance columns every other M4 table has, and the projector
silently dropped them on INSERT even though `VerificationOp` carries them.
Downstream effect: EvidenceItems built from verification rows surfaced
`profile_id=None` and non-enum `lifecycle=None`, so M8.5 scope calibration
misclassified an in-scope, fully authorized verification as
`excluded_unauthorized_scope` (score unavailable) and M8.6 authority checks saw
a lifecycle value outside the closed enum.

**Fix (schema-first, additive, derived-only):**
- `src/storage/migrations/migrate_12.py` — schema v12: 3 idempotent
  `ADD COLUMN`s; values recoverable from canonical replay.
- `src/project_memory/projector.py` — persist `op.trace_id/session_id/profile_id`.
- `src/project_memory/reader.py` — `VerificationView` exposes provenance +
  `lifecycle_status="active"` marker (same convention as ProjectArtifactView).
- `src/project_memory/rebuild.py` — `_recreate_m4_tables()` re-applies
  migration 12 after migrate_7.
- `src/integration/m7/evidence_builder.py` — normalize missing lifecycle to
  `"active"` (matching eligibility convention) as defense-in-depth.
- Schema-version literals across m8/integration introspection + tests bumped 11→12.

**Final suite evidence:** `3477 passed, 7 skipped, 0 failed`
(Python 3.13.15, isolated HOME, full canonical run).

## Process change

A mandatory defect registry was established at `docs/defects/DEFECT-REGISTRY.md`
and wired into `AGENTS.md` and `WORKSPACE-POLICY.md`: every defect must be
registered before any fix code is written; fixes follow
registry → RED-first test → smallest fix → focused test → full suite →
entry closed with verbatim evidence.

## Known limitations / deferred defects

- DEF-003 (crash/power-loss durability proof test) — planned v1.3.4.
- DEF-004 (knowledge-space grant authorization) — planned v1.4.x, needs ADR.
- DEF-005 (enrichment adapter wiring) — backlog.

## Authorization

Maintainer granted full-cycle self-decide authorization in chat on 2026-08-23
(fix → test → publish GitHub v1.3.3), recorded in the defect registry history
and the git mutation record.
