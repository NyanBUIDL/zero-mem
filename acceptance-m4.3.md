# M4.3 — Final Acceptance Evidence (Decision Log projection)

Authoritative spec: `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`
Approved M4 plan: `.hermes/plans/2026-08-07_000004-m4-project-memory-plan.md`
Prior increments: `acceptance-m4.1.md` (M4.1 VERIFIED), `acceptance-m4.2.md`
(M4.2 VERIFIED). M4.3 scope: deterministic, idempotent **Decision Log**
projection only (create/state/lifecycle/key/supersession/conflict/provenance/
transaction-safety/determinism). No Current Project State reducer, no
Verification projector, no Artifact projector, no M4 read API, no M4.4+/M5.

## Starting state (verified)
- HEAD: d683e29
- M0–M3: VERIFIED; M4.1: VERIFIED; M4.2: VERIFIED; schema: v7
- Canonical suite: 687 passed, 3 skipped
- Working tree: clean

## Implemented (M4.3)
- `src/project_memory/contracts.py`: `DecisionOp` typed envelope (explicit
  `decision_id`, nullable `decision_key`, lifecycle/domain `state` split,
  promotion guard for `assistant_claim`, self-supersession rejection).
  `M4Domain.DECISION` added.
- `src/project_memory/projector.py`: `project_decision(conn, op)` + `DECISION`
  classification in `classify_event_for_m4`.

## Authoritative design decisions (evidence-based)
- The canonical event envelope (`src/capture/event_types.py`,
  `src/capture/validation.py`) has NO `decision` event type; validation rejects
  unknown `event_type`. Per "Do not invent event names merely for convenience.
  Use repository evidence," M4.3 consumes an EXPLICIT typed operation envelope
  (`DecisionOp`); it never infers decisions from prose, timestamps, trace_id,
  embeddings, or LLM output. `classify_event_for_m4` projects only on an
  explicit `m4.{domain,identity,op}` block; generic events → `CLASSIFY_SKIP`.
- `decision_id` is the explicit stable identity; `trace_id` is NEVER used as
  identity or as `decision_key`. `decision_key` is nullable; NULL-key decisions
  coexist and do not falsely collide.

## Schema boundary (M4.1 VERIFIED, not modified)
- M4.3 uses the VERIFIED v7 `zm_decisions` table as-is (no migration v8; migrate_7
  unchanged). `decision_id` is PK (one row per identity; history in canonical
  JSONL, reproduced by rebuild). Active-uniqueness partial index
  `uq_zm_decisions_active ON (project_id, scope, decision_key) WHERE
  lifecycle_status='active' AND decision_key IS NOT NULL`.
- **Documented M4.1 nuance (not an M4.3 regression):** the partial unique index
  enforces active-uniqueness when `scope` is NON-NULL (the normal, intended
  case — all canonical M4.3 tests set `scope`). When `scope` is NULL, SQLite's
  "NULL in an indexed column is distinct" quirk means the index does not catch
  two active rows with the same `(project_id, decision_key)` at project scope.
  This is a pre-existing M4.1 schema characteristic, reported here for
  transparency; M4.3 does not silently alter migration 7.
- **Provenance column note:** the VERIFIED `zm_decisions` schema has no
  `created_at` column; temporal provenance is carried by `effective_at`. M4.3
  folds `effective_at or op.created_at` into `effective_at` and respects the
  VERIFIED schema (does not modify migration 7). Present provenance columns:
  `source_event_id`, `trace_id`, `session_id`, `profile_id`, `effective_at`.

## Behavior coverage (tested)
- Identity: explicit `decision_id` preserved; missing id not invented; trace_id
  not used as id; explicit `decision_key` preserved; absent key NULL; trace_id
  not used as key.
- State/lifecycle: generic `state` separate from `lifecycle_status`; closed enum
  enforced; `accepted/rejected/proposed` not allowed as lifecycle; active/
  superseded/conflicted accepted only when explicitly supplied.
- Creation/idempotence: creation; repeated-event idempotence; no duplicates.
- Active uniqueness: one active per project/scope/non-NULL key; second active
  same key rejected (ConflictError, existing retained); different key allowed;
  multiple active NULL-key allowed; inactive same-key history allowed.
- Supersession: explicit B supersedes A (A preserved + linked, B active); atomic
  active transition (A marked superseded BEFORE B promoted, never dual-active);
  no timestamp inference; missing target rolls back (no partial B); self-
  supersession rejected; explicit chain A<-B<-C preserved (no flattening);
  malformed cycle rejected/preserved safely (no cyclic graph formed).
- Conflict: explicit `conflicted` preserved; both sources + provenance retained;
  no winner; no newest-timestamp preference; no LLM resolution; NO automatic
  mutation of other records to `conflicted`; conflict operation transaction-safe.
- Safety/boundaries: `assistant_claim` not auto-promoted; raw SQLite errors not
  leaked (sanitized); no secrets; JSONL unchanged; schema v7; M3 TRUE READ-ONLY
  green; no real `~/.hermes` writes; no LLM/network imports; no Current State /
  Verification / Artifact projector; no broad M4 read API; no M4.4+/M5.
- Determinism: incremental == replay; repeated replay deterministic.

## Verification order results
1. Syntax/collection: `compileall` OK.
2. Focused M4.3: **40 passed** (`tests/unit/test_m4_decision.py`).
3. Combined M4 (M4.1 + M4.2 + M4.3): **110 passed** (32 + 38 + 40).
4. M2/M3 lifecycle + read-only compatibility: **220 passed**.
5. Full canonical suite: **727 passed, 3 skipped** (no deselection).
   (Prior M4.2 baseline was 687 passed, 3 skipped; +40 M4.3.)

## Ad-hoc verification (fresh, post-edit, /tmp, removed after run)
Covered: Decision creation + explicit key; NULL key (trace_id not key); multiple
active NULL-key coexist; same-key dual-active prevented (existing retained);
explicit supersession A->B (old preserved + linked); missing target rolls back
(no partial); no timestamp-based replacement; explicit conflict preserves both
(no winner); assistant_claim not promoted; lifecycle/domain-state separation;
replay determinism; classify generic→SKIP / structured→DECISION; schema v7.
Result: **20/20 ALL PASS** (scope set to match real usage; the NULL-scope index
quirk is documented above as an M4.1 characteristic, not an M4.3 defect).

## Regression recheck (M4.1 + M4.2 must remain VERIFIED)
- M4.1 (32 tests) + M4.2 (38 tests) in the combined run: all green.
- migration v7, lifecycle CHECK, decision active partial unique index, Charter
  projection, Requirement projection, M3 TRUE READ-ONLY: all green.

## Acceptance criteria
- All M4.3 acceptance criteria pass.                       ✓
- M4.1 remains VERIFIED.                                   ✓
- M4.2 remains VERIFIED.                                   ✓
- Focused M4.3 passes (40).                                ✓
- Combined M4 focused passes (110).                        ✓
- Compatibility passes (220).                              ✓
- Canonical suite passes (727/3).                          ✓
- Decision identity explicit; no trace_id key fallback.    ✓
- Active uniqueness works (non-NULL scope/key).            ✓
- NULL-key behavior safe.                                  ✓
- Supersession explicit + atomic; history preserved.       ✓
- Conflict preserves evidence; no automatic winner.        ✓
- assistant claims not auto-promoted.                      ✓
- Replay deterministic.                                    ✓
- Schema remains v7.                                       ✓
- JSONL canonical + unchanged.                             ✓
- No M4.4+ behavior.                                       ✓
- Working tree clean after commit.                         ✓

## Record
- starting_commit: d683e29
- implementation_commit: ae7db4f2bf8247933ef445ab699a6ff5f560e585
- tested_commit: ae7db4f2bf8247933ef445ab699a6ff5f560e585
- evidence/state-binding commit: faa00df9a4f5c7ae1350b0fc07e8deae215afdd6
- focused M4.3 result: 40 passed
- combined M4 result: 110 passed
- compatibility result: 220 passed
- canonical result: 727 passed, 3 skipped
- current HEAD after closeout: faa00df9a4f5c7ae1350b0fc07e8deae215afdd6
- schema version: 7
- files changed: src/project_memory/contracts.py,
  src/project_memory/projector.py, src/project_memory/__init__.py,
  tests/unit/test_m4_decision.py
- failed/no-op patches: none (3 test-logic bugs fixed during dev: supersession
  ordering, content-equal temporal compare, forbidden-token list)
- working-tree status: clean (after commit)

## Conclusion
M4.3: VERIFIED
M4 overall: IN PROGRESS
Schema version: 7
Next: M4.4 — Current Project State reducer
