# M4.4 — Final Acceptance Evidence (Current Project State reducer)

Authoritative spec: `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`
Approved M4 plan: `.hermes/plans/2026-08-07_000004-m4-project-memory-plan.md`
Prior increments: `acceptance-m4.1.md` (M4.1 VERIFIED), `acceptance-m4.2.md`
(M4.2 VERIFIED), `acceptance-m4.3.md` (M4.3 VERIFIED). M4.4 scope: deterministic,
idempotent **Current Project State** reducer only (create/update/supersede/
transition/delete/active-uniqueness/conflict/idempotence/transaction-safety/
determinism). No Verification projector, no Artifact projector, no M4 read API,
no M4.5+/M5 behavior.

## Starting state (verified)
- HEAD: ac08ad15e2d61d1ff4d7af3cb0a9155a5f98d853
- M0–M3: VERIFIED; M4.1/M4.2/M4.3: VERIFIED; schema: v7
- Canonical suite: 727 passed, 3 skipped
- Working tree: clean

## Implemented (M4.4)
- `src/project_memory/contracts.py`: `StateOp` typed envelope (explicit
  `state_key` — never invented; `scope` defaults to `project:<project_id>` only
  when `state_key` present; lifecycle/domain-state split; promotion guard for
  `assistant_claim`; `M4Domain.STATE` added).
- `src/project_memory/projector.py`: `project_state(conn, op)` + `STATE`
  classification in `classify_event_for_m4`.

## Authoritative design decisions (evidence-based)
- The canonical event envelope (`src/capture/event_types.py`,
  `src/capture/validation.py`) has NO `state` event type; validation rejects
  unknown `event_type`. Per "Do not invent event names merely for convenience.
  Use repository evidence," M4.4 consumes an EXPLICIT typed operation envelope
  (`StateOp`); it never infers state from prose, timestamps, trace_id,
  embeddings, or LLM output. `classify_event_for_m4` projects only on an
  explicit `m4.{domain,identity,op}` block; generic events → `CLASSIFY_SKIP`.
- `state_key` is the explicit logical slot (NULL when absent; record preserved,
  no uniqueness, surfaced as missing-key). `trace_id` is NEVER used as
  `state_key`. `scope` defaults to `project:<project_id>` only when `state_key`
  is present (per approved plan lines 207-212).
- Active value selected by `lifecycle_status`, NEVER by timestamp.

## Schema boundary (M4.1 VERIFIED, not modified)
- M4.4 uses the VERIFIED v7 `zm_project_state` table as-is (no migration v8;
  migrate_7 unchanged). `id` autoincrement PK (not a stable external id);
  active-uniqueness partial index `uq_zm_project_state_active ON
  (project_id, scope, state_key) WHERE lifecycle_status='active' AND
  state_key IS NOT NULL`.
- Deterministic model: each state mutation INSERTS a NEW row; update/supersede
  marks the prior active row `superseded` (history preserved in the derived table
  and in canonical JSONL). Active-selected-by-lifecycle guarantees no
  timestamp-based selection.
- Documented M4.1 nuance (not an M4.4 regression): the partial unique index
  enforces active-uniqueness when `scope` is NON-NULL (the normal, intended
  case); when `scope` is NULL, SQLite's "NULL in an indexed column is distinct"
  quirk means the index does not catch two active rows with the same
  `(project_id, state_key)` at project scope. This is a pre-existing M4.1 schema
  characteristic, reported for transparency; M4.4 does not silently alter
  migration 7.

## Behavior coverage (tested)
- Identity/key: explicit `state_key` preserved; absent key NULL; `trace_id` not
  used as key; scope defaults to `project:<id>` when key present.
- State/lifecycle: generic `state_value` separate from `lifecycle_status`; closed
  enum enforced; `proposed` not allowed as lifecycle; active/superseded/
  conflicted/archived accepted only when explicitly supplied.
- Creation/idempotence: creation; repeated-create idempotent (no duplicate);
  update/supersede marks prior `superseded`; idempotence is content-based
  (logical fields only, NOT timestamp — a re-projection that omits
  `created_at` is still recognized as a noop).
- Active uniqueness: one active per project/scope/non-NULL key; a bare `create`
  for an existing active key with differing content is a sanitized `ConflictError`
  (existing retained, no silent overwrite); `update`/`supersede` explicitly retire
  prior; different key allowed; multiple active NULL-key allowed; inactive
  same-key history allowed.
- Supersession: explicit B supersedes A (A marked superseded, B active, `supersedes`
  link set to `state:<id>`); missing target rolls back (no partial row); supersede
  requires explicit state_key; idempotent noop on identical re-supersede.
- Conflict: explicit `conflicted` (non-active) row coexists with an active row
  for the same key (no dual-active violation, no winner); both sources + provenance
  retained; no automatic mutation of other records to `conflicted`; conflict
  operation transaction-safe.
- Transition/delete: explicit lifecycle transition; logical delete (deleted);
  history preserved.
- Safety/boundaries: `assistant_claim` not auto-promoted; raw SQLite errors not
  leaked (sanitized); no secrets; JSONL unchanged; schema v7; M3 TRUE READ-ONLY
  green; no real `~/.hermes` writes; no LLM/network imports; no Verification /
  Artifact projector; no broad M4 read API; no M4.5+/M5.
- Determinism: incremental == replay; repeated replay deterministic.

## Verification order results
1. Syntax/collection: `compileall` OK.
2. Focused M4.4: **35 passed** (`tests/unit/test_m4_state.py`).
3. Combined M4 (M4.1 + M4.2 + M4.3 + M4.4): **145 passed** (32 + 38 + 40 + 35).
4. M2/M3 lifecycle + read-only compatibility: **220 passed**.
5. Full canonical suite: **762 passed, 3 skipped** (no deselection).
   (Prior M4.3 baseline was 727 passed, 3 skipped; +35 M4.4.)

## Ad-hoc verification (fresh, post-edit, /tmp, removed after run)
Covered: explicit key + scope default; NULL key (trace_id not key); invalid
lifecycle rejected; repeated-create idempotence; update marks prior superseded;
explicit supersede links prior; missing target rolls back (no partial); one active
per key (second active create conflicts, existing retained); different key allowed;
multiple active NULL-key allowed; explicit conflict preserved (no winner);
transition; delete; assistant_claim not promoted; replay determinism; classify
generic→SKIP / structured→STATE; schema v7. Result: **23/23 ALL PASS**.

## Regression recheck (M4.1 + M4.2 + M4.3 must remain VERIFIED)
- M4.1 (32) + M4.2 (38) + M4.3 (40) in the combined run: all green.
- migration v7, lifecycle CHECK, decision/state active partial unique indexes,
  Charter/Requirement/Decision projection, M3 TRUE READ-ONLY: all green.

## Acceptance criteria
- All M4.4 acceptance criteria pass.                       ✓
- M4.1/M4.2/M4.3 remain VERIFIED.                          ✓
- Focused M4.4 passes (35).                                ✓
- Combined M4 focused passes (145).                        ✓
- Compatibility passes (220).                              ✓
- Canonical suite passes (762/3).                          ✓
- State_key explicit; no trace_id key fallback.            ✓
- Active uniqueness works (non-NULL scope/key).            ✓
- NULL-key behavior safe.                                  ✓
- Supersession explicit; history preserved.                ✓
- Conflict preserves evidence; no automatic winner.        ✓
- assistant claims not auto-promoted.                      ✓
- Replay deterministic.                                    ✓
- Schema remains v7.                                       ✓
- JSONL canonical + unchanged.                             ✓
- No M4.5+/M5 behavior.                                    ✓
- Working tree clean after commit.                         ✓

## Record
- starting_commit: ac08ad15e2d61d1ff4d7af3cb0a9155a5f98d853
- implementation_commit: 6e2f19e6b1453a5dc373d0737350148478a627c7
- tested_commit: 6e2f19e6b1453a5dc373d0737350148478a627c7
- evidence/state-binding commit: <TBD>
- focused M4.4 result: 35 passed
- combined M4 result: 145 passed
- compatibility result: 220 passed
- canonical result: 762 passed, 3 skipped
- current HEAD after closeout: <TBD>
- schema version: 7
- files changed: src/project_memory/contracts.py,
  src/project_memory/projector.py, src/project_memory/__init__.py,
  tests/unit/test_m4_state.py
- failed/no-op patches: none (3 test-logic bugs + 1 product idempotence fix
  during dev: NULL-key cross-talk in probe; missing created_at in ad-hoc probe;
  supersede-missing-target test expectation; product fix — idempotence now
  content-based, ignoring timestamp)
- working-tree status: clean (after commit)

## Conclusion
M4.4: VERIFIED
M4 overall: IN PROGRESS
Schema version: 7
Next: M4.5 — Verification + Artifact integration
