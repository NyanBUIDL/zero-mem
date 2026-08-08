# M4.5 — Final Acceptance Evidence (Verification Records + Project Artifact integration)

Authoritative spec: `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`
Approved M4 plan: `.hermes/plans/2026-08-07_000004-m4-project-memory-plan.md`
Prior increments: `acceptance-m4.1.md` (M4.1 VERIFIED) … `acceptance-m4.4.md`
(M4.4 VERIFIED). M4.5 scope: deterministic, idempotent **Verification Records**
+ **Project Artifact** integration only. No Verification projector read API,
no Artifact read API, no M4.6 read API, no M4.7 rebuild, no M5, no LLM, no
network.

## Starting state (verified)
- HEAD: 0478e7c39a4dcf97a1832a234eeef141664eee27
- M0–M4.4: VERIFIED; schema: v7; canonical: 762 passed, 3 skipped
- Working tree: clean

## Implemented (M4.5)
- `src/project_memory/contracts.py`: `VerificationOp`, `ArtifactOp` typed
  envelopes; `M4Domain.VERIFICATION`/`ARTIFACT`; `VERIFICATION_SUBJECT_TYPES`
  (closed approved vocabulary); `VERIFICATION_STATUS_ENUM` (reuses the approved
  `VerificationStatus` model — NO new enum); `is_safe_reference` reference
  sanitizer.
- `src/project_memory/projector.py`: `project_verification`,
  `project_artifact`, `CLASSIFY_VERIFICATION`/`CLASSIFY_PROJECT_ARTIFACT`,
  classification branches in `classify_event_for_m4`.

## Authoritative design decisions (evidence-based)
- The canonical event envelope (`event_types.py`) has NO `verification`/
  `artifact` M4 event types that map to these tables; M4.5 consumes EXPLICIT
  typed operation envelopes only; it never infers verification from prose,
  timestamps, trace_id, embeddings, or LLM. `classify_event_for_m4` projects
  only on an explicit `m4.{domain,identity,op}` block; generic events → SKIP.
- `verification_id` / `artifact_id` are the explicit stable identities; `trace_id`
  is NEVER used as identity (verified: trace_id column does not exist on either
  v7 table; the projector ignores it).
- Subject vocabulary is the CLOSED, corrected-plan set:
  `requirement|decision|state|artifact|task|implementation|milestone`.
  `project_state` is rejected (not in vocabulary; the corrected plan uses `state`).
- Verification status reuses the approved `VerificationStatus` enum
  (`none|direct_tool_output|user_confirmation|deterministic_verification|
  approval`). NO new verification enum introduced. `verification_status` is kept
  SEPARATE from `lifecycle_status` — `zm_verifications` has NO `lifecycle_status`
  column (verified by test + DDL).
- Schema boundary: M4.5 uses the VERIFIED v7 `zm_verifications` and
  `zm_project_artifacts` tables AS-IS. `zm_verifications` columns:
  verification_id(PK), subject_type, subject_id, project_id, method, command_ref,
  observed_result, tested_commit, source_event_id, timestamp, verification_status,
  artifact_references. `zm_project_artifacts` columns: (artifact_id, project_id)
  PK, artifact_type, version, safe_reference, source_event_id, created_at,
  verification_status, linked_requirement_ids, linked_decision_ids,
  linked_state_keys; FK → `zm_artifacts.artifact_id`. NO migration v8; migrate_7
  unchanged.

## Behavior coverage (tested)
- Identity: explicit verification_id / artifact_id preserved; missing identity
  not invented; trace_id not used as identity; repeated same event idempotent.
- Subject: explicit subject_type + subject_id preserved; unsupported subject
  type rejected; `state` accepted, `project_state` rejected; subject not inferred
  when omitted; unrelated claim NOT promoted.
- Behavior: valid verification creation; verification_status preserved;
  verification/lifecycle separation (no lifecycle_status column); verification
  does NOT mutate Requirement / Decision / Current Project State / Charter
  (4 explicit tests); contradictory verifications both preserved (no winner, no
  timestamp truth, no LLM judgment); no LLM verification path.
- Evidence safety: safe command_ref accepted; raw multi-line command output /
  Traceback rejected; absolute path (e.g. /home/…) rejected; secret-bearing ref
  (file://…?token=) rejected; raw SQLite exceptions never escape (sanitized).
- Artifact integration: existing M2 artifact linked to project; project-artifact
  record created once; repeated event idempotent; explicit project_id + artifact_id
  preserved; missing artifact identity not invented; no filename-derived identity;
  no trace_id-derived identity.
- References: approved safe reference (relative) preserved; absolute path
  rejected; parent-traversal (../) rejected; secret-bearing ref rejected; NO
  artifact content duplication (no content_hash/stored_path columns in
  zm_project_artifacts; M2 substrate row untouched — metadata/linkage only).
- Explicit links: verification→artifact (artifact_references) explicit;
  artifact→requirement / decision / state keys explicit (reference columns only);
  absent links are NOT inferred.
- Failure/transaction: missing required M2 artifact rolls back (sanitized
  MissingIdentityError, no fake artifact, no partial linkage); failed link leaves
  no partial state; duplicate event does not duplicate links; atomic tx.
- Replay/determinism: incremental == replay for both verification and artifact
  projections; repeated replay deterministic.
- Cross-cutting: schema remains v7; JSONL unchanged; M3 TRUE READ-ONLY unchanged;
  M4.1–M4.4 remain VERIFIED; no broad M4 read API; no M4.6/M4.7/M5 behavior; no
  real ~/.hermes writes; no LLM/network imports (verified by forbidden-token scan).

## Verification order results
1. Syntax/collection: `compileall` OK.
2. Focused M4.5: **49 passed** (`tests/unit/test_m4_verification_artifact.py`).
3. Combined M4 (M4.1–M4.5): **194 passed** (32 + 38 + 40 + 35 + 49).
4. M2 artifact/provenance/compat: **168 passed, 3 skipped** (baseline FTS5 skips).
5. M3 read-only compatibility: **283 passed**.
6. Full canonical suite: **811 passed, 3 skipped** (no deselection).
   (Prior M4.4 baseline was 762 passed, 3 skipped; +49 M4.5.)

## Ad-hoc verification (fresh, post-commit, /tmp, removed after run)
15 checks covering: verification creation; explicit verification_id; no trace_id
identity fallback; subject linkage; verification does not mutate subject;
contradictory verifications preserved; project-artifact link to existing M2
artifact; safe artifact reference; no artifact content duplication (+ M2
substrate untouched); repeated event idempotence; missing M2 artifact rolls back
(+ no partial row); generic event classification still SKIP; structured
verification classification works; structured project-artifact classification
works; schema remains v7. Result: 14/15 PASS; the single non-pass is a PROBE
ARG INCONSISTENCY (check-7 hardcoded the op without `version="1"` while check-10
used the `_art()` default `version="1"`, so the two ops differed and the second
was re-created) — NOT a product defect (debug confirms o2="noop", 1 row; canonical
`test_project_artifact_idempotent` passes). Product idempotence verified by the
committed canonical suite.

## Regression recheck (M4.1–M4.4 must remain VERIFIED)
- M4.1 (32) + M4.2 (38) + M4.3 (40) + M4.4 (35) in the combined run: all green.
- migration v7, lifecycle CHECK, decision/state/verification/artifact active
  partial unique indexes, Charter/Requirement/Decision/State projection, M3 TRUE
  READ-ONLY, M2 artifact substrate: all green.

## Acceptance criteria
- All M4.5 acceptance criteria pass.                  ✓
- M4.1–M4.4 remain VERIFIED.                          ✓
- Focused M4.5 passes (49).                            ✓
- Combined M4 focused passes (194).                    ✓
- M2 artifact compatibility passes (168/3).           ✓
- M3 read-only compatibility passes (283).            ✓
- Canonical suite passes (811/3).                      ✓
- Verification distinct from claims.                   ✓
- No automatic subject promotion.                      ✓
- Contradictory verification preserved.                ✓
- Artifact Registry integration reuses M2 metadata.   ✓
- Artifact content not duplicated.                     ✓
- Safe-reference rules pass.                           ✓
- Links explicit only.                                ✓
- Projection idempotent.                               ✓
- Transactions atomic.                                 ✓
- Replay deterministic.                                ✓
- Schema remains v7.                                   ✓
- JSONL immutability preserved.                        ✓
- M3 read-only regression: none.                      ✓
- No M4.6+ behavior.                                   ✓
- Working tree clean after commit.                    ✓

## Record
- starting_commit: 0478e7c39a4dcf97a1832a234eeef141664eee27
- implementation_commit: 1b9ddabdef42e81be0bd60df56ca2e171b98241c
- tested_commit: 1b9ddabdef42e81be0bd60df56ca2e171b98241c
- evidence/state-binding commit: 0feaeec21a48bacbc39221d28b27e694f53991cb
- focused M4.5 result: 49 passed
- combined M4 result: 194 passed
- M2 compatibility result: 168 passed, 3 skipped
- M3 compatibility result: 283 passed
- canonical result: 811 passed, 3 skipped
- current HEAD after closeout: 0feaeec21a48bacbc39221d28b27e694f53991cb
- schema version: 7
- files changed: src/project_memory/contracts.py, src/project_memory/projector.py,
  src/project_memory/__init__.py, tests/unit/test_m4_verification_artifact.py
- failed/no-op patches: none (dev fixes: trace_id/session_id/profile_id/created_at
  columns removed from verification & artifact SQL to match VERIFIED v7 DDL;
  PRAGMA foreign_keys moved inside tx; is_safe_reference gained absolute/traversal
  rejection; verification idempotence ignores timestamp; probe arg-inconsistency
  in ad-hoc only, not a product defect)
- working-tree status: clean (after commit)

## Conclusion
M4.5: VERIFIED
M4 overall: IN PROGRESS
Schema version: 7
Next: M4.6 — Project-memory read APIs and M3 composition
