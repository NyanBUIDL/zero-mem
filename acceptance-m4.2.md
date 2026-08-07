# M4.2 — Final Acceptance Evidence (Project Charter + Requirement Registry projection)

Authoritative spec: `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`
Approved M4 plan: `.hermes/plans/2026-08-07_000004-m4-project-memory-plan.md`
Prior increment: `acceptance-m4.1.md` (M4.1 VERIFIED, schema v7)
M4.2 scope: deterministic, idempotent projection for **Project Charter** and
**Requirement Registry** domains only. No Decision Log, no Current Project
State reducer, no Verification projector, no Artifact Registry, no M4 read API,
no M4.3+/M5 behavior.

## Starting state (verified)
- HEAD: 80f7337
- M0–M3: VERIFIED; M4.1: VERIFIED; schema: v7
- Canonical suite: 649 passed, 3 skipped
- Working tree: clean

## Implemented (M4.2)
- New package `src/project_memory/`:
  - `contracts.py` — typed operation envelopes `CharterOp` / `RequirementOp`
    (explicit `op` in {create, update, supersede, transition, delete});
    closed `LIFECYCLE_ENUM` (§7.1); sanitized errors
    `M4ProjectionError` / `MissingIdentityError` / `MissingRequiredFieldError` /
    `InvalidLifecycleError` / `InvalidTransitionError` / `ConflictError` /
    `PromotionBlockedError` (no raw SQL/payload/secret leakage).
  - `projector.py` — `project_charter(conn, op)`, `project_requirement(conn, op)`,
    `classify_event_for_m4(event)`.
- Writer boundary kept separate from M3 TRUE READ-ONLY (`open_readonly` +
  `PRAGMA query_only=ON`). Projector consumes explicit typed ops; it never
  reads for retrieval and never calls `ensure_schema`.

## Authoritative design decisions (evidence-based)
- The canonical event envelope (`src/capture/event_types.py`,
  `src/capture/validation.py`) has **no** `charter`/`requirement` event types
  and validation rejects unknown `event_type` values. Per the rule "Do not
  invent event names merely for convenience. Use repository evidence," M4.2 is
  a deterministic write/projector driven by an **explicit typed operation
  envelope** (the plan permits this: "If the plan defines a typed M4 operation
  envelope, use it exactly"). The projector never infers charter/requirement
  data from prose, timestamps, trace_id, or semantic similarity, and never
  invents event names.
- `classify_event_for_m4` projects ONLY when an event carries an explicit
  structured M4 block (`m4.domain` + `m4.identity` + `m4.op`); otherwise it
  returns `CLASSIFY_SKIP` (deterministic, no inference). A generic
  `assistant_claim` with requirement-like text is NOT projected.

## Schema boundary (M4.1 VERIFIED, not modified)
- M4.1 v7 uses `charter_id` / `requirement_id` as a single PRIMARY KEY (one row
  per identity). The M4.2 requirement to "preserve the prior version / do not
  silently overwrite the prior row" is satisfied as follows, WITHOUT modifying
  migration 7:
  - The derived table holds the CURRENT version per identity with an
    incremented `version` counter; full historical versions are preserved in
    the canonical JSONL (authoritative, append-only, rebuildable) and
    reproduced by rebuild.
  - `SUPERSEDE` between DISTINCT identities preserves BOTH rows (the prior is
    marked `superseded`, the new `active` carries the explicit link).
- No migration v8 added. Schema remains v7. No M4.1 column/index/CHECK changed.

## Behavior coverage (tested)
- Charter: create; repeated-create idempotence; version (in-place bump, history
  in JSONL); explicit supersession (distinct id, prior preserved); active
  uniqueness (one active per project via v7 partial unique index); active
  selection by lifecycle_status, never MAX(created_at); invalid lifecycle
  rejected; domain `state` in separate column; logical delete (history
  retained, `deleted` is terminal); provenance retained; transaction rollback
  (no partial state); replay determinism.
- Requirement: create; explicit `requirement_id` preserved; missing stable
  identity NOT invented; trace_id NOT used as identity; `assistant_claim` does
  NOT auto-promote to active (guarded); lifecycle/domain `state` separation;
  explicit transition; terminal `deleted` guard; repeated-event idempotence;
  explicit supersession (prior preserved + linked, no physical delete); no
  timestamp-based supersession; conflict preserved (existing retained, no
  winner, no overwrite); logical delete; provenance; transaction rollback;
  replay determinism.
- Cross-cutting: no duplicates; no raw SQLite error leakage; no secrets; JSONL
  immutability (projection creates no JSONL); schema stays v7; M3 TRUE READ-ONLY
  unchanged; no writes during M3 queries; no real `~/.hermes` writes; no LLM/
  network imports; no Decision/State/Verification/Artifact behavior; no M4.3+/M5.

## Verification order results
1. Syntax/collection: `compileall` OK.
2. Focused M4.2: **38 passed** (`tests/unit/test_m4_projector.py`).
3. Combined M4.1+M4.2: **70 passed** (32 M4.1 + 38 M4.2).
4. M2/M3 lifecycle + read-only compatibility: **220 passed**.
5. Full canonical suite: **687 passed, 3 skipped** (no deselection).
   (Prior M4.1 baseline was 649 passed, 3 skipped; +38 M4.2.)

## Ad-hoc verification (fresh, post-edit, /tmp, removed after run)
Covered: Charter create + explicit supersede; Requirement create; repeated-event
idempotence (no duplicate); missing requirement_id raises (not invented);
assistant_claim not promoted; lifecycle/domain-state separation;
transaction rollback (no partial row); schema remains v7; classify
generic→SKIP, structured→REQUIREMENT. Result: ALL PASS.

## Secret safety
Synthetic secrets only; tests assert error MESSAGES (not exception class) and
never print secret values. No secret-bearing payload reaches errors/logs.

## Regression recheck (M4.1 must remain VERIFIED)
- migration v7: covered by `test_m4_schema.py` (32 pass, in combined run).
- lifecycle CHECK, active Charter uniqueness index, NULL-safe key semantics,
  downgrade behavior, schema version: all green in combined M4 run + full suite.

## Acceptance criteria
- All M4.2 acceptance criteria pass.  ✓
- M4.1 remains VERIFIED.              ✓
- Focused M4.2 passes (38).           ✓
- Combined M4.1–M4.2 passes (70).     ✓
- Affected compatibility passes (220). ✓
- Canonical suite passes (687/3).     ✓
- Charter history/version deterministic.           ✓ (version counter + JSONL)
- Requirement identity explicit.                    ✓
- No assistant-claim auto-promotion.                ✓
- Supersession explicit.                            ✓
- Conflicts preserved.                              ✓
- Projector idempotent.                             ✓
- Transactions atomic.                              ✓
- Schema remains v7.                               ✓
- JSONL canonical & unchanged by projection reads.  ✓
- No M4.3+ behavior.                               ✓
- Working tree clean after commit.                 ✓

## Record
- starting_commit: 80f7337
- implementation_commit: 57915ed8c7b63c4efa219b7ef1638ee76a8061bd
- tested_commit: 57915ed8c7b63c4efa219b7ef1638ee76a8061bd
- evidence/state-binding commit: <TBD>
- focused M4.2 result: 38 passed
- combined M4 (M4.1+M4.2) result: 70 passed
- compatibility result: 220 passed
- canonical result: 687 passed, 3 skipped
- current HEAD after closeout: <TBD>
- schema version: 7
- files changed: src/project_memory/__init__.py, src/project_memory/contracts.py,
  src/project_memory/projector.py, tests/unit/test_m4_projector.py
- failed/no-op patches: none
- working-tree status: clean (after commit)

## Conclusion
M4.2: VERIFIED
M4 overall: IN PROGRESS
Schema version: 7
Next: M4.3 — Decision Log, supersession, and conflict
