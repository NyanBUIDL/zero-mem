# M2.3 — Lifecycle, Verification, Supersession, and Rebuild Projection

**Status:** READY FOR APPROVAL (auto-approved under continuous M2 execution)
**Milestone:** M2 (increment 3)
**Authority:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`, `ARCHITECTURE.md`,
`AGENTS.md`, master M2 plan (`2026-08-05_...-m2-sqlite-metadata-state-relations-indexes.md`),
`implementation-plan.json`, `project-state.yaml`, accepted M1 envelope contract
(`src/capture/event_types.py`, `src/capture/validation.py`), verified M2.1/M2.2 source,
`acceptance-m2-increment-1.md`, `acceptance-m2-increment-2.md`.
**Predecessor:** M2.2 VERIFIED (canonical 227 passed; schema v2; HEAD e5b11c7).
**Next increments:** M2.4 relations/scopes, M2.5 indexes/FTS5, M2.6 retention/tombstones,
M2.7 final acceptance.

---

## 1. Objective and non-goals

M2.3 adds the **derived lifecycle-state projection** (`zm_lifecycle`), the **derived
verification/provenance projection** (`zm_provenance`), and the **`rebuild_from_jsonl()`**
capability that reproduces the entire derived SQLite layer from canonical JSONL. SQLite
remains a disposable, fully-rebuildable projection; JSONL stays authoritative.

Scope is exactly:
- Lifecycle-state projection (mirror of observed `lifecycle_status`, plus the dedicated
  `zm_lifecycle` table that later increments extend).
- Verification-state projection (seed one `zm_provenance` row per event from the envelope's
  `verification_status` and a deterministic verifier; verifier-rank stored as **data only**).
- Recorded `conflicted` / `archived` / `deleted` states (as observed envelope values).
- Deterministic state transitions (current state = envelope value; no invented transition logic).
- First-write / later-event idempotent behavior (seeded on new-event insert only).
- `rebuild_from_jsonl()` (full rebuild into a derived-empty SQLite DB; parity with incremental
  ingest; deterministic and repeatable; malformed lines handled like ingest).

**Non-goals (explicitly excluded, assigned to later increments):**
- `zm_relations` edges, explicit `superseded_by` link creation, and active-key *uniqueness
  enforcement*: **M2.4**. M2.3 creates the `zm_lifecycle` columns (`superseded_by`,
  `active_key`) and seeds them as `NULL` (no invented enforcement).
- `zm_scopes` (project/profile/knowledge-space mappings): **M2.4**.
- FTS5 (`zm_fts`) and relational indexes: **M2.5**.
- Retention tombstones and physical-delete policy: **M2.6**.
- Retrieval, ranking, scoring, query routing, MCP, Obsidian, context injection: never in M2.

---

## 2. Storage roles (unchanged)

- **Authoritative:** canonical append-only JSONL (`JsonlCaptureStore`, M1).
- **Derived:** SQLite (`zm_meta`, `zm_ingest_*`, `zm_lifecycle`, `zm_provenance`), rebuildable.
- Truth order: JSONL-first, SQLite-second. Rebuild reproduces index state exactly.

---

## 3. Schema (migration v3, additive over v2)

`zm_lifecycle` and `zm_provenance` are created. `zm_meta` (v1) and `zm_ingest_*` (v2) are
unchanged. `CURRENT_SCHEMA_VERSION` becomes **3**.

```sql
CREATE TABLE zm_lifecycle (
  event_id      TEXT PRIMARY KEY,
  current_state TEXT NOT NULL,   -- mirror of zm_meta.lifecycle_status (observed value)
  superseded_by TEXT,            -- NULL in M2.3 (supersession link created in M2.4)
  active_key    TEXT,            -- NULL in M2.3 (uniqueness enforcement in M2.4)
  updated_at    TEXT NOT NULL
);

CREATE TABLE zm_provenance (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id           TEXT NOT NULL,
  verification_status TEXT NOT NULL,  -- envelope value
  verifier            TEXT NOT NULL,   -- 'deterministic_check' (M1 capture is deterministic/local)
  evidence_ref        TEXT,            -- trace_id of the source envelope
  recorded_at         TEXT NOT NULL
);
```

### 3.1 Lifecycle projection
- `current_state` is seeded from `envelope.lifecycle_status` (validated by `validate_envelope`).
  Accepted values: `raw, observed, candidate, confirmed, active, superseded, conflicted,
  archived, deleted`.
- `superseded_by`, `active_key` are `NULL` in M2.3 (reserved; M2.4 enforces).
- One row per `event_id` (PRIMARY KEY). Seeded on first insert; never silently overwritten
  by later events in M2.3 (idempotent by `event_id`; updates belong to M2.4 supersession).

### 3.2 Verification-state projection
- One `zm_provenance` row per `event_id`, seeded on first insert.
- `verification_status` = `envelope.verification_status` (accepted: `none,
  direct_tool_output, user_confirmation, deterministic_verification, approval`).
- `verifier` = `'deterministic_check'` (M1 capture is a deterministic local operation; no LLM).
- `evidence_ref` = `envelope.trace_id` (provenance pointer to the source trace).
- Verifier-rank ordering (tool_output / test / user_confirmation / deterministic_check outrank
  assistant self-report) is **stored as data only**; M2.3 applies no ranking, scoring, or
  retrieval selection.

### 3.3 State keys / approved scope keys
- M2.3 records `current_state` only. `active_key` (the entity/scope/state key for the
  "active is unique" rule) is left `NULL` because its composition and enforcement are M2.4's
  responsibility (per master M2 plan §12). No key is invented in M2.3.

### 3.4 Active-state uniqueness
- Enforcement (at-most-one `active` per key, mark prior `superseded`) is **M2.4**.
- M2.3 only stores the observed `current_state`; it does not enforce or mutate uniqueness.

### 3.5 Supersession links
- The `superseded_by` column exists; M2.3 seeds it `NULL`. Creating the supersession edge
  (`zm_relations` `supersedes`/`replaced_by`) from `relation_ids`/explicit `replaced_by` is
  **M2.4**. No supersession logic is invented in M2.3.

### 3.6 Conflicted / archived / deleted states
- Stored verbatim as observed `current_state` values. M2.3 performs no special transition;
  they are valid lifecycle states carried from the envelope (deletion tombstones are M2.6).

### 3.7 Deterministic state transitions
- `current_state` is a direct projection of the envelope value. M2.3 introduces no transition
  function; the envelope is the source of truth. This keeps incremental ingest and rebuild
  identical (no runtime state drift).

### 3.8 First-write and later-event behavior
- First occurrence (`new_event`): insert `zm_meta`, `zm_lifecycle`, `zm_provenance` in one
  transaction.
- Later event with same `event_id` (duplicate): all three inserts are skipped (idempotent);
  no row mutated.
- Later event with same `content_hash` different `event_id` (duplicate content): `zm_meta`
  skipped; lifecycle/provenance not seeded for the new id (no new event row).
- Event-id/content conflict: `zm_meta` original kept; no new lifecycle/provenance row.

---

## 4. `rebuild_from_jsonl()`

Signature: `rebuild_from_jsonl(store, jsonl_paths, source_ids=None, synchronous_full=False)
-> dict[str, IngestionReport]`.

Behavior:
1. **Drop all derived tables**: `zm_meta`, `zm_lifecycle`, `zm_provenance`,
   `zm_ingest_checkpoint`, `zm_ingest_log`. `zm_migrations` is preserved (schema version
   survives); `zm_artifacts` (future M2.6) preserved.
2. **Recreate schema** via `store.ensure_schema()` (recreates all derived tables for the
   current `CURRENT_SCHEMA_VERSION`).
3. **Ingest each file** in order via `ingest_file` (reuses M2.2 per-line transactions,
   idempotence, checkpoint, consumed-prefix hash). Returns one `IngestionReport` per file.
4. **Deterministic**: identical input set and order → identical derived state (same key sets
   and `current_state`/`verification_status` values). Running rebuild twice yields identical
   rows (it drops first).
5. **Parity with incremental ingest**: for a fixed set of JSONL files, the final `zm_meta`,
   `zm_lifecycle`, and `zm_provenance` key sets and state values equal the result of ingesting
   the same files incrementally (the durable data is identical; only `zm_ingest_checkpoint` /
   `zm_ingest_log` history may differ, which is not part of the parity contract).
6. **Malformed-line behavior**: identical to M2.2 — sanitized `invalid_record`, ingestion
   continues; no dead-letter, no replay.
7. **Crash safety**: each file's `ingest_file` commits per line. If rebuild is interrupted,
   re-running `rebuild_from_jsonl` drops and recreates cleanly (idempotent, no corruption).
   JSONL is never mutated; SQLite is always reconstructable from JSONL.
8. **No LLM / no network**; read-only over JSONL; writes only to the derived SQLite DB under a
   temporary directory in tests.

### 4.1 Full rebuild into an empty SQLite database
- A store opened on a non-existent path (or one with only `zm_migrations`) rebuilds fully:
  `rebuild_from_jsonl` drops (no-op for absent tables) then re-ingests all supplied files.

---

## 5. Transaction and crash safety (restated for M2.3)

- WAL mode; `synchronous=NORMAL` default, `FULL` when `synchronous_full=True`.
- Per-line transactions (from M2.2). Lifecycle/provenance inserts ride inside the same
  per-line transaction as the `zm_meta` insert for `new_event`.
- No raw JSONL mutation/truncation/reordering.
- Consumed-prefix hash (from M2.2) continues to guard `zm_ingest_checkpoint` during incremental
  ingest; rebuild resets the checkpoint by dropping the table.

---

## 6. Migrations and downgrade

- `migrate_3.py`: `up` creates `zm_lifecycle` + `zm_provenance`; `down` drops both.
- `CURRENT_SCHEMA_VERSION = 3` (auto-bumped by the registry key set).
- `downgrade_to(2)` drops `zm_lifecycle`/`zm_provenance`, returns to v2 (M2.2 state).
- `downgrade_to(1)` (further) drops `zm_ingest_*` too, returns to v1 (M2.1 state).
- Failed v3 migration rolls back, version does not advance, `zm_migrations` unchanged.
- Unknown future DB version (db > code) rejected; downgrade to >= current rejected.

---

## 7. Files and tests

### New / modified product code
- `src/storage/migrations/migrate_3.py` (new) — v3 DDL.
- `src/storage/migrations/__init__.py` (modified) — register `migrate_3`; `CURRENT_SCHEMA_VERSION=3`.
- `src/storage/ingest.py` (modified) — seed `zm_lifecycle` + `zm_provenance` on `new_event`;
  add `rebuild_from_jsonl`, `get_lifecycle`, `get_provenance`, `list_by_lifecycle_state`,
  `verify_rebuild_parity` helpers; extend `scan_sqlite_for_secrets` to cover the new tables;
  update module docstring/boundaries.
- `src/storage/sqlite_store.py` — unchanged (M2.1 module; not modified in M2.3).

### Tests
- `tests/unit/test_m2_rebuild.py` (new) — focused M2.3 tests:
  - migration v2->v3 apply; downgrade v3->v2 drops lifecycle/provenance; reopen idempotent.
  - lifecycle projection: row mirrors envelope `lifecycle_status`; conflicted/archived/deleted
    stored verbatim.
  - provenance projection: one row per event; `verifier='deterministic_check'`;
    `verification_status` from envelope; `evidence_ref=trace_id`.
  - first-write/later-event idempotence: duplicate event_id/content does not add lifecycle/
    provenance rows; conflict keeps original.
  - `rebuild_from_jsonl`: full rebuild populates zm_meta/zm_lifecycle/zm_provenance; parity with
    incremental ingest (same key sets + states); deterministic repeated rebuild identical;
    malformed line handled (sanitized, continues); empty-DB rebuild works; unknown-future /
    downgrade rejected.
  - transaction/crash safety: per-line commit; simulated commit failure rolls back the whole
    line's zm_meta+lifecycle+provenance (no partial row).
  - secret scan clean across zm_meta/zm_lifecycle/zm_provenance/zm_ingest_log (synthetic secret
    in `sanitized_content` never stored).
  - no JSONL mutation; no real `~/.hermes` writes; no LLM/network; no later-M2 tables.

### Evidence
- `acceptance-m2-increment-3.md` (new).

---

## 8. Rollback / runbook

- To roll back M2.3 schema: `store.downgrade_to(2)` (drops `zm_lifecycle`/`zm_provenance`).
  Index/rebuild state is regenerated from JSONL via `rebuild_from_jsonl` after any rollback.
- Rebuild is always available to reconstruct the derived layer from canonical JSONL; no
  separate backup is required for the derived layer (JSONL is the backup).

---

## 9. Objective acceptance criteria (all must pass before M2.3 is VERIFIED)

1. `zm_lifecycle` and `zm_provenance` created by migration v3; `CURRENT_SCHEMA_VERSION == 3`.
2. Lifecycle projection mirrors `lifecycle_status`; `conflicted`/`archived`/`deleted` stored
   verbatim when observed.
3. Provenance projection seeds exactly one row per event with `verifier='deterministic_check'`,
   `verification_status` from envelope, `evidence_ref=trace_id`.
4. Idempotence: duplicate `event_id`/`content_hash` and conflicts add no lifecycle/provenance
   rows; original kept.
5. `rebuild_from_jsonl` reproduces identical `zm_meta` + `zm_lifecycle` + `zm_provenance` key
   sets and state values vs incremental ingest (parity).
6. Deterministic repeated rebuild is identical (drop + recreate is stable).
7. Malformed JSONL lines during rebuild are sanitized `invalid_record` and ingestion continues.
8. Crash safety: a simulated per-line commit failure rolls back the entire line (zm_meta +
   lifecycle + provenance) — no partial row; resume/rebuild reconstructs cleanly.
9. Migration downgrade v3->v2 drops the two new tables and restores v2 state; unknown-future
   version rejected.
10. Secret scan clean across all derived tables (no synthetic secret present).
11. JSONL byte-for-byte immutable; no real `~/.hermes` writes; no LLM/network calls; no later-M2
    tables/behavior (relations/scopes/FTS5/retention/retrieval).
12. Canonical suite passes with no regression (227 → N passed).

---

## 10. Self-review against master M2 plan

- Covers master §3.3 (`zm_lifecycle`) and §3.4 (`zm_provenance`) table shapes: ✓ (column names/
  types match; `superseded_by`/`active_key` present, seeded NULL pending M2.4 enforcement).
- Covers master §7 (lifecycle seeded from envelope; supersession link creation deferred to M2.4):
  ✓ (projection only; no invented supersession).
- Covers master §8 (provenance seeded from envelope + deterministic verifier; rank stored as
  data only): ✓.
- Covers master §12 M2.3 ("zm_lifecycle, zm_provenance, full rebuild_from_jsonl()"):
  ✓.
- Does NOT do master §12 M2.4 (zm_relations/zm_scopes/active-key enforcement): ✓ excluded.
- Does NOT do M2.5 FTS5 / M2.6 retention: ✓ excluded.
- Rebuild parity (master §10/§12 #1) and determinism (§12 #2): ✓.
- No new product decision required; stays within approved M2 architecture: ✓.

---

## 11. Exact implementation sequence (within M2.3)

1. Write `migrate_3.py`; register in `__init__.py` (bumps to v3).
2. Extend `ingest.py`: seed lifecycle + provenance on `new_event`; add `rebuild_from_jsonl`,
   `get_lifecycle`, `get_provenance`, `list_by_lifecycle_state`, `verify_rebuild_parity`; extend
   `scan_sqlite_for_secrets` to new tables; update module docstring.
3. Write `tests/unit/test_m2_rebuild.py`.
4. Run focused M2.3 tests, then `pytest tests/ -q` (canonical, no regression).
5. Ad-hoc verifier (temp dirs): rebuild parity, secret clean, no real `~/.hermes` writes.
6. Write `acceptance-m2-increment-3.md`.
7. Commit impl+tests+evidence; bind `project-state.yaml` + `implementation-plan.json`; commit state.
8. Clean working tree before M2.4.
