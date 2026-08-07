# M4 — Project State, Requirements, Decisions, Artifacts, and Verification Records

**Milestone:** M4 (deterministic project-memory layer)
**Depends on:** M0–M3 VERIFIED (HEAD `d8e18bd`, schema v6, canonical 617 passed / 3 skipped)
**Status:** PLANNING ONLY — no implementation, no tests, no state/plan mutation.
**Do not begin M5 or any later milestone.**

Produced under the M4 planning protocol; updated via two plan-correction commits after resolving the
open planning decisions (vocabulary, decision_key, state_key) and then correcting the key semantics
(trace_id is NOT a stable logical key; lifecycle_status vs domain `state` distinction).

Only this plan artifact was created/updated. No source code, tests, `project-state.yaml`,
`implementation-plan.json`, or verified M0–M3 evidence were modified.

## Phase 1 — Reconciliation result (unchanged)

| Check | Evidence | Verdict |
|-------|----------|---------|
| HEAD matches final M3 state | `d8e18bd` | ✅ |
| Working tree clean | `git status --short --branch` → `## master` | ✅ |
| M3 VERIFIED | `status: m3_verified` / `current_milestone_status: m3_verified` | ✅ |
| M3.1–M3.6 VERIFIED | increment_1..6 blocks `status: verified` | ✅ |
| Schema v6 | `CURRENT_SCHEMA_VERSION = max(MIGRATIONS)`; last `migrate_6.py` | ✅ |
| Canonical 617/3 | `.venv/bin/python -m pytest tests/ -q` | ✅ |
| M4/M5 not started | no m4/m5 status in state | ✅ |

No conflict → M4 planning proceeded.

## Authoritative vocabulary (from master spec, read in full from the `.docx`)

### Lifecycle-state enum (§7.1, CLOSED — authoritative, enforced in `lifecycle_status`)

`raw → observed → candidate → confirmed → active → superseded → conflicted → archived → deleted`

**Only these nine values may enter `lifecycle_status`.** This is the single status vocabulary for the
*memory-substrate lifecycle* of every M4 record (charter, requirement, decision, project-state,
verification, artifact link). (`deleted` is handled via tombstone/lifecycle per Decision B; excluded
from active queries.)

### Domain `state` (generic, per spec §9.2)

The spec's `decisions(decision_id, scope, state, rationale_ref, supersedes_id)` includes a generic
**`state`** column that is NOT the lifecycle enum. Requirement/decision domain statuses
(`proposed`, `accepted`, `satisfied`, `blocked`, `rejected`, `superseded`, `conflicted`, `archived`)
are represented in this separate generic `state` column — **never** in `lifecycle_status`. No new
closed domain enum is manufactured; `state` is a documented, free-but-sanitized TEXT column whose
allowed values are taken from the spec/plan, not enforced as a CHECK.

### Decision/state key mechanism (§7.2 + verified M2 `zm_lifecycle.active_key`)

Active-uniqueness rule (authoritative, §7.2): **at most one `active` value per
`entity + scope + state_key`** unless a state supports multiple values. The verified M2 codebase
implements this for *canonical lifecycle state* via `zm_lifecycle.active_key` (= canonical `trace_id`
for active events) with explicit supersession (`ingest.py:284-306`). M4 reuses the same *rule* for
decision/project-state active-uniqueness but, per the correction below, uses an **explicit logical
key**, NOT `trace_id`.

### Minimum table schema (§9.2, authoritative)

```
decisions(decision_id, scope, state, rationale_ref, supersedes_id)
tasks(task_id, project_id, status, current_step, updated_at)
artifacts(artifact_id, path, mime_type, hash, version)
```
The spec's `decisions` table uses **`scope`** (not `decision_key`) and a generic **`state`** column.
M4's `zm_decisions` follows this: `scope` is the decision-domain key, `state` is the generic domain
status. Requirements and Charter are mentioned only as Obsidian Project Home concepts (not as SQL
tables in §9.2), so M4's Requirement Registry and Project Charter are deliberate design extensions
that use the authoritative lifecycle-state enum for `lifecycle_status` and a generic `state` column
for domain status.

## decision_key (§4) — CORRECTED: explicit-only, NO trace_id fallback

**Authoritative evidence that trace_id is NOT a stable logical key:**
- `ingest.py:234` comment: *"enforce at-most-one active per active_key (=trace_id)"*.
- `ingest.py:287-301`: when a new `active` event arrives, the query matches the **prior different
  trace_id** and marks it `superseded`. This proves each version of a logical decision/state carries
  its **own** `trace_id`. Example: decision version A1 → trace_id T1, version A2 → trace_id T2 — two
  distinct trace_ids. Using `trace_id` as `decision_key` would therefore create **two independent
  active-uniqueness keys** for the same logical decision — incorrect. `trace_id` is a per-event
  lineage id and is explicitly unsafe as a logical key.

**Resolution precedence (deterministic, rebuildable, no LLM, no semantic similarity, no free-form
normalization):**
1. **Explicitly supplied canonical key** — if the decision event carries `decision_key`, `scope`, or
   `decision_id` (per spec §9.2 `decisions(decision_id, scope, ...)`), use it verbatim as the
   `decision_key`. This is the only accepted source of a stable logical key.
2. **No trace_id / active_key fallback.** The verified M2 `active_key` equals `trace_id`, which is
   per-version and unstable (evidence above). It MUST NOT be used as a `decision_key` fallback.
3. **Otherwise decision_key = NULL** (no key derived, no hashing of decision text, no semantic
   similarity):
   - the decision record is still projected and preserved;
   - no logical-domain active-uniqueness constraint applies to that record;
   - supersession/conflict for that record require explicit structured references
     (`supersedes`/`replaced_by`/`parent_trace_id`);
   - missing-key state is surfaced (e.g. a `list_conflicts`/`missing_keys` projection or a
     sanitized diagnostic) where appropriate.

**NEEDS DECISION check:** the spec §9.2 defines `decisions(decision_id, scope, state, ...)` (a
`decision_id` column exists in the table schema) but does **not** explicitly mandate that every
decision *event* must carry a `decision_id`/`scope`. Canonical events have no such field. Because the
spec does not require a key for every decision event, the preferred safe behavior (key = NULL,
preserve, surface) applies. **No NEEDS DECISION stop is required** — but M4.1 implementation must
decide the projector's handling: decisions without an explicit key are projected with `decision_key`
NULL and excluded from uniqueness enforcement (documented in M4.1).

## state_key (§5) — CORRECTED: explicit-only, NO trace_id fallback

Same analysis as decision_key. A `state_key` is a **logical state slot** (e.g. `current_milestone`,
`schema_version`, `active_increment`). Two updates to the same slot must resolve to the **same**
`state_key`. Since `trace_id` changes per update (evidence above), it cannot serve as the logical
`state_key`.

**Resolution precedence:**
1. **Explicitly supplied `state_key`** from the canonical event — used verbatim.
2. **No trace_id / active_key fallback.** `trace_id` is per-update and unstable; it MUST NOT be used
   as `state_key`.
3. **Otherwise state_key = NULL**:
   - the project-state record is still projected and preserved;
   - no `(project_id, scope, state_key)` active-uniqueness constraint applies;
   - supersession requires explicit `supersedes`/`replaced_by`;
   - missing-key state is surfaced.

If a current-state projection is required to carry a `state_key` and cannot resolve one, M4 returns a
fixed sanitized projection failure (error class `missing_state_key`) rather than inventing a key.

## Distinguish lifecycle_status from domain state (§3)

`lifecycle_status` is constrained to the **closed** lifecycle enum (§7.1) — only
`raw/observed/candidate/confirmed/active/superseded/conflicted/archived/deleted`.

Domain-specific states that are **not** in the lifecycle enum
(`proposed`, `accepted`, `satisfied`, `blocked`, `rejected`, …) are represented **only** in the
separate generic **`state`** column (per spec §9.2 `decisions(...state...)`), never in
`lifecycle_status`.

Examples (explicitly supported mappings; the generic `state` TEXT is not a closed enforced enum):
- Decision rejected: `state = "rejected"`, `lifecycle_status = "archived"`.
- Decision accepted/effective: `state = "accepted"`, `lifecycle_status = "active"`.
- Decision superseded: `state = "superseded"`, `lifecycle_status = "superseded"`.
- Decision conflicted: `state = "conflicted"`, `lifecycle_status = "conflicted"`.
- Requirement satisfied: `state = "satisfied"`, `lifecycle_status = "confirmed"` (+ verification link).
- Requirement blocked: `state = "blocked"`, `lifecycle_status = "observed"`/`"candidate"`.
- Requirement proposed (not yet promoted): `state = "proposed"`, `lifecycle_status = "candidate"`.

An `assistant_claim`/`suggestion` stays `candidate` until an explicit event or verification promotes
it (§6.3). No new closed domain enum is manufactured; `state` accepts the documented domain
vocabulary as sanitized TEXT.

## Uniqueness constraints (§4 review) — NULL-safe

A uniqueness constraint is valid only when its logical key is **stable and non-NULL**.

- **Decisions:** partial unique index `UNIQUE(project_id, scope, decision_key) WHERE lifecycle_status='active' AND decision_key IS NOT NULL`.
  - SQLite's `UNIQUE` already treats NULLs as distinct, so rows with `decision_key IS NULL` never
    collide — exactly the "no uniqueness when key is NULL" behavior. The explicit `AND decision_key IS
    NOT NULL` documents intent.
  - `scope` may also be NULL for a key-less decision; the index then does not fire.
- **Current project state:** partial unique index `UNIQUE(project_id, scope, state_key) WHERE lifecycle_status='active' AND state_key IS NOT NULL`.
  - `scope` defaults to `project:<project_id>` only when an explicit `state_key` is present; if
    `state_key` is NULL, no uniqueness is enforced.

No trace-specific fallback can defeat logical uniqueness, because trace_id is never part of these keys.

## Supersession (§5) — explicit only

Supersession remains **explicit**. A new `trace_id` implies **nothing** about:
- same logical decision;
- same state slot;
- supersession;
- replacement.

Use explicit `supersedes` / `replaced_by` / `active_key` / `decision_key` / `state_key` **only where
actually supplied/verified**. The projector never infers supersession from `trace_id` proximity or
recency.

## M4 architecture (unchanged)

- Canonical JSONL (authoritative) → derived SQLite v7 (disposable, rebuildable) → TRUE READ-ONLY read
  path reusing M3 `open_readonly` + `query_only`.
- Deterministic, idempotent **projector** (single transaction, only writer) separates write/project
  path from retrieval. M3 retrieval guarantees unchanged.
- Zero LLM / zero network for routine ops. No LLM-context injection (M7). No M5 authorization.

## Models (resolved, corrected)

### Project Charter
Versioned rows; `lifecycle_status` from the closed enum; active version = `lifecycle_status='active'`.
Update appends `version+1` `active` row, prior → `superseded` (never deleted). `get_project_charter`
returns the `active` row; historical retrieval returns all versions. Domain nuance (if any) in a
generic `state` column.

### Requirement Registry
`requirement_id` (stable, explicit). `state` (generic domain: proposed/active/satisfied/blocked/
rejected/superseded/archived) + `lifecycle_status` (closed enum). A `proposed` requirement stays
`candidate` until explicit promotion. Supersession explicit (`supersedes`/`replaced_by`).
`list_requirements`/`get_requirement` return non-deleted rows with provenance.

### Decision Log
`decision_id` (stable, explicit). **`scope`** (decision-domain key, per §9.2) = `decision_key`.
`state` (generic domain) + `lifecycle_status` (closed enum; effective decision = `active`).
`rationale_ref`/`alternatives` only when explicitly supplied (references, not free-text blobs).
Supersession explicit. Active-decision uniqueness via the NULL-safe partial unique index above.
**If a decision event carries no explicit `decision_key`/`scope`/`decision_id` → `decision_key` = NULL,
record preserved, no uniqueness, surfaced as missing-key.** Conflict → preserve + surface, not winner.

### Current Project State
`state_key` (explicit logical slot, else NULL) + `scope` (default `project:<project_id>` when
`state_key` present). `lifecycle_status='active'` marks the current value. Active-uniqueness key
`project_id + scope + state_key` (NULL-safe partial unique index). Active selected by
`lifecycle_status`, not timestamp. Update = new `active` row, prior → `superseded`. **If no explicit
`state_key` → `state_key` = NULL, record preserved, no uniqueness, surfaced.**

### Verification Records
First-class; distinct from claims. `verification_id`, `subject_type`
(`requirement|decision|state|artifact|task|implementation|milestone`), `subject_id`, `project_id`,
`method`, `command`/`reference` (sanitized), `observed_result` (sanitized), `tested_commit`,
`source_event_id`, `timestamp`, `verification_status` (M2 enum), `artifact_references`. No secrets/raw
dumps/unrestricted paths. Does NOT auto-promote unrelated claims.

### Artifact integration
Reuses M2 `zm_artifacts` (metadata refs). New `zm_project_artifacts` for project-level linkage
(`artifact_id` FK → `zm_artifacts`, `project_id`, `safe_reference`, linked requirement/decision/state
keys). No content duplication; no arbitrary file reads; no unrestricted path exposure.

### Provenance
`source_event_id`, `trace_id`, `session_id`, `project_id`, `profile_id` (if supplied), `created_at`,
`verification_reference`, `supersession_reference`. Missing provenance not inferred. (`trace_id` is
stored for lineage/provenance only — never as a logical decision/state key.)

## Rebuild behavior (unchanged)

`rebuild_project_memory(project_id)` reprojects all M4 derived tables deterministically from canonical
JSONL + M2 substrate. Same stream → same active charter/requirements/decisions/state/artifacts/
verifications/supersession/conflict. Incremental == rebuild. No competing canonical project-state file.

## Schema impact — v7 review (§7, corrected)

All six tables required (charter/requirement are M4 extensions the objective mandates; spec mentions
them only as Obsidian concepts). Aligns with spec §9.2 where applicable. **Corrections vs prior draft:
added generic `state` column to `zm_decisions`/`zm_requirements`; added `lifecycle_status` CHECK
(constrained to the closed enum); `decision_key`/`state_key` are NULL-able; partial unique indexes
carry explicit `IS NOT NULL`.**

**zm_project_charters** — PK `charter_id`; `project_id`; `version` (int, monotonic); `lifecycle_status`
(closed enum, CHECK); `state` (generic TEXT, nullable); `supersedes` (self-FK); provenance; UNIQUE
`(project_id)` WHERE `lifecycle_status='active'`; index `project_id`; downgrade drops table → v6.

**zm_requirements** — PK `requirement_id`; `project_id`; **`state`** (generic domain TEXT);
`lifecycle_status` (closed enum, CHECK); `verification_status` (M2 enum); `supersedes`/`replaced_by`
(self-FK); linked ids (references only); provenance; index `project_id`; downgrade drops table.

**zm_decisions** — PK `decision_id`; `project_id`; **`scope`** (decision-domain key; spec §9.2; served
as `decision_key`); **`state`** (generic domain TEXT: proposed/accepted/rejected/superseded/conflicted/
archived); `lifecycle_status` (closed enum, CHECK; effective = `active`); `rationale_ref`,
`alternatives` (references, nullable); `supersedes_id` (self-FK); `effective_at`; linked ids;
provenance; **partial UNIQUE `(project_id, scope, decision_key) WHERE lifecycle_status='active' AND
decision_key IS NOT NULL`**; index `project_id`, `scope`; downgrade drops table.

**zm_project_state** — PK `id` or `(project_id, scope, state_key, version)`; `project_id`; **`scope`**
(default `project:<project_id>` only when `state_key` present); **`state_key`** (explicit logical slot,
nullable); `state_value`/`reference` (sanitized); `lifecycle_status` (closed enum, CHECK; `active` =
current); `verification_status`; `effective_at`; `supersedes`; provenance; **partial UNIQUE
`(project_id, scope, state_key) WHERE lifecycle_status='active' AND state_key IS NOT NULL`**; index
`project_id`, `state_key`; downgrade drops table.

**zm_verifications** — PK `verification_id`; `subject_type`; `subject_id`; `project_id`; `method`;
`sanitized_command_ref`; `observed_result` (sanitized); `tested_commit`; `source_event_id`;
`timestamp`; `verification_status`; `artifact_references`; provenance; index `subject_id`,
`project_id`; downgrade drops table. No secret/raw-output columns.

**zm_project_artifacts** — PK `(artifact_id, project_id)`; FK → `zm_artifacts.artifact_id`;
`project_id`; `artifact_type`; `version`; `safe_reference`; `source_event_id`; `created_at`;
`verification_status`; linked ids (references); index `project_id`; downgrade drops table.

**Migration 7:** `migrate_7.py` with `up` (create six tables + indexes + NULL-safe partial unique
indexes + `lifecycle_status` CHECK) and `down` (drop all six → v6). `CURRENT_SCHEMA_VERSION` becomes 7.
Idempotent projector uses stable identities + dedup keys (no duplicate rows on reprocess).

## Idempotence & transaction safety (unchanged)

Stable identities + dedup keys ⇒ reprocessing same canonical event never duplicates. Projector writes
in one transaction: state + supersession + verification + artifact links commit together or roll back
together.

## Deletion behavior (preserve Decision B) — unchanged

Canonical JSONL append-only; no physical purge. Logical deletion marks derived row
`lifecycle_status='deleted'` (reusing M2 convention + tombstone), preserving provenance, excluded from
active queries, rebuildable deterministically.

## Secret safety / Profile boundary / Performance (unchanged)

Synthetic-secret scans over all M4 surfaces; no raw exception strings. M4 stores `profile_id`/`project`
mappings (provenance) only — no M5 access policy. Performance: measure first; baseline p95
(current-state <20ms, requirements <20ms, active-decision <20ms, verification <20ms, rebuild(200)<2s);
no invented SLA.

## Proposed M4 increments (unchanged structure)

M4.1 contracts + schema/migration v7 · M4.2 Charter+Requirements · M4.3 Decision Log+supersession/
conflict · M4.4 Current-State reducer · M4.5 Verification+Artifact integration · M4.6 Read APIs + M3
composition · M4.7 Rebuild/performance/final acceptance. Each: objective/files/schema/tests/
acceptance/rollback/deps/exclusions.

## Acceptance matrix (unchanged — all criteria mapped to planned tests)

Charter create/version/supersede; requirement create/transition/supersede; decision
create/accepted/rejected/supersede/conflict/active-uniqueness; state create/update/supersede/
active-uniqueness; verification create/link/no-auto-promote; artifact link; provenance; idempotence;
incremental==rebuild; rebuild determinism; rollback; deleted-handling; **lifecycle_status never
receives non-enum values (proposed/accepted/satisfied/blocked/rejected rejected from
lifecycle_status; domain states in `state`)**; **decision/state records without explicit key →
decision_key/state_key NULL, no uniqueness, surfaced**; **trace_id never used as logical key**; secret
absence; M3 unchanged; no real ~/.hermes; no LLM/network; no M5 behavior. Final acceptance:
`.venv/bin/python -m pytest tests/ -q`; count must not decrease without justified removal.

## State bookkeeping mismatch (§8) — recorded correction

`project-state.yaml` line 305 reads `next_incomplete_milestone: M3` while `implementation-plan.json`
reads `next_incomplete_milestone: M4`. Pre-existing from the M3.6 baseline-guard sync; neither file is
changed now (per instructions).

**Exact correction required when M4.1 becomes VERIFIED:** set `project-state.yaml` line 305
`next_incomplete_milestone: M3` → `next_incomplete_milestone: M4`. (`current_milestone: M3` stays
correct — M3 is the latest verified milestone; `m3_status: verified` stays. Only the
`next_incomplete_milestone` pointer is wrong.) No change to `implementation-plan.json` is needed at
that point (it already reads M4).

## Unresolved decisions — RESOLVED / DOCUMENTED

1. **Master-spec vocabulary** — RESOLVED. Single closed lifecycle enum (§7.1); requirements/decisions/
   charter reuse it for `lifecycle_status` + a generic `state` column (§9.2). No vocabulary invented.
2. **decision_key** — RESOLVED (explicit-only). `trace_id`/`active_key` are per-version and unstable
   (`ingest.py:234,287-301` evidence); they are NOT used as a fallback. Key-less decisions →
   `decision_key` NULL, preserved, surfaced (preferred safe behavior; spec does not mandate a key per
   event, so no NEEDS DECISION stop).
3. **state_key** — RESOLVED (explicit-only). Same reasoning; `trace_id` not used. Key-less state →
   `state_key` NULL, preserved, surfaced.
4. **lifecycle_status vs domain state** — RESOLVED. `lifecycle_status` strictly the closed enum;
   domain states in separate generic `state` (spec §9.2).
5. **Conflict semantics** — RESOLVED (§7.3). Preserve all sources, surface `conflict_set`; no silent
   overwrite, no auto-winner, do NOT force both `conflicted`.
6. **Uniqueness NULL behavior** — RESOLVED. Partial unique indexes carry `IS NOT NULL`; SQLite treats
   NULL keys as distinct (no false collisions).
7. **State bookkeeping mismatch** — recorded (§8); corrected when M4.1 VERIFIED.

## Deliverable status

- Created/updated: this M4 plan artifact only.
- Modified: nothing else (no source, tests, state, plan, or M0–M3 evidence).

M4 PLAN: READY FOR IMPLEMENTATION
Vocabulary: CONFIRMED
decision_key: STABLE
state_key: STABLE
trace_id fallback: NOT USED FOR LOGICAL KEYS
Schema target: v7
Working tree: clean
