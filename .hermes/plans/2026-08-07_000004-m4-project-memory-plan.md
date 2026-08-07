# M4 — Project State, Requirements, Decisions, Artifacts, and Verification Records

**Milestone:** M4 (deterministic project-memory layer)
**Depends on:** M0–M3 VERIFIED (HEAD `d8e18bd`, schema v6, canonical 617 passed / 3 skipped)
**Status:** PLANNING ONLY — no implementation, no tests, no state/plan mutation.
**Do not begin M5 or any later milestone.**

This plan was produced under the M4 planning protocol. It creates **only** this plan artifact.
No source code, tests, `project-state.yaml`, `implementation-plan.json`, or verified M0–M3 evidence
were modified.

## Phase 1 — Reconciliation result

| Check | Evidence | Verdict |
|-------|----------|---------|
| HEAD matches final M3 state | `d8e18bd` (`git rev-parse HEAD`) | ✅ |
| Working tree clean | `git status --short --branch` → `## master` (no changes) | ✅ |
| M3 VERIFIED | `project-state.yaml`: `status: m3_verified`, `m3_status: verified`; `implementation-plan.json`: `current_milestone_status: m3_verified`; `current_milestone: M3` | ✅ |
| M3.1–M3.6 VERIFIED | increment_1..6 blocks all `status: verified` in `project-state.yaml` | ✅ |
| Schema remains v6 | `CURRENT_SCHEMA_VERSION = max(MIGRATIONS)`; last migration `migrate_6.py` (v6) | ✅ |
| Canonical suite 617 passed / 3 skipped | `.venv/bin/python -m pytest tests/ -q` (this session) | ✅ |
| M4 not started | no `m4_status` / `m4_increment*` in `project-state.yaml` | ✅ |
| M5 not started | no `m5_status` / `m5_increment*` in `project-state.yaml` | ✅ |

**Note (non-blocking):** `project-state.yaml` line 305 still reads `next_incomplete_milestone: M3`
while `implementation-plan.json` reads `next_incomplete_milestone: M4`. This is a pre-existing
cross-file inconsistency from the M3.6 baseline-guard sync and does not affect M4 planning. It will
be corrected when M4 state is first written (implementation phase, not planning).

No conflict → continue to M4 planning.

## M4 architecture

**Layering (consistent with AGENTS.md / M2 substrate):**

1. **Canonical source (authoritative, append-only):** JSONL event stream. M4 derives all project
   memory from canonical events + explicitly recorded project artifacts. No new canonical source is
   introduced.
2. **Derived SQLite (disposable, rebuildable, non-canonical):** new M4 projection tables (v7). These
   mirror the M2 pattern: derived → disposable → rebuildable. They are projected, never the source of
   truth.
3. **Read path (TRUE READ-ONLY, reuses M3):** M4 read APIs query the derived tables through the same
   `mode=ro` + `PRAGMA query_only=ON` connection M3 uses (`src/retrieval/db.py`). M3 retrieval
   guarantees are unchanged.
4. **Write/projector boundary:** a deterministic projector consumes canonical events and writes the
   derived M4 tables inside a single transaction. Retrieval calls never mutate M4 state. The projector
   is the only writer; it is not M3.

**Reused verified substrate:**
- `zm_artifacts` (M2.4) → M4 artifact registry base (metadata references only; no content duplication).
- `zm_meta` / `zm_provenance` / `zm_lifecycle` / `zm_tombstones` / `zm_deletion_audit` (M2) → provenance
  and deleted-state patterns reused.
- M3 `open_readonly` + `query_only` + `cursor` fingerprint + sanitized `QueryError` contract → M4 read
  APIs compose with / reuse M3 infrastructure.
- M2 migration registry (`MIGRATIONS` dict + `up`/`down` + `CURRENT_SCHEMA_VERSION`) → migration 7.

**No LLM / no network:** routine M4 operations (project, projector, read) make zero LLM and zero
network calls. Project memory is not injected into LLM context in M4 (M7 concern).

**project-state.yaml vs M4 runtime state (explicit distinction):**
- `project-state.yaml` remains a **development/control-plane evidence + workflow file** (per AGENTS.md
  delivery protocol and the M3 baseline guard that keys off `status: m3_verified`). It records
  milestone verification, increment commits, and acceptance evidence pointers. It is NOT the runtime
  canonical memory database.
- M4 runtime project memory lives in the **external memory substrate** (canonical JSONL + derived
  SQLite v7 tables), rebuilt deterministically. M4 must NOT silently promote `project-state.yaml`
  into the runtime canonical project-state DB.

## Project Charter model

Structured, versioned charter per project.

**Fields (only those supportable from existing structures; no invented content):**
- `charter_id` (stable identity, e.g. `charter:<project_id>` or explicit id)
- `project_id`
- `name`
- `goal`
- `scope`
- `non_goals`
- `constraints`
- `architecture_principles`
- `success_criteria`
- `created_at`, `updated_at`
- `source_event_id` (canonical event that created/updated the charter)
- `verification_status` (reuse M2 enum: `none/direct_tool_output/user_confirmation/deterministic_verification/approval`)
- `version` (monotonic integer; active version selected by `lifecycle_status='active'`)

**Behavior:**
- *Creation:* projector derives a charter row from an explicit `charter` event (canonical). No
  silent creation from assistant text.
- *Update / versioning:* a new charter row is appended with `version+1` and `lifecycle_status='active'`;
  the prior version is flipped to `lifecycle_status='superseded'` (never deleted). Update never
  destroys the previous version.
- *Supersession:* explicit `supersedes = <prior_charter_id>` on the new row; prior row marked
  `superseded`. `newer timestamp = supersedes` is NOT assumed unless the spec explicitly states it.
- *Active version selection:* exactly one row per `project_id` with `lifecycle_status='active'`
  (uniqueness constraint). `get_project_charter(project_id)` returns the active row.
- *Historical retrieval:* `list_charter_versions(project_id)` returns all versions ordered by
  `version`, including superseded/archived.
- *Rebuild:* charter state is fully reproducible from canonical events; rebuild reproduces the same
  active + historical set.

## Requirement Registry model

Deterministic requirement registry with explicit identity and lifecycle.

**Fields:**
- `requirement_id` (stable identity)
- `project_id`
- `statement` / `reference` (text or pointer; sanitized)
- `source_event_id`
- `created_at`
- `status` (requirement lifecycle — see states below)
- `verification_status` (M2 enum)
- `supersedes` / `replaced_by`
- `linked_decision_ids`
- `linked_artifact_ids`
- `linked_verification_ids`

**Requirement lifecycle (states actually supportable; confirm against master `.docx` in M4.1):**
`proposed → active → satisfied | blocked | rejected | superseded | archived`.
- An assistant *suggestion* is NOT an accepted requirement unless an explicit event or verification
  establishes `active` (or later) state. Unverified suggestion stays `proposed` (or is not projected).
- Status transitions are explicit events; no automatic promotion.
- Supersession: explicit `supersedes` / `replaced_by`; prior row marked `superseded`, never deleted.
- `list_requirements(project_id)` returns non-deleted rows; `get_requirement(requirement_id)`
  returns the row with provenance.

## Decision Log model

Append-only, versioned decision log.

**Fields:**
- `decision_id`
- `project_id`
- `statement` / `reference`
- `rationale` / `reference` (only when explicitly supplied)
- `alternatives` (only when explicitly supplied)
- `source_event_id`
- `verification` (verification_status enum)
- `effective_at`
- `supersedes` / `replaced_by`
- `linked_requirement_ids`
- `linked_artifact_ids`
- `linked_verification_ids`

**Decision states (only approved):** `proposed`, `accepted` (active), `rejected`, `superseded`,
`conflicted`, `archived`.
- *Never silently overwrite a prior decision.* If Decision B replaces Decision A: A stays historical
  (`superseded`), B becomes `accepted`/`active`, and the supersession relation (`supersedes`) is
  explicit.
- *Active decision uniqueness:* at most one `accepted` decision per approved
  `project_id + decision_key` (e.g. decision_key derived from the decision's subject/type). If two
  both claim active for the same key → both retained, both flagged `conflicted`; no winner chosen
  (conflict surfaced, not auto-resolved).
- `get_active_decision(project_id, decision_key)` returns the `accepted` row, or raises a sanitized
  `conflict` error if more than one `accepted` exists.

## Current Project State model

Derived "current valid state" for approved state keys.

**Fields:**
- `state_key` (approved key; e.g. `active_milestone`, `active_increment`, `schema_version`,
  `verified_test_result`, `implementation_commit`, `task_status`, `last_verified_checkpoint` — only
  those the spec defines)
- `project_id`
- `state_value` / `reference` (sanitized)
- `source_event_id`
- `lifecycle_status`
- `verification_status`
- `effective_at`
- `supersedes`
- `provenance` (source_event_id + verification reference)

**Rules:**
- At most one `active` value per (`project_id`, `scope`, `state_key`) unless the spec explicitly
  permits multiple. Enforced by a UNIQUE index on (`project_id`, `state_key`, `scope`) WHERE
  `lifecycle_status='active'`.
- "latest timestamp wins" is NOT used as truth. Active state is selected by explicit
  `lifecycle_status='active'` + provenance, not by recency.
- Update = new row `active`, prior flipped `superseded`.
- `get_current_project_state(project_id)` returns all `active` rows.

## Verification Records model

First-class verification records, distinct from assistant claims.

**Fields:**
- `verification_id`
- `subject_type` (one of: `requirement`, `decision`, `state`, `artifact`, `task`, `implementation`,
  `milestone` — only if supported by spec)
- `subject_id`
- `project_id`
- `method` (e.g. `pytest`, `deterministic_check`, `user_confirmation`)
- `command` / `reference` (sanitized; no raw output)
- `observed_result` (sanitized summary; e.g. `617 passed, 3 skipped`)
- `tested_commit` (where applicable)
- `source_event_id`
- `timestamp`
- `verification_status` (M2 enum)
- `artifact_references` (safe references only)

**Prohibited content:** secrets, unrestricted command output containing secrets, raw exception
dumps, uncontrolled filesystem paths. References must be sanitized (commit hash, relative artifact
id, counts).
- `list_verifications(subject_id)` returns verifications linked to a subject.
- A verification record does NOT automatically promote an unrelated assistant claim to verified
  state; it is linked evidence only.

## Artifact integration model

Reuses verified M2 `zm_artifacts` (metadata references; no content). M4 adds project-level linkage.

**M4 artifact linking fields (new derived table `zm_project_artifacts`):**
- `artifact_id` (FK → `zm_artifacts.artifact_id`)
- `project_id`
- `artifact_type`
- `version`
- `safe_reference` (no unrestricted filesystem path exposed)
- `source_event_id`
- `created_at`
- `verification_status`
- `linked_requirement_ids`
- `linked_decision_ids`
- `linked_state_keys`

**Rules:** do not automatically open/read arbitrary files; do not expose unrestricted filesystem
paths; do not duplicate artifact content into SQLite (metadata + safe reference only).
`list_project_artifacts(project_id)` returns linked artifacts with sanitized references.

## Provenance model

Every M4 object is traceable to canonical evidence. Provenance fields (minimum):
- `source_event_id`
- `trace_id`
- `session_id`
- `project_id`
- `profile_id` (only when explicitly supplied)
- `created_at`
- `verification_reference` (link to `zm_verifications` / `zm_provenance`)
- `supersession_reference` (prior id when superseded)

Missing provenance is NOT inferred. Every `active`/`accepted` row must carry a `source_event_id`.

## Conflict & supersession rules

- **Conflict (no auto-resolution):** when two events claim incompatible state for the same identity
  key (requirement status, active decision, current-state value, verification disagreement), both
  sources are preserved; the affected rows are marked `conflicted` (or both retained historical) and
  the conflict is surfaced via a sanitized query result / `conflict` error. If the spec defines a
  resolution policy, follow it; otherwise surface, never choose a winner.
- **Supersession (explicit only):** `supersedes`/`replaced_by` are set explicitly on the new row;
  the prior row is flipped to `superseded` (never physically deleted). `newer timestamp = supersedes`
  is NOT assumed unless the master spec explicitly states so.
- Applies uniformly to charters, requirements, decisions, project-state values, artifacts (when
  versioned), and verification records (where applicable).

## Rebuild behavior

- `rebuild_project_memory(project_id)` (or equivalent internal projector) reprojects all M4 derived
  tables deterministically from canonical JSONL + M2 artifact substrate.
- Same canonical stream → same active charter, requirement states, active decisions, current state,
  artifact registry, verification records, supersession, and conflict state.
- Incremental projection MUST equal rebuild projection (idempotent; stable identities + dedup keys).
- No competing canonical project-state file is created that cannot be rebuilt. Canonical JSONL
  remains the only canonical source.

## Schema impact (expected)

**New migration required → version 7.** Rationale: no existing v6 table represents charters,
requirements, decisions, current-state, or verifications; `zm_artifacts` covers artifact *metadata*
but not project-level linkage. New tables are derived, disposable, rebuildable (consistent with M2).

**Proposed tables (each justified, with constraints/indexes/FKs/up/down/rebuild):**

1. `zm_project_charters` — charter versions (PK `charter_id`; UNIQUE `(project_id)` WHERE
   `lifecycle_status='active'`).
2. `zm_requirements` — requirement registry (PK `requirement_id`; index `project_id`;
   `supersedes`/`replaced_by` self-FK).
3. `zm_decisions` — decision log (PK `decision_id`; UNIQUE `(project_id, decision_key)` WHERE
   `lifecycle_status='accepted'`; `supersedes` self-FK).
4. `zm_project_state` — current state (PK `id`; UNIQUE `(project_id, state_key, scope)` WHERE
   `lifecycle_status='active'`).
5. `zm_verifications` — verification records (PK `verification_id`; index `subject_id`).
6. `zm_project_artifacts` — project artifact linkage (PK `(artifact_id, project_id)`; FK →
   `zm_artifacts.artifact_id`).

All carry `source_event_id`, `lifecycle_status`, `verification_status`, `created_at`, provenance.
Each migration has `up`/`down`; `down` drops the table (returns to v6). Rebuild re-derives from
canonical events. No schema duplication with M2 tables.

*(Final exact column set, indexes, and FKs to be locked in M4.1 after master-spec vocabulary
confirmation.)*

## Idempotence & transaction safety

- Stable identities (`charter_id`, `requirement_id`, `decision_id`, `verification_id`,
  `(artifact_id, project_id)`) + dedup keys ⇒ reprocessing the same canonical event never creates
  duplicate rows.
- Projector writes inside one transaction: state + supersession + verification + artifact links
  commit together or roll back together. No partially updated project-memory state.

## Deletion behavior (preserve Decision B)

- Canonical JSONL stays append-only; no physical purge.
- Logical deletion of a project-memory subject marks the derived row `lifecycle_status='deleted'`
  (reusing the M2 `deleted` convention + tombstone pattern), preserving historical provenance and
  excluded from active queries. Rebuild reproduces deleted state deterministically.

## Secret safety

Synthetic-secret scans must prove absence in: charter data, requirement registry, decision log,
project-state values, verification records, artifact metadata, diagnostics, errors, and acceptance
artifacts. No raw exception strings; sanitized references only.

## Profile boundary (M4 scope edge)

M4 MAY store explicitly supplied `profile_id`/`project` mappings (provenance). M4 does NOT implement
M5 access policy: no read/write authorization, cross-profile policy, inheritance, or isolation-mode
enforcement. M5 owns those.

## Performance acceptance (measure first; no invented SLA)

Synthetic corpus (temp dir, isolated store): ~200 requirements/decisions/state-keys across projects.
Baseline p95 targets (no hard SLA yet):
- current project-state lookup < 20 ms
- requirements listing < 20 ms
- active decision lookup < 20 ms
- verification lookup < 20 ms
- project rebuild (200 subjects) < 2 s
No premature cache. If a filter lacks an index, that becomes a justified M4 index addition, not an
M2/M3 change.

## Proposed M4 increments

M4.1 — Project-memory contracts + schema/migration (v7): data models, enum vocabularies (confirmed
       vs master `.docx`), `migrate_7.py`, projector skeleton, idempotent projector tests, read-only
       open over v7, no mutation of M3.
M4.2 — Project Charter + Requirement Registry: creation/versioning/supersession; `get_project_charter`,
       `list_requirements`, `get_requirement`; active-uniqueness; claim-not-fact.
M4.3 — Decision Log + supersession/conflict: `list_decisions`, `get_active_decision`; accepted/rejected/
       superseded/conflicted; active-decision uniqueness; conflict surfacing.
M4.4 — Current Project State reducer: deterministic reduction; `get_current_project_state`; active
       uniqueness; no "latest-timestamp-wins".
M4.5 — Verification Records + Artifact Registry integration: `list_verifications`, `list_project_artifacts`;
       verification↔subject linkage; reuse `zm_artifacts`; safe references; no secret leakage.
M4.6 — Read APIs and M3 composition: expose read APIs over M4 tables via M3 TRUE READ-ONLY
       infrastructure; ensure M3 retrieval guarantees unchanged; no retrieval mutation of M4 state.
M4.7 — Rebuild, performance, and final integration acceptance: `rebuild_project_memory`; incremental==
       rebuild parity; repeated-rebuild determinism; transaction rollback; deleted-state handling;
       secret absence; no real `~/.hermes` writes; no LLM/network; no M5 behavior; full canonical suite
       green (count must not decrease without justified removal).

For every increment: objective, files, schema changes, projection behavior, tests, acceptance
criteria, rollback (`down` migration), dependencies (prior M4 increments), explicit exclusions.

## Acceptance matrix (criterion → test, planned)

| Criterion | Planned test |
|-----------|--------------|
| charter creation/versioning | test_m4_charter::test_charter_create_version |
| charter supersession | test_m4_charter::test_charter_supersede_keeps_history |
| requirement creation | test_m4_requirement::test_requirement_create |
| requirement status change | test_m4_requirement::test_requirement_status_transition |
| requirement supersession | test_m4_requirement::test_requirement_supersede |
| decision creation | test_m4_decision::test_decision_create |
| accepted decision | test_m4_decision::test_decision_accepted_active |
| rejected decision | test_m4_decision::test_decision_rejected |
| superseded decision | test_m4_decision::test_decision_supersede |
| decision conflict | test_m4_decision::test_decision_conflict_no_winner |
| active decision uniqueness | test_m4_decision::test_active_decision_unique |
| current-state creation | test_m4_state::test_state_create |
| state update | test_m4_state::test_state_update_supersedes_prior |
| state supersession | test_m4_state::test_state_supersede |
| active state uniqueness | test_m4_state::test_active_state_unique |
| verification creation | test_m4_verification::test_verification_create |
| verification linked to subject | test_m4_verification::test_verification_links_subject |
| verification does not promote claims | test_m4_verification::test_verification_no_auto_promote |
| artifact linkage | test_m4_artifact::test_artifact_link |
| provenance preservation | test_m4_*:test_provenance_present |
| duplicate-event idempotence | test_m4_projector::test_idempotent_reprocess |
| incremental/rebuild parity | test_m4_rebuild::test_incremental_eq_rebuild |
| repeated rebuild determinism | test_m4_rebuild::test_rebuild_deterministic |
| transaction rollback | test_m4_projector::test_rollback_consistent |
| deleted-state handling | test_m4_*:test_deleted_excluded |
| secret absence | test_m4_*:test_secret_absent |
| M3 read-only unchanged | test_m4_readonly::test_m3_unchanged |
| no real ~/.hermes writes | test_m4_isolation::test_no_real_hermes_home |
| no LLM/network | test_m4_*:test_no_llm_network |
| no M5 behavior | test_m4_*:test_no_m5_policy |

Final M4 acceptance runs `.venv/bin/python -m pytest tests/ -q`; canonical count must not decrease
without explicitly justified test removal.

## Explicit exclusions (M4)

Excluded unless the master spec explicitly assigns them to M4: profile authorization; cross-profile
permission policy; isolated-mode enforcement; M5 behavior; automatic LLM memory selection; prompt/
context injection; LLM summarization; semantic/vector search; autonomous conflict resolution;
autonomous requirement creation; autonomous decision creation; Obsidian sync; MCP integration;
background scheduler; physical JSONL deletion; M5+ implementation.

## Unresolved decisions

1. **Master-spec vocabulary confirmation (recommended before M4.1):** the authoritative master
   specification is a binary `.docx` (`Tai_lieu_thong_nhat_...docx`) that could not be read as text
   in this planning session. The requirement-lifecycle and decision-state vocabularies proposed here
   (`proposed/active/satisfied/blocked/rejected/superseded/archived` for requirements;
   `proposed/accepted/rejected/superseded/conflicted/archived` for decisions) are grounded in the
   verified M2 lifecycle/verification enums and IDEA.md pain points, but the **exact** allowed values
   and any `state_key` list for Current Project State must be confirmed against the master `.docx`
   during M4.1. This is a documentation-confirmation step, not a design blocker — models are defined
   to accept the confirmed vocabulary without structural change.
2. **`decision_key` derivation:** the exact key used for active-decision uniqueness
   (`project_id + decision_key`) needs the spec's decision taxonomy. Proposed default: derive
   `decision_key` from the decision's subject/type supplied in the canonical event; confirm in M4.1.
3. **Cross-file `next_incomplete_milestone` inconsistency** (`project-state.yaml` says M3,
   `implementation-plan.json` says M4) — pre-existing from M3.6; will be corrected when M4 state is
   first written (implementation phase), not in planning.

## Deliverable status

- Created: this M4 plan artifact only (`.hermes/plans/...`).
- Modified: nothing else (no source, tests, state, plan, or M0–M3 evidence).

M4 PLAN: READY FOR APPROVAL
Working tree change: M4 plan file only
