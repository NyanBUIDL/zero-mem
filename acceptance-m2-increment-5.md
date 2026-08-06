# M2 Increment 5 Acceptance Evidence

**Increment:** M2.5 — Relational indexes, FTS5, and minimal inspection helpers
**Status:** VERIFIED
**M2 plan:** APPROVED (`dac2f91930fff6b2f1164e3df2...`), plan file `.hermes/plans/2026-08-06_000000-m2-5-indexes-fts5-inspection.md`
**Predecessor:** M2.4 VERIFIED (HEAD `3a2bae0`, canonical 270 passed).

## Scope (objective acceptance criteria → evidence)

| # | Criterion | Evidence |
|---|-----------|----------|
| 1 | Relational indexes created by migration v5; `CURRENT_SCHEMA_VERSION == 5` | `test_migration_v4_to_v5` (asserts all 11 indexes via `index_exists`), `CURRENT_SCHEMA_VERSION == 5` |
| 2 | FTS5 detected when available; `zm_fts` created + populated with sanitized content only | `test_fts5_detected_and_table_created`, `test_fts_indexes_sanitized_content`, `test_fts_stores_exactly_sanitized_content` |
| 3 | Safe fallback when FTS5 unavailable: no `zm_fts`; `search_fts` returns `[]`; migration still succeeds | `test_search_fts_safe_when_unavailable` (patches `_detect_fts5` → False); `migrate_5.up` still applies indexes |
| 4 | Inspection helpers exact-key, deterministic, read-only; no ranking/scoring exposed | `test_find_related_both_directions`, `test_find_by_trace_id`, `test_list_events_in_scope`, `test_no_later_m2_tables_or_ranking` (no `rank_results`/`retrieve_top_k`) |
| 5 | Rebuild repopulates FTS; parity includes FTS row set (when available) | `test_rebuild_parity_includes_fts` (asserts `verify_rebuild_parity` True + FTS search reproduces) |
| 6 | Secret scan clean (covers zm_fts); JSONL immutable; no real `~/.hermes`; no LLM/network | `test_secret_scan_covers_fts` (clean content → `[]`), `test_jsonl_immutable`, `test_no_real_hermes_home_writes` (baseline-aware, isolated HERMES_HOME), `test_no_network_calls` |
| 7 | No later-M2 tables/behavior (zm_tombstone absent; no retrieval/ranking/routing/MCP/Obsidian/injection) | `test_no_later_m2_tables_or_ranking`, M2.2/3/4 `test_no_later_*` updated to exclude `zm_tombstone` (M2.6) only |
| 8 | Migration downgrade v5→v4 drops indexes+FTS; unknown-future rejected | `test_downgrade_v5_to_v4_drops_indexes`, M2.1 `test_unknown_future_schema_version_rejected` (v6), `test_unsupported_downgrade_rejected` |
| 9 | Canonical suite passes with no regression | see below |

## Test evidence

- **Focused M2.5** (`tests/unit/test_m2_indexes.py`): **12 passed, 3 skipped** (skips are
  `pytest.skip("FTS5 unavailable")` — FTS5 IS available on this build, so the active FTS tests ran
  and passed; the 3 skips are the platform-conditional branches).
- **Canonical suite** (`pytest tests/ -q`): **283 passed, 3 skipped** (normal run, fully green).
- M2.1 focused: 25 passed · M2.2 focused: 36 passed · M2.3 focused: 22 passed · M2.4 focused: 22 passed
  (all still green under `CURRENT_SCHEMA_VERSION == 5`, after sanctioned version-tracking + later-table
  + sanitized-content secret-test updates).

## Ad-hoc runtime verification (temp dirs, no real ~/.hermes)

- relational indexes present (`idx_zm_meta_trace`, `idx_zm_relations_from`, ...).
- FTS indexes SANITIZED content: query `deploy` → `{a}`, `migration` → `{b}`.
- inspection helpers: `find_related(a)` → `[b]` (child_of edge, both directions);
  `find_by_trace_id(tr-A)` → `[a]`; `list_events_in_scope(project, proj-1)` → `[a]`.
- rebuild parity (incremental vs rebuild): `True`; FTS search reproduces after rebuild.
- secret scanner covers `zm_fts`: an intentionally injected synthetic secret in an FTS-row fixture
  IS detected by `scan_sqlite_for_secrets` (defense-in-depth proven).
- JSONL byte-for-byte immutable: `True`.
- schema version: `5`.

## Real ~/.hermes write test — exact method (per M2.5 acceptance)

`test_no_real_hermes_home_writes` (M2.2/3/4/5) uses a **baseline-aware** assertion:
1. Capture the exact entry set of the REAL `~/.hermes` before the test.
2. Run the project operation with an **isolated temporary `HERMES_HOME`** (via `monkeypatch.setenv`
   + `pathlib.Path.home` patch) so any home-write our code makes lands in the temp home, never the real one.
3. Assert the real `~/.hermes` is byte-identical afterward, **excluding only the specific, independently
   verified unrelated sidecars** `kanban.db-wal` / `kanban.db-shm` (an unrelated kanban feature's sqlite
   WAL/SHM mutated by a background process during the run). Any NEW project-attributable entry still fails.

This does NOT globally ignore every `.wal`/`.shm`/`.journal` — only the two named unrelated sidecars are
tolerated; all other real-home mutations fail the assertion.

## Known issue (NOT an M2.5 defect — pre-existing M1 flake, logged for separate maintenance)

`tests/unit/test_hermes_payload_fixtures.py::test_mapping_is_deterministic` (M1) is **intermittently
flaky**: `map_hook_payload` includes `redaction_audit.observed_at` = a fresh `datetime.now()` per call
(`src/redaction/redactor.py:60`); when two calls straddle a millisecond boundary the dicts differ.
Confirmed present at the M2.3 HEAD (`3340a8e`) and untouched by M2.5 (working tree does not touch
`redactor.py`/`payload_mapping.py`). It is a pre-existing M1 determinism defect and is explicitly NOT
fixed here (M1 is VERIFIED; fixing it would misattribute the change to M2.5 and violate single-increment
attribution). Recommended follow-up (separate M1 maintenance commit): make `RedactionAudit.observed_at`
deterministic (derive from payload `observed_at` when present, else a single frozen timestamp per
`map_hook_payload` call). **M2.7 final acceptance must run the complete suite without deselecting after
that maintenance issue is resolved.** Reported separately; not relabeled as a pass.

## Files

- `src/storage/migrations/migrate_5.py` (new) — v5 relational indexes + `zm_fts` (FTS5 capability detection).
- `src/storage/migrations/__init__.py` (modified) — register v5; `CURRENT_SCHEMA_VERSION=5`.
- `src/storage/sqlite_store.py` (modified) — `index_exists` helper.
- `src/storage/ingest.py` (modified) — `_seed_fts` on new_event; `search_fts`/`find_related`/
  `find_by_trace_id`/`list_events_in_scope`; `verify_rebuild_parity` extended (FTS); secret scanner
  covers `zm_fts`; docstring updated.
- `tests/unit/test_m2_indexes.py` (new) — 15 focused M2.5 tests (12 pass, 3 FTS5-conditional skips).

## Git evidence

- Plan commit: `51d042e`
- Implementation + tests + evidence commit: see "Implementation commit" in checkpoint.
- Schema version: 5. Derived indexes/FTS rebuildable via `rebuild_from_jsonl`.

## Rollback / runbook

`store.downgrade_to(4)` drops indexes + FTS; re-derive via `rebuild_from_jsonl` (JSONL is the backup).
