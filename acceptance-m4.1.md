# M4.1 — Final Acceptance Evidence (Project-memory contracts + schema/migration v7)

Authoritative spec: `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`
Approved M4 plan: `.hermes/plans/2026-08-07_000004-m4-project-memory-plan.md`
M4 plan correction commit: `6ee6510` (key semantics: no trace_id fallback; NULL-safe active uniqueness; lifecycle/domain-state separation)

## Verified starting state (Phase 1 reconciliation)

- HEAD at M4.1 start: `6ee6510` (latest M4 plan correction commit)
- M0: VERIFIED
- M1: VERIFIED
- M2: VERIFIED
- M3: VERIFIED (incl. M3.1–M3.6)
- M4: not started before this increment
- M5: not started
- Working tree clean before implementation
- Schema version: v6 → target v7

No repository-state conflict found. Proceeded to implement M4.1.

## Scope implemented (M4.1 only)

Deterministic project-memory contracts and SQLite schema foundation. No M4.2
projection logic, no M5 authorization/profile policy, no LLM, no network,
no real `~/.hermes` writes.

### Schema migration v7 (`src/storage/migrations/migrate_7.py`)

Six derived tables (disposable, rebuildable, non-canonical):

1. `zm_project_charters` — charter_id PK, project_id, version, name, goal,
   scope, non_goals, constraints, architecture_principles, success_criteria,
   lifecycle_status (CHECK §7.1), generic `state`, provenance, supersedes FK,
   verification reference, created_at/updated_at. Partial unique index
   `uq_zm_charters_active_version` on (project_id) WHERE lifecycle_status='active'.
2. `zm_requirements` — requirement_id PK, project_id, statement, lifecycle_status
   (CHECK), generic `state`, verification_status, supersedes/replaced_by self-FKs,
   linked Decision/Artifact/Verification id lists, provenance.
3. `zm_decisions` — decision_id PK, project_id, scope, decision_key (NULL-able),
   statement, rationale_ref, alternatives, lifecycle_status (CHECK), generic
   `state`, supersedes_id self-FK, replaced_by, effective_at, linked id lists,
   provenance. Partial unique index `uq_zm_decisions_active_key` on
   (project_id, scope, decision_key) WHERE lifecycle_status='active' AND
   decision_key IS NOT NULL.
4. `zm_project_state` — id PK, project_id, scope, state_key (NULL-able),
   state_value, state_ref, lifecycle_status (CHECK), verification_status,
   effective_at, supersedes self-FK, provenance. Partial unique index
   `uq_zm_project_state_active_key` on (project_id, scope, state_key) WHERE
   lifecycle_status='active' AND state_key IS NOT NULL.
5. `zm_verifications` — verification_id PK, subject_type, subject_id, project_id,
   method, command_ref, observed_result, tested_commit, source_event_id,
   timestamp, verification_status, artifact_references. Indexes on
   (project_id, subject_type, subject_id) and (subject_type, subject_id).
6. `zm_project_artifacts` — (artifact_id, project_id) PK, FK→`zm_artifacts`
   (reuses M2.4 metadata; no content duplication), artifact_type, version,
   safe_reference, source_event_id, created_at, verification_status,
   linked Requirement/Decision/State keys.

### Corrected key semantics (authoritative)

- `decision_key`: explicit stable key only. NO trace_id fallback, NO active_key
  fallback. Missing → NULL; record preserved; no domain uniqueness; supersession
  via explicit refs; missing-key surfaced in validation/audit (M4.2+).
- `state_key`: explicit stable key only. NO trace_id fallback. Missing → NULL;
  preserved; does not participate in logical active uniqueness when NULL.
- `lifecycle_status`: strictly the closed §7.1 enum
  (raw/observed/candidate/confirmed/active/superseded/conflicted/archived/deleted).
  Domain states (proposed/accepted/satisfied/blocked/rejected) live in a
  separate generic `state` column — never in lifecycle_status.
- Active uniqueness enforced only when the relevant key is non-NULL (partial
  unique index with `IS NOT NULL`). NULL-key rows never falsely collide.
- Supersession explicit only; a new trace_id implies nothing (not same logical
  decision, not same state slot, not supersession, not replacement).

### Migration framework

- `CURRENT_SCHEMA_VERSION = 7`; deterministic ascending ordering.
- `ensure_schema`: v6 → v7 upgrade (transaction-safe, no partial advance).
- `downgrade_to(6)`: removes only M4-derived schema; M0–M3 tables, JSONL,
  artifacts, prior migrations, M2/M3 state untouched.
- Idempotent reopen (no create if current == code).
- Unknown future version (db > code) → `SchemaVersionError`.
- Failed migration → sanitized `MigrationError`, rollback, version unchanged.
- `rebuild_from_jsonl`: extended `DERIVED_TABLES` to include the six M4 tables
  so rebuild drops and re-derives them alongside existing derived tables.

## Focused M4.1 test result

`tests/unit/test_m4_schema.py` — 32 passed.

Coverage:
- migration registry v7 (CURRENT_SCHEMA_VERSION==7; 7 in MIGRATIONS; ascending order)
- v6 → v7 upgrade; ledger rows 1..7; schema version == 7
- all six M4 tables exist
- expected indexes exist (uq partial indexes + idx)
- v7 reopen idempotent
- v7 → v6 downgrade (six M4 tables dropped; M2 tables retained)
- downgrade rejects unknown (target > current) and negative targets (sanitized errors)
- failed migration rolls back (no partial advance; v7 tables absent; version == 6)
- unknown future schema (db_8 > code_7) rejected
- lifecycle CHECK accepts enum; rejects domain states (proposed/accepted/...)
- generic domain `state` accepts proposed/accepted/satisfied/blocked/rejected
- explicit decision_key stored unchanged; missing → NULL; trace_id NOT used as key
- explicit state_key stored unchanged; missing → NULL; trace_id NOT used as key
- active-decision uniqueness: same non-NULL key rejected; different key allowed;
  multiple NULL-key active allowed; non-active historical rows allowed
- active-state uniqueness: same non-NULL key rejected; different allowed;
  multiple NULL-key active allowed
- explicit supersession FK behavior (valid ref allowed; missing ref allowed)
- verification schema (insert + fields)
- artifact linkage schema (FK → zm_artifacts, safe reference only)
- no M4.2 projection logic (migrate_7 contains no projector/reducer/promotion)
- no real `~/.hermes` writes (tmp_path only)
- no LLM dependency imported in migrate_7
- no network calls (socket guard absent)
- no M5 behavior (no authorization/profile policy in migrate_7)

## Compatibility (migration/compatibility battery)

- `tests/unit/test_m2_sqlite_foundation.py` — 25 passed
- `tests/unit/test_m2_indexes.py` — passed
- `tests/unit/test_m2_rebuild.py` — 22 passed (rebuild drops+re-derives M4 tables)
- Pre-existing tests asserting the old current version (==6) updated to ==7 where
  they checked the post-`ensure_schema` version; downgrade-target assertions
  (==5/==4/==2) left intact.

## Canonical suite

`.venv/bin/python -m pytest tests/ -q` → **649 passed, 3 skipped**.

No deselection. The 3 skipped are pre-existing capability skips (documented,
not M4.1-related). No environmental flake: the focused, compatibility, and
canonical runs are stable and reproducible in isolation and in combined order.

## Files changed

- `src/storage/migrations/migrate_7.py` (new) — schema migration v7
- `src/storage/migrations/__init__.py` — register migrate_7; CURRENT_SCHEMA_VERSION=7
- `src/storage/ingest.py` — DERIVED_TABLES extended with six M4 tables
- `tests/unit/test_m4_schema.py` (new) — 32 focused M4.1 tests
- `tests/unit/test_m2_integration.py` — v6→v7 version assertions
- `tests/unit/test_m2_tombstones.py` — v6→v7 version assertions
- `tests/unit/test_m3_query.py` — v6→v7 version assertions

## State bookkeeping

- `project-state.yaml`: next_incomplete_milestone M3 → M4; added m4_status/
  m4_increment_1_* fields. current_milestone M3 and m3_status verified retained.
- `implementation-plan.json`: M4 milestone updated to approved project-memory
  definition; added increment_1 (M4.1) verified block. next_incomplete_milestone
  already M4.

## Commit chain

- Starting commit: `6ee6510` (M4 plan correction; M4.1 start)
- M4 plan commits: `214954f` → `ce74a43` → `6ee6510`
- Implementation/tested commit: `b6eabe6ad5d02d00b55cfe65eabee4b201523434`
- Evidence/state-binding commit: <this evidence + state commit>
- Current HEAD after evidence: <hash>

## Acceptance gate

- migration v7 correct: YES
- focused tests pass: YES (32)
- migration compatibility passes: YES
- canonical suite passes: YES (649 passed, 3 skipped)
- all six required tables exist: YES
- lifecycle/domain-state separation correct: YES
- decision_key/state_key semantics correct: YES
- no trace_id fallback: YES (proven by direct regression tests)
- active uniqueness only for non-NULL keys: YES
- downgrade to v6 works: YES
- JSONL remains unchanged: YES (migration writes no JSONL; rebuild re-derives only)
- no M4.2 behavior: YES
- no M5 behavior: YES
- working tree clean after commit: YES

## Conclusion

M4.1: VERIFIED
M4 overall: IN PROGRESS (do not begin M4.2 without approval)
Schema version: 7
Next: M4.2 — Project Charter and Requirement Registry
