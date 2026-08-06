# M2.5 — Relational Indexes, FTS5, and Minimal Inspection Helpers

**Status:** READY FOR APPROVAL (auto-approved under continuous M2 execution)
**Milestone:** M2 (increment 5)
**Authority:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`, `ARCHITECTURE.md`, `AGENTS.md`,
master M2 plan (`...-m2-sqlite-metadata-state-relations-indexes.md`), `implementation-plan.json`,
`project-state.yaml`, verified M2.1–M2.4 source, `acceptance-m2-increment-*.md`.
**Predecessor:** M2.4 VERIFIED (canonical 270 passed; schema v4; HEAD 3a2bae0).
**Next increments:** M2.6 retention/tombstones, M2.7 final acceptance.

---

## 1. Objective and non-goals

M2.5 adds **deterministic relational indexes** (migration v5) and the **FTS5 full-text index**
over *approved sanitized content only*, plus **minimal exact-key inspection helpers**. All indexes
are derived from JSONL; FTS text is the already-sanitized envelope content (M1 redaction is
fail-closed, so stored FTS text carries no raw secrets). Indexes/FTS are fully rebuildable via
`rebuild_from_jsonl`.

Scope:
- migration v5: `CREATE INDEX` on `zm_meta` (`trace_id`, `lifecycle_status`, `verification_status`,
  `project_id`, `profile_id`, `created_at`), `zm_relations` (`from_event_id`, `to_event_id`),
  `zm_lifecycle` (`active_key`, `current_state`), `zm_scopes` (`scope_type`, `scope_id`).
- `zm_fts` (FTS5 virtual table `rowid, event_id, content`) populated on `new_event` with the
  **sanitized** content text (never raw payload). Created only when FTS5 is available.
- FTS5 capability detection: attempt `CREATE VIRTUAL TABLE ... USING fts5`; on `OperationalError`,
  record `FTS5_AVAILABLE=False`, skip `zm_fts`, and make `search_fts` a safe no-op returning `[]`.
- Inspection helpers (exact-key, no ranking/scoring): `search_fts`, `find_related`, `find_by_trace_id`,
  `list_events_in_scope`.
- Rebuild parity extended to include FTS row sets (when FTS available).

**Non-goals (explicitly excluded):**
- Semantic search, vectors, embedding, retrieval ranking, scoring, top-k selection: **never in M2**
  (M3+). `search_fts` returns candidate event_ids only; no relevance ordering is produced or trusted.
- Retrieval/query routing/context injection: M3.
- Retention tombstones: **M2.6**.
- Modifying `zm_meta` to store raw payload text: prohibited (secret guarantee from M2.2 stands).

---

## 2. FTS5 content safety

- The FTS `content` column is populated from the envelope's `sanitized_content` — the **already
  redacted** payload produced by M1's fail-closed redactor. Raw secrets are replaced with
  `[REDACTED:...]` before the JSONL is written, so what reaches FTS cannot carry a raw secret.
- `scan_sqlite_for_secrets` is extended to cover `zm_fts` (so any accidental leakage is caught).
- FTS5 stores an *index*, not the system of record; it is derivable and rebuildable. If FTS5 is
  unavailable, the table is omitted and the system still functions (safe fallback).

---

## 3. Schema (migration v5, additive over v4)

```sql
-- relational indexes (no data; rebuildable automatically)
CREATE INDEX IF NOT EXISTS idx_zm_meta_trace       ON zm_meta(trace_id);
CREATE INDEX IF NOT EXISTS idx_zm_meta_lifecycle   ON zm_meta(lifecycle_status);
CREATE INDEX IF NOT EXISTS idx_zm_meta_verif       ON zm_meta(verification_status);
CREATE INDEX IF NOT EXISTS idx_zm_meta_project     ON zm_meta(project_id);
CREATE INDEX IF NOT EXISTS idx_zm_meta_profile     ON zm_meta(profile_id);
CREATE INDEX IF NOT EXISTS idx_zm_meta_created     ON zm_meta(created_at);
CREATE INDEX IF NOT EXISTS idx_zm_relations_from   ON zm_relations(from_event_id);
CREATE INDEX IF NOT EXISTS idx_zm_relations_to     ON zm_relations(to_event_id);
CREATE INDEX IF NOT EXISTS idx_zm_lifecycle_key    ON zm_lifecycle(active_key);
CREATE INDEX IF NOT EXISTS idx_zm_lifecycle_state  ON zm_lifecycle(current_state);
CREATE INDEX IF NOT EXISTS idx_zm_scopes_type      ON zm_scopes(scope_type, scope_id);
```

`zm_fts` (only if FTS5 available):
```sql
CREATE VIRTUAL TABLE zm_fts USING fts5(event_id UNINDEXED, content);
```
`CURRENT_SCHEMA_VERSION` becomes **5**.

---

## 4. FTS5 capability detection

`migrate_5.up` tries the FTS5 `CREATE VIRTUAL TABLE`; on `sqlite3.OperationalError`, it sets a
module-level flag `FTS5_AVAILABLE = False`, skips `zm_fts`, and logs a sanitized diagnostic. All
FTS helpers check `FTS5_AVAILABLE` and return safe empty results when unavailable. Because indexes
are the only mandatory v5 artifact, migration v5 still succeeds (idempotent) even without FTS5.

---

## 5. Index population / rebuild

- Relational indexes require no population (they are maintained automatically by SQLite over the
  data). They exist after `ensure_schema()`.
- FTS rows are inserted inside the per-line new-event transaction (`_seed_fts` called alongside
  `_project_relations_scopes`). Because `rebuild_from_jsonl` re-runs `ingest_file`, FTS is
  repopulated on rebuild deterministically.
- `verify_rebuild_parity` gains an FTS row-set comparison (when FTS available; skipped when not).

---

## 6. Inspection helpers (exact-key, no ranking)

- `search_fts(store, query, limit=20) -> list[dict]`: runs `MATCH` over `zm_fts`, returns
  `[{event_id, snippet}]` (snippet is FTS highlight, not raw payload). Empty when FTS unavailable.
  No relevance score is exposed or trusted.
- `find_related(store, event_id) -> list[str]`: returns event_ids reachable via `zm_relations`
  (both directions), exact-key.
- `find_by_trace_id(store, trace_id) -> list[dict]`: returns zm_meta rows for a trace.
- `list_events_in_scope(store, scope_type, scope_id) -> list[str]`: event_ids whose zm_meta
  `project_id`/`profile_id` equals scope_id (scope_type decides the column); exact-key.

These are read-only, deterministic, and never perform retrieval/ranking.

---

## 7. Transaction and crash safety

FTS insert occurs in the same per-line transaction as zm_meta insert (new_event). A simulated
commit failure rolls back the entire line (meta + projections + FTS). Resume/rebuild reconstructs.

---

## 8. Migrations and downgrade

- `migrate_5.up`: create indexes (+ `zm_fts` if available). `down`: drop indexes + `zm_fts`.
- `downgrade_to(4)` returns to v4 (M2.4 state). Indexes are dropped; data preserved.
- Failed v5 migration rolls back, version does not advance. Unknown-future DB rejected.

---

## 9. Files and tests

- `src/storage/migrations/migrate_5.py` (new).
- `src/storage/migrations/__init__.py` (modified) — register `migrate_5`; `CURRENT_SCHEMA_VERSION=5`.
- `src/storage/ingest.py` (modified) — `_seed_fts` on new_event; `FTS5_AVAILABLE` flag; helpers
  `search_fts`, `find_related`, `find_by_trace_id`, `list_events_in_scope`; extend
  `verify_rebuild_parity` (FTS parity); extend `scan_sqlite_for_secrets` (zm_fts); update docstring.
- `tests/unit/test_m2_indexes.py` (new) — focused M2.5 tests.
- `acceptance-m2-increment-5.md` (new).

### Focused tests
- migration v4->v5 applies; relational indexes exist; downgrade v5->v4 drops indexes.
- FTS5 capability detection: when available, `zm_fts` created and populated; when unavailable
  (simulated by patching `FTS5_AVAILABLE`/sqlite), `search_fts` returns `[]` and no `zm_fts`.
- FTS indexes only sanitized content; `search_fts` returns the right event_id for a clean query.
- relational indexes improve nothing observable but exist (smoke: query uses index path / no error).
- inspection helpers: `find_related` (both directions), `find_by_trace_id`, `list_events_in_scope`.
- rebuild parity includes FTS row set (when available).
- secret scan clean (covers zm_fts); JSONL immutable; no real `~/.hermes`; no LLM/network.
- no later-M2 tables (zm_tombstone absent); no retrieval/ranking/scoring APIs.
- canonical no-regression (270 → N passed), accounting for the pre-existing M1 flake being
  deselected.

---

## 10. Rollback / runbook

`store.downgrade_to(4)` drops indexes + FTS; re-derive via `rebuild_from_jsonl`.

---

## 11. Objective acceptance criteria

1. Relational indexes created by migration v5; `CURRENT_SCHEMA_VERSION == 5`.
2. FTS5 detected when available; `zm_fts` created and populated with sanitized content only.
3. Safe fallback when FTS5 unavailable: no `zm_fts`; `search_fts` returns `[]`; migration still succeeds.
4. Inspection helpers are exact-key, deterministic, read-only; no ranking/scoring exposed.
5. Rebuild repopulates FTS; parity includes FTS row set (when available).
6. Secret scan clean (covers zm_fts); JSONL immutable; no real `~/.hermes`; no LLM/network.
7. No later-M2 tables/behavior (zm_tombstone absent; no retrieval/ranking/routing/MCP/Obsidian/injection).
8. Migration downgrade v5->v4 drops indexes+FTS; unknown-future rejected.
9. Canonical suite passes with no regression.

---

## 12. Self-review against master M2 plan

- Covers master §3.7 (zm_fts FTS5 over sanitized content), §10.1 (index only approved sanitized
  content), §10.2 (deterministic index migrations, rebuildable), §12 M2.5 (relational indexes,
  FTS5 capability detection, rebuildable population, index parity, minimal inspection helpers, safe
  FTS5-unavailable fallback): ✓.
- Does NOT do semantic search/vectors/ranking/scoring/retrieval selection/query routing/injection
  (excluded per §12 and M2 global rules): ✓.
- FTS content safety consistent with M2.2 secret guarantee (sanitized content only): ✓.
- No new product decision required; within approved M2 architecture: ✓.

---

## 13. Implementation sequence (within M2.5)

1. Write `migrate_5.py` (+ `FTS5_AVAILABLE` detection); register in `__init__.py` (bumps to 5).
2. Extend `ingest.py`: `_seed_fts` on new_event; helpers `search_fts`/`find_related`/
   `find_by_trace_id`/`list_events_in_scope`; extend `verify_rebuild_parity` + secret scanner;
   update docstring.
3. Write `tests/unit/test_m2_indexes.py`.
4. Run focused M2.5 tests, then `pytest tests/ -q` (canonical; deselect the pre-existing M1 flake).
5. Ad-hoc verifier (temp dirs): indexes/FTS, safe fallback, secret clean, no real `~/.hermes`.
6. Write `acceptance-m2-increment-5.md`.
7. Commit impl+tests+evidence; bind `project-state.yaml` + `implementation-plan.json`; commit state.
8. Clean working tree before M2.6.
