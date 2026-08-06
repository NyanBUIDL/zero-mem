# M2.4 — Relations and Project/Profile/Knowledge-Space Mappings

**Status:** READY FOR APPROVAL (auto-approved under continuous M2 execution)
**Milestone:** M2 (increment 4)
**Authority:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`, `ARCHITECTURE.md`, `AGENTS.md`,
master M2 plan (`...-m2-sqlite-metadata-state-relations-indexes.md`), `implementation-plan.json`,
`project-state.yaml`, accepted M1 envelope contract (`src/capture/event_types.py`,
`src/capture/validation.py`), verified M2.1/M2.2/M2.3 source, `acceptance-m2-increment-*.md`.
**Predecessor:** M2.3 VERIFIED (canonical 249 passed; schema v3; HEAD 3340a8e).
**Next increments:** M2.5 indexes/FTS5, M2.6 retention/tombstones, M2.7 final acceptance.

---

## 1. Objective and non-goals

M2.4 adds the **explicit trace-relation projection** (`zm_relations`), the **scope mapping
projection** (`zm_scopes`: project / profile / knowledge_space), the **active-state uniqueness
enforcement** and **supersession links** (completing `zm_lifecycle` columns reserved in M2.3),
and the **artifact-metadata registry** (`zm_artifacts`, populated only from explicit,
authorized artifact references). All are derived from the M1 envelope; nothing is inferred.

Scope:
- `zm_relations`: edges from envelope-present signals only — `parent_trace_id` => `child_of`,
  `relation_ids` entries => `derived_from` (to an existing event_id or the earliest event of an
  existing trace_id). No invented relation types.
- `zm_scopes`: one row per observed `project_id` / `profile_id` (and `knowledge_space_id` if an
  optional field is present). No cwd/repo/prompt inference; no cross-profile writes.
- Active-state uniqueness: when an `active` event is ingested, any prior `active` event sharing
  its `active_key` (= `trace_id`, the entity) is marked `superseded` (zm_lifecycle update) and a
  `supersedes` edge is written (zm_relations). No silent overwrite — a link/record is written.
- Supersession links: realized via the `supersedes`/`superseded_by` edge + lifecycle update above.
- `zm_artifacts` registry: created in v4; populated only when an envelope carries an explicit
  `artifact_refs` list of `{artifact_id, content_hash, kind, retention}` (authorized references).
  M2.4 records metadata only; artifact *content* storage stays deferred.
- Relation provenance: each `zm_relations` edge records `verifier='deterministic_check'` and
  `evidence_ref=trace_id` (who asserted the relation, deterministically).
- Idempotent rebuild: `rebuild_from_jsonl` re-derives relations/scopes/artifacts because they are
  projected inside the per-line new-event transaction (same as M2.3 lifecycle/provenance).

**Non-goals (explicitly excluded):**
- Retrieval, ranking, scoring, query routing, MCP, Obsidian, context injection: never in M2.
- FTS5 content indexing (`zm_fts`): **M2.5**.
- Retention tombstones / physical-delete policy: **M2.6**.
- Authorization or access-control enforcement across profiles/projects: **M5** (M2.4 records
  observed scopes only; performs no cross-profile writes or policy decisions).

---

## 2. Storage roles (unchanged)

- **Authoritative:** canonical append-only JSONL (M1).
- **Derived:** SQLite (`zm_meta`, `zm_ingest_*`, `zm_lifecycle`, `zm_provenance`, `zm_relations`,
  `zm_scopes`, `zm_artifacts`), fully rebuildable. JSONL first, SQLite second.

---

## 3. Schema (migration v4, additive over v3)

```sql
CREATE TABLE zm_relations (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  from_event_id TEXT NOT NULL,
  to_event_id   TEXT NOT NULL,
  relation      TEXT NOT NULL,   -- child_of / supersedes / derived_from (M2.4)
  verifier      TEXT NOT NULL,
  evidence_ref  TEXT,
  created_at    TEXT NOT NULL,
  UNIQUE (from_event_id, to_event_id, relation)
);

CREATE TABLE zm_scopes (
  scope_type   TEXT NOT NULL,     -- project / profile / knowledge_space
  scope_id     TEXT NOT NULL,
  display_name TEXT,
  parent_scope TEXT,
  created_at   TEXT NOT NULL,
  PRIMARY KEY (scope_type, scope_id)
);

CREATE TABLE zm_artifacts (
  artifact_id   TEXT PRIMARY KEY,
  content_hash  TEXT NOT NULL,
  kind          TEXT,
  retention     TEXT NOT NULL,
  origin_event_id TEXT,
  stored_path   TEXT,            -- NULL in M2.4 (content storage deferred)
  created_at    TEXT NOT NULL
);
```

`CURRENT_SCHEMA_VERSION` becomes **4**. `zm_meta` (v1), `zm_ingest_*` (v2), `zm_lifecycle`/
`zm_provenance` (v3) unchanged. M2.3's reserved `zm_lifecycle.superseded_by` / `active_key` are
now populated by M2.4 enforcement.

---

## 4. Relation derivation (envelope-present only)

For each NEW_EVENT (inside the per-line transaction, after `zm_meta` insert):
- **`child_of`**: if `envelope.parent_trace_id` is present and resolves to an existing event in
  `zm_meta` (the earliest event by `sequence` for that `trace_id`), insert
  `zm_relations(from=event_id, to=that_event, relation='child_of', verifier='deterministic_check',
  evidence_ref=trace_id)`.
- **`derived_from`**: for each id in `envelope.relation_ids`:
  - if id is an existing `event_id` in `zm_meta` => edge `derived_from` to it.
  - elif id is an existing `trace_id` in `zm_meta` => edge `derived_from` to that trace's earliest
    event.
  - else => skip (no invented target; the reference is not yet known — it may arrive later, but
    M2.4 does not retro-fit or infer).
- No other relation types are synthesized. The master enum also lists `replaced_by`/`reply_to`/
  `conflict_with`; those are emitted by later captures if present as typed signals — M2.4 handles
  `supersedes` (below) and otherwise only `child_of`/`derived_from` which are derivable from the
  M1 contract today.

---

## 5. Active-state uniqueness + supersession (completes zm_lifecycle)

`active_key` = `trace_id` (the entity/decision the trace represents). Deterministic, no inference.

- On ingesting a NEW_EVENT with `lifecycle_status == 'active'`:
  1. Set `zm_lifecycle.active_key = trace_id`, `current_state = 'active'`.
  2. Find any existing `zm_lifecycle` row with `active_key = trace_id` AND `current_state =
     'active'` (the prior active event for this entity).
  3. If one exists and its `event_id != this_event_id`: update it to `current_state='superseded'`,
     `superseded_by = this_event_id`; insert `zm_relations(from=this_event_id, to=prior_event_id,
     relation='supersedes', verifier='deterministic_check', evidence_ref=trace_id)`.
- This enforces "at most one active per entity" without silent overwrite (a link + superseded
  record preserves the prior state).
- An event ingested as `superseded` directly (envelope `lifecycle_status='superseded'`) keeps
  `current_state='superseded'` and `superseded_by` = envelope `superseded_by` if present (optional
  field), else NULL.
- `conflicted` / `archived` / `deleted` remain plain observed states (no special transition in
  M2.4; tombstones are M2.6).

---

## 6. Scope mappings (observed only)

- For each NEW_EVENT: if `envelope.project_id` present => upsert `zm_scopes('project', project_id)`.
- if `envelope.profile_id` present => upsert `zm_scopes('profile', profile_id)`.
- if optional `envelope.knowledge_space_id` present => upsert `zm_scopes('knowledge_space', id)`.
- `display_name` / `parent_scope` are NULL in M2.4 (no directory of names; recorded only when
  explicitly supplied). No cwd/repo/prompt inference; no cross-profile write.

---

## 7. Artifact metadata registry (authorized references only)

- `zm_artifacts` is created in v4.
- If `envelope.artifact_refs` is present (a list of `{artifact_id, content_hash, kind,
  retention}`), upsert one `zm_artifacts` row per reference (`stored_path` NULL — content storage
  deferred). If absent, the table stays empty. No artifact bytes are ingested; no content is read.
- This satisfies "approved artifact metadata references": the registry + ingestion path exist and
  are populated only from explicit, authorized envelope references.

---

## 8. Idempotent rebuild

`rebuild_from_jsonl` already re-runs `ingest_file` per file. Because M2.4 projects relations/
scopes/artifacts inside the per-line new-event transaction, a full rebuild re-derives them exactly.
The `UNIQUE(from_event_id, to_event_id, relation)` constraint and scope primary keys make
re-derivation idempotent. Parity (M2.3's `verify_rebuild_parity`) is extended to include
`zm_relations` / `zm_scopes` / `zm_artifacts` key sets.

---

## 9. Transaction and crash safety

- All M2.4 writes (relations/scopes/artifacts/lifecycle updates) occur inside the same per-line
  transaction as the `zm_meta` insert for `new_event` (begun/committed in `_commit_outcome`). A
  simulated commit failure rolls back the *entire* line (meta + lifecycle + provenance + relations
  + scopes + artifacts) — no partial row. Resume/rebuild reconstructs cleanly (M2.3 guarantee).

---

## 10. Migrations and downgrade

- `migrate_4.py`: `up` creates `zm_relations`, `zm_scopes`, `zm_artifacts`; `down` drops all three.
- `CURRENT_SCHEMA_VERSION = 4`.
- `downgrade_to(3)` drops the three new tables, returns to v3 (M2.3 state).
- Failed v4 migration rolls back, version does not advance. Unknown future DB version rejected;
  downgrade to >= current rejected.

---

## 11. Files and tests

- `src/storage/migrations/migrate_4.py` (new) — v4 DDL.
- `src/storage/migrations/__init__.py` (modified) — register `migrate_4`; `CURRENT_SCHEMA_VERSION=4`.
- `src/storage/ingest.py` (modified) — project relations/scopes/artifacts on new_event (same
  transaction); active-key uniqueness + supersession enforcement; extend `verify_rebuild_parity`
  to relations/scopes/artifacts; add helpers `get_relations(event_id)`, `get_scopes(scope_type)`,
  `get_artifact(artifact_id)`, `list_active_for_key`; update docstring.
- `tests/unit/test_m2_relations.py` (new) — focused M2.4 tests (below).
- `acceptance-m2-increment-4.md` (new).

### Focused tests
- migration v3->v4 apply; downgrade v4->v3 drops the three tables; reopen idempotent.
- `child_of` derived from `parent_trace_id` (links to earliest event of parent trace).
- `derived_from` derived from `relation_ids` (existing event_id and existing trace_id); unknown id skipped (no invention).
- active-key uniqueness: two `active` events same trace => first marked `superseded` + `supersedes` edge; no silent overwrite.
- conflicted/archived/deleted stored verbatim; no special transition.
- scopes: project_id/profile_id observed; knowledge_space only when optional field present; no cross-profile inference.
- artifact registry: populated only from explicit `artifact_refs`; empty otherwise; stored_path NULL.
- relation provenance: `verifier='deterministic_check'`, `evidence_ref=trace_id`.
- idempotence: duplicate event_id adds no new relations/scopes; rebuild parity includes relations/scopes/artifacts.
- no inferred cross-profile/cross-project relations: an event with only its own project_id never
  creates an edge to another project's events.
- transaction/crash safety: per-line commit failure rolls back whole line (incl. relations).
- secret scan clean (extends M2.3 scanner to new tables); JSONL immutable; no real `~/.hermes`;
  no LLM/network; no later-M2 tables (zm_fts absent).

---

## 12. Rollback / runbook

- `store.downgrade_to(3)` drops relations/scopes/artifacts; re-derive anytime via
  `rebuild_from_jsonl` (JSONL is the backup).

---

## 13. Objective acceptance criteria (all must pass before M2.4 is VERIFIED)

1. `zm_relations`, `zm_scopes`, `zm_artifacts` created by migration v4; `CURRENT_SCHEMA_VERSION == 4`.
2. Relations derived only from envelope-present `parent_trace_id` (`child_of`) and `relation_ids`
   (`derived_from`); unknown targets skipped (no invention).
3. Active-state uniqueness enforced: a new `active` event for an existing active key marks the
   prior one `superseded` and writes a `supersedes` edge (no silent overwrite).
4. Scopes recorded only from explicit `project_id`/`profile_id` (and optional `knowledge_space_id`);
   no cwd/repo inference; no cross-profile writes.
5. Artifact registry populated only from explicit `artifact_refs`; empty otherwise.
6. Relation provenance recorded (`verifier='deterministic_check'`, `evidence_ref=trace_id`).
7. Idempotence: duplicates add no new relations/scopes; rebuild parity includes relations/scopes/
   artifacts.
8. No inferred cross-profile/cross-project relationships.
9. Transaction/crash safety: per-line commit failure rolls back the whole line (incl. relations).
10. Migration downgrade v4->v3 drops the three tables; unknown-future version rejected.
11. Secret scan clean across all derived tables; JSONL immutable; no real `~/.hermes`; no LLM/network;
    no later-M2 tables/behavior (zm_fts absent; no retrieval/ranking/routing).
12. Canonical suite passes with no regression (249 → N passed).

---

## 14. Self-review against master M2 plan

- Covers master §3.2 (`zm_relations` shapes/relation types), §3.5 (`zm_scopes`), §3.6 (`zm_artifacts`
  registry), §7 (supersession link + active-key uniqueness), §9 (scopes observed only, no inference),
  §12 M2.4 ("zm_relations, zm_scopes, zm_lifecycle supersession/active-key enforcement"): ✓.
- Does NOT do M2.5 FTS5 / M2.6 retention / M3 retrieval: ✓ excluded.
- Supersession link creation is assigned to M2.4 by master §12 (the user's M2.3 bulleted it, but
  the authoritative increment split places enforcement in M2.4 — reconciled here, no new decision).
- No new product decision required; stays within approved M2 architecture: ✓.

---

## 15. Exact implementation sequence (within M2.4)

1. Write `migrate_4.py`; register in `__init__.py` (bumps to v4).
2. Extend `ingest.py`: project relations/scopes/artifacts on new_event; active-key enforcement +
   supersession; extend `verify_rebuild_parity`; add helpers `get_relations`, `get_scopes`,
   `get_artifact`, `list_active_for_key`; update docstring.
3. Write `tests/unit/test_m2_relations.py`.
4. Run focused M2.4 tests, then `pytest tests/ -q` (canonical, no regression).
5. Ad-hoc verifier (temp dirs): relations/scopes/artifacts projection, active-key enforcement,
   secret clean, no real `~/.hermes` writes.
6. Write `acceptance-m2-increment-4.md`.
7. Commit impl+tests+evidence; bind `project-state.yaml` + `implementation-plan.json`; commit state.
8. Clean working tree before M2.5.
