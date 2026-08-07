# M4 — Project State, Requirements, Decisions, Artifacts, and Verification Records

**Milestone:** M4 (deterministic project-memory layer)
**Depends on:** M0–M3 VERIFIED (HEAD `d8e18bd`, schema v6, canonical 617 passed / 3 skipped)
**Status:** PLANNING ONLY — no implementation, no tests, no state/plan mutation.
**Do not begin M5 or any later milestone.**

This plan was produced under the M4 planning protocol and updated (plan-correction commit) after
resolving the open planning decisions from **authoritative repository evidence**, including the
master specification (`Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`, extracted and read in full).

Only this plan artifact was created/updated. No source code, tests, `project-state.yaml`,
`implementation-plan.json`, or verified M0–M3 evidence were modified.

## Phase 1 — Reconciliation result (unchanged from initial plan)

| Check | Evidence | Verdict |
|-------|----------|---------|
| HEAD matches final M3 state | `d8e18bd` | ✅ |
| Working tree clean | `git status --short --branch` → `## master` | ✅ |
| M3 VERIFIED | `status: m3_verified` / `current_milestone_status: m3_verified` | ✅ |
| M3.1–M3.6 VERIFIED | increment_1..6 blocks `status: verified` | ✅ |
| Schema v6 | `CURRENT_SCHEMA_VERSION = max(MIGRATIONS)`; last `migrate_6.py` | ✅ |
| Canonical 617/3 | `.venv/bin/python -m pytest tests/ -q` | ✅ |
| M4/M5 not started | no m4/m5 status in state | ✅ |

No conflict → M4 planning proceeded; open decisions resolved below.

## Authoritative vocabulary (resolved from master spec)

Source: master specification §6–§9 (read in full from the `.docx`). The spec defines a **single
closed Lifecycle-state enum** shared by all memory objects, and a **minimum table schema** for
decisions/artifacts. It does **not** define closed enums for "requirement status" or "decision
status" as separate vocabularies; those reuse the lifecycle-state enum and/or a generic `state`
column. Requirements and Charter are mentioned only as Obsidian Project Home concepts (not as
canonical SQL tables in §9.2), so M4's Requirement Registry and Project Charter are deliberate
design extensions that use the authoritative lifecycle-state enum for their status.

### Lifecycle-state enum (§7.1, CLOSED — authoritative)

`raw → observed → candidate → confirmed → active → superseded → conflicted → archived → deleted`

This is the single status vocabulary for requirements, decisions, project-state, verifications,
and charters. (`deleted` is handled via tombstone/lifecycle per Decision B; it is excluded from
active queries.)

### Decision/state key mechanism (§7.2 + verified M2 `zm_lifecycle.active_key`)

Active-uniqueness rule (authoritative, §7.2): **at most one `active` value per
`entity + scope + state_key`** unless a state supports multiple values. The verified M2 codebase
already implements this for lifecycle state via `zm_lifecycle.active_key` (= canonical
`trace_id` for active events) with explicit supersession (`ingest.py:284-306`). M4 reuses this exact
mechanism for decision and project-state active-uniqueness — it does **not** invent a new key
scheme.

### Minimum table schema (§9.2, authoritative)

```
decisions(decision_id, scope, state, rationale_ref, supersedes_id)
tasks(task_id, project_id, status, current_step, updated_at)
artifacts(artifact_id, path, mime_type, hash, version)
```
Note: the spec's `decisions` table uses **`scope`** (not `decision_key`) and a generic **`state`**
column. M4's `zm_decisions` follows this; `scope` is the decision-domain key.

## Vocabulary reconciliation table

| Concept | Authoritative definition (master spec) | Proposed M4 definition | Result |
|---------|------------------------------------------|------------------------|--------|
| Requirement states | No closed enum in spec. Status reuses lifecycle-state enum (§7.1); requirements appear as Obsidian "active requirements" (§12.7) only. | `proposed/active/satisfied/blocked/rejected/superseded/archived` mapped onto lifecycle-state semantics; explicit promotion required. | CHANGE → spec has no closed enum; M4 uses lifecycle-state enum + explicit lifecycle transitions (see §2). |
| Decision states | No closed enum; `decisions(scope, state, ...)` (§9.2) with generic `state`. | `proposed/accepted/rejected/superseded/conflicted/archived` → reuse lifecycle enum (`candidate`≈proposed, `active`≈accepted, `superseded`, `conflicted`, `archived`, `raw`/`observed` as draft). | CHANGE → no closed decision enum; use lifecycle enum; `accepted`==`active`. |
| Verification states | `VerificationStatus` (§6.2 provenance envelope: `direct_tool_output`, `user_confirmation`, `deterministic_verification`; plus `none`/`approval` from verified M2 enum). | Same M2 enum. | MATCH |
| Charter lifecycle | No closed enum; charter is an Obsidian Project Home concept (§12.7). | Versioned rows; status from lifecycle enum; active version = `active`. | CHANGE → spec has no charter enum; use lifecycle enum + versioning. |
| Project-state semantics | §7.2: one active per `entity+scope+state_key`; `active` selected by lifecycle, not timestamp. | Same; `state_key` explicit or derived from `active_key`/`trace_id`. | MATCH |

**Conclusion:** The spec does **not** define closed requirement/decision/charter enums. M4 uses the
single authoritative lifecycle-state enum for all object `status`, plus the spec's `scope`/`state`
columns for decisions. No vocabulary is invented; the previously-proposed multi-word state lists
are reinterpreted as lifecycle-state transitions/aliases, not new enums.

## Requirement lifecycle (§2)

The spec provides no closed requirement-status enum. M4 models requirement `status` using the
authoritative lifecycle-state enum, with explicit promotion (no auto-promotion of suggestions):

| Proposed value | Classification vs spec | M4 mapping |
|----------------|------------------------|------------|
| proposed | implied but not enumerated | `candidate` (draft, not yet active) |
| active | implied but not enumerated | `active` (explicit promotion event/verification) |
| satisfied | implied but not enumerated | `confirmed` + verification link |
| blocked | implied but not enumerated | `observed`/`candidate` + note (no active promotion) |
| rejected | implied but not enumerated | `archived` (or tombstone) — never silently dropped |
| superseded | explicitly supported (§7.1, §7.2) | `superseded` + `supersedes` |
| archived | explicitly supported (§7.1) | `archived` |

An assistant suggestion is `candidate` only; it becomes `active` solely via an explicit event or
verification (per §6.3: "do not promote assistant_claim to active fact without tool observation,
user confirmation, or deterministic verification").

## Decision lifecycle (§3)

The spec provides no closed decision-status enum; `decisions` uses a generic `state` (§9.2). M4 maps
decision `state` onto the lifecycle enum:

| Proposed value | M4 lifecycle-state mapping |
|----------------|----------------------------|
| proposed | `candidate` |
| accepted | `active` |
| rejected | `archived` (preserved, not dropped) |
| superseded | `superseded` (+ `supersedes_id`) |
| conflicted | `conflicted` |
| archived | `archived` |

**What makes a decision currently effective:** a decision is effective when its `state` =
`active` **and** its `scope` (decision domain) is the currently-active one for that scope — i.e. it
is the row with `state='active'` for its `decision_key` (see §4), selected by explicit lifecycle
status, **not** by timestamp. If more than one row is `active` for the same `decision_key`, none is
unambiguously effective; both are preserved and the conflict is surfaced (§6).

## decision_key (§4) — RESOLVED

Resolution order (deterministic, rebuildable, no LLM, no semantic similarity, no free-form
normalization):
1. **Explicitly supplied canonical field** — if the decision event carries `scope` (per spec
   `decisions.scope`, §9.2) or `decision_key`, use it verbatim.
2. **Deterministically derived from approved structured canonical fields** — if no explicit
   `scope`/`decision_key`, derive `decision_key = active_key` (the verified M2 `zm_lifecycle.active_key`,
   which equals the canonical `trace_id` for active events). This is the same key M2 already uses
   for lifecycle active-uniqueness; it is stable across rebuilds.
3. **Otherwise no derived key** — if an active decision event carries neither `scope`/`decision_key`
   nor a usable `trace_id`/`active_key` (cannot happen for a well-formed `decision` event, since
   every event has `trace_id`), then the decision has no domain and MUST be supplied explicitly.

Canonical data **can** deterministically supply/derive it (`trace_id` is mandatory on every event,
per §4.3 and `ZM_META_COLUMNS`), so **no NEEDS DECISION stop is required**. Unrelated decisions have
distinct `trace_id` → no collision; the same logical decision domain reuses the same `trace_id` →
consistent resolution.

## state_key (§5) — RESOLVED

`state_key` is **explicitly supplied** when the canonical event carries one; otherwise it is
**deterministically derived** from the verified `active_key`/`trace_id` (same as decision_key). It
is NOT a hard-coded example list — the supported `state_key` values are whatever the canonical
events supply (e.g. `active_milestone`, `schema_version`, `implementation_commit`,
`verified_test_result`), validated only for non-emptiness and determinism.

**Active-uniqueness key (authoritative, §7.2):** `project_id + scope + state_key`.
- `scope` structure: a namespaced string; if not explicitly supplied, `scope` defaults to
  `project:<project_id>` (the approved scope dimension). **Missing scope is NOT invented** beyond
  this explicit default tied to the project_id that is always present on project-state events.
- Uniqueness enforced by a partial unique index on `(project_id, scope, state_key)` WHERE
  `state='active'`.

## Conflict semantics (§6) — aligned to spec §7.3

Authoritative behavior (§7.3): detect same entity + same attribute + overlapping validity with
incompatible values/states; **preserve all source traces**; rank by verification/source/temporal;
if unresolved → return `conflict_set`; **no silent overwrite**.

M4 conflict handling:
- **Duplicate active requirement identity** (`requirement_id` with two `active` rows): preserve both
  rows (each keeps its own `state`); record a `conflict_set` linking them; surface via
  `list_conflicts(project_id)`. Do **not** automatically mark both `conflicted` (spec does not
  mandate that); the conflict is surfaced, not auto-resolved.
- **Two `active` decisions for one `decision_key`**: same — both preserved, `conflict_set` surfaced;
  `get_active_decision(...)` returns a sanitized `conflict` error (not a silent winner).
- **Two `active` project-state values for one `state_key`**: same — both preserved, conflict
  surfaced; `get_current_project_state` excludes the conflicting pair from the clean "active" set
  and reports them under `conflicts`.
- **Contradictory verification records**: both retained with provenance; conflict surfaced.

No autonomous resolution; no winner chosen. This CHANGES the earlier draft which said "both flagged
`conflicted`" — the spec preserves and surfaces, it does not force a `conflicted` status on each.

## M4 architecture (unchanged from initial plan)

- Canonical JSONL (authoritative) → derived SQLite v7 (disposable, rebuildable) → TRUE READ-ONLY
  read path reusing M3 `open_readonly` + `query_only`.
- Deterministic, idempotent **projector** (single transaction, only writer) separates write/project
  path from retrieval. M3 retrieval guarantees unchanged.
- Zero LLM / zero network for routine ops. No LLM-context injection (M7). No M5 authorization.

## Models (resolved)

### Project Charter
Versioned rows; update appends `version+1` `active` row, prior → `superseded` (never deleted).
Status from lifecycle enum; active version = `state='active'`. `get_project_charter(project_id)`
returns the `active` row. Historical retrieval returns all versions.

### Requirement Registry
`requirement_id` (stable). `status` from lifecycle enum (§2 table). `proposed`≈`candidate` stays
un-promoted until explicit event/verification. Supersession explicit (`supersedes`/`replaced_by`).
`list_requirements`/`get_requirement` return non-deleted rows with provenance.

### Decision Log
`decision_id` (stable). `scope` (decision domain) + `state` (lifecycle enum). `accepted`==`active`.
Supersession explicit. Active-decision uniqueness via `(decision_key, state='active')` partial
unique index. Conflict → preserve + surface, not winner. `rationale_ref`/`alternatives` only when
explicitly supplied (references, not free text blobs).

### Current Project State
`state_key` (explicit or derived from `active_key`/`trace_id`) + `scope` (default `project:<id>`).
Active-uniqueness key `project_id + scope + state_key` (partial unique index WHERE `state='active'`).
Active selected by `state`, not timestamp. Update = new `active` row, prior → `superseded`.

### Verification Records
First-class; distinct from claims. Fields: `verification_id`, `subject_type`
(`requirement|decision|state|artifact|task|implementation|milestone`), `subject_id`, `project_id`,
`method`, `command`/`reference` (sanitized), `observed_result` (sanitized), `tested_commit`,
`source_event_id`, `timestamp`, `verification_status` (M2 enum), `artifact_references`. No secrets/
raw dumps/unrestricted paths. Does NOT auto-promote unrelated claims.

### Artifact integration
Reuses M2 `zm_artifacts` (metadata refs). New `zm_project_artifacts` for project-level linkage
(`artifact_id` FK → `zm_artifacts`, `project_id`, `safe_reference`, linked requirement/decision/
state keys). No content duplication; no arbitrary file reads; no unrestricted path exposure.

### Provenance
`source_event_id`, `trace_id`, `session_id`, `project_id`, `profile_id` (if supplied),
`created_at`, `verification_reference`, `supersession_reference`. Missing provenance not inferred.

## Rebuild behavior (unchanged)

`rebuild_project_memory(project_id)` reprojects all M4 derived tables deterministically from
canonical JSONL + M2 substrate. Same stream → same active charter/requirements/decisions/state/
artifacts/verifications/supersession/conflict. Incremental == rebuild. No competing canonical
project-state file.

## Schema impact — v7 review (§7)

All six tables are required (charter/requirement are M4 extensions; spec mentions them only as
Obsidian concepts but the M4 objective explicitly requires them). Each table aligns with spec §9.2
where applicable (`zm_decisions` uses `scope` + `state`, not `decision_key`/`status` split).

**zm_project_charters** — PK `charter_id`; `project_id`; `version` (int, monotonic); `lifecycle_status`
(lifecycle enum); `supersedes` (self-FK); provenance (`source_event_id`, `trace_id`, `session_id`,
`profile_id`, `created_at`); UNIQUE `(project_id)` WHERE `lifecycle_status='active'`; index
`project_id`; FKs none beyond self; downgrade drops table → v6.

**zm_requirements** — PK `requirement_id`; `project_id`; `status` (lifecycle enum); `verification_status`
(M2 enum); `supersedes`/`replaced_by` (self-FK); `linked_decision_ids`, `linked_artifact_ids`,
`linked_verification_ids` (text/JSON, references only); provenance fields; index `project_id`;
downgrade drops table.

**zm_decisions** — PK `decision_id`; `project_id`; **`scope`** (decision domain, per §9.2); `state`
(lifecycle enum; `active`==accepted); `rationale_ref`, `alternatives` (references, nullable);
`supersedes_id` (self-FK); `effective_at`; linked requirement/artifact/verification ids; provenance;
**partial UNIQUE `(decision_key, state)` WHERE `state='active'`** with `decision_key` derived per §4
(stored column = explicit `scope` or `active_key`/`trace_id`); index `project_id`, `scope`;
downgrade drops table.

**zm_project_state** — PK `id` (autoincrement) or `(project_id, scope, state_key, version)`;
`project_id`; **`scope`** (default `project:<project_id>`); **`state_key`** (explicit or derived);
`state_value`/`reference` (sanitized); `lifecycle_status` (lifecycle enum); `verification_status`;
`effective_at`; `supersedes`; provenance; **partial UNIQUE `(project_id, scope, state_key)` WHERE
`lifecycle_status='active'`** (authoritative §7.2); index `project_id`, `state_key`; downgrade drops
table.

**zm_verifications** — PK `verification_id`; `subject_type`; `subject_id`; `project_id`; `method`;
`sanitized_command_ref`; `observed_result` (sanitized); `tested_commit`; `source_event_id`;
`timestamp`; `verification_status`; `artifact_references`; provenance; index `subject_id`,
`project_id`; downgrade drops table. No secret/raw-output columns.

**zm_project_artifacts** — PK `(artifact_id, project_id)`; FK → `zm_artifacts.artifact_id`; `project_id`;
`artifact_type`; `version`; `safe_reference`; `source_event_id`; `created_at`; `verification_status`;
`linked_requirement_ids`, `linked_decision_ids`, `linked_state_keys` (references); index
`project_id`; downgrade drops table.

**Migration 7:** `migrate_7.py` with `up` (create the six tables + indexes + partial unique indexes)
and `down` (drop all six → v6). `CURRENT_SCHEMA_VERSION` becomes 7. Idempotent projector uses stable
identities + dedup keys (no duplicate rows on reprocess).

## Idempotence & transaction safety (unchanged)

Stable identities + dedup keys ⇒ reprocessing same canonical event never duplicates. Projector
writes in one transaction: state + supersession + verification + artifact links commit together or
roll back together.

## Deletion behavior (preserve Decision B)

Canonical JSONL append-only; no physical purge. Logical deletion marks derived row
`lifecycle_status='deleted'` (reusing M2 convention + tombstone), preserving provenance, excluded
from active queries, rebuildable deterministically.

## Secret safety / Profile boundary / Performance (unchanged)

Synthetic-secret scans over all M4 surfaces; no raw exception strings. M4 stores `profile_id`/
`project` mappings (provenance) only — no M5 access policy. Performance: measure first; baseline p95
(current-state <20ms, requirements <20ms, active-decision <20ms, verification <20ms, rebuild(200)<2s);
no invented SLA.

## Proposed M4 increments (unchanged structure)

M4.1 contracts + schema/migration v7 · M4.2 Charter+Requirements · M4.3 Decision Log+supersession/
conflict · M4.4 Current-State reducer · M4.5 Verification+Artifact integration · M4.6 Read APIs + M3
composition · M4.7 Rebuild/performance/final acceptance. Each: objective/files/schema/tests/
acceptance/rollback/deps/exclusions.

## Acceptance matrix (unchanged — all criteria mapped to planned tests)

(Charter create/version/supersede; requirement create/transition/supersede; decision
create/accepted/rejected/supersede/conflict/active-uniqueness; state create/update/supersede/
active-uniqueness; verification create/link/no-auto-promote; artifact link; provenance; idempotence;
incremental==rebuild; rebuild determinism; rollback; deleted-handling; secret-absence; M3 unchanged;
no real ~/.hermes; no LLM/network; no M5 behavior.) Final acceptance: `.venv/bin/python -m pytest
tests/ -q`; count must not decrease without justified removal.

## State bookkeeping mismatch (§8) — recorded correction

`project-state.yaml` line 305 reads `next_incomplete_milestone: M3` while `implementation-plan.json`
reads `next_incomplete_milestone: M4`. Pre-existing from the M3.6 baseline-guard sync; neither file
is changed now (per instructions).

**Exact correction required when M4.1 becomes VERIFIED:** set `project-state.yaml` line 305
`next_incomplete_milestone: M3` → `next_incomplete_milestone: M4`. (`current_milestone: M3` stays
correct — M3 is the latest verified milestone; `m3_status: verified` stays. Only the
`next_incomplete_milestone` pointer is wrong.) No change to `implementation-plan.json` is needed at
that point (it already reads M4).

## Unresolved decisions — RESOLVED

1. **Master-spec vocabulary** — RESOLVED. Read the `.docx` in full. Requirement/decision/charter
   statuses are NOT closed enums in the spec; all use the authoritative lifecycle-state enum
   (§7.1). Decision/state tables follow §9.2 (`decisions(scope, state, ...)`). No vocabulary invented.
2. **decision_key** — RESOLVED (§4). Explicit `scope`/`decision_key` → else derived from verified
   `active_key`/`trace_id`. Canonical data supplies it deterministically; no NEEDS DECISION stop.
3. **state_key** — RESOLVED (§5). Explicit `state_key` → else derived from `active_key`/`trace_id`;
   `scope` defaults to `project:<project_id>`, not invented. Active-uniqueness key
   `project_id + scope + state_key` (§7.2).
4. **Conflict semantics** — RESOLVED (§6). Preserve all sources, surface `conflict_set`; do NOT
   force both `conflicted` (aligns with §7.3).
5. **State bookkeeping mismatch** — recorded (§8); corrected when M4.1 VERIFIED.

## Deliverable status

- Created/updated: this M4 plan artifact only.
- Modified: nothing else (no source, tests, state, plan, or M0–M3 evidence).

M4 PLAN: READY FOR IMPLEMENTATION
Vocabulary: CONFIRMED
decision_key: RESOLVED
state_key: RESOLVED
Schema target: v7
Working tree: clean
