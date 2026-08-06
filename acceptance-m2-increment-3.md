# M2 Increment 3 Acceptance Evidence

**Increment:** M2.3 — Lifecycle, verification, supersession, and rebuild projection
**Status:** VERIFIED
**M2 plan:** APPROVED (commit `dac2f91930fff6b2f1164e3df2b9108802e29d9b`)
**M2.3 plan:** APPROVED (commit `c173d501ef9a5a036dc9a472bdf310bdfac81356`)
**Starting commit:** `e5b11c7` (`.gitignore` hygiene over `1e8e299` M2.2 binding)
**Plan commit:** `c173d501ef9a5a036dc9a472bdf310bdfac81356`
**Implementation commit:** PENDING_IMPL
**Tested commit:** PENDING_TESTED

## Scope (approved M2.3 plan)

Derived lifecycle-state projection (`zm_lifecycle`), derived verification/provenance
projection (`zm_provenance`), and `rebuild_from_jsonl()` that reproduces the entire derived
SQLite layer from canonical JSONL. Supersession *links* (zm_relations), active-key
*enforcement*, scopes, FTS5, and retention tombstones are deferred to M2.4/M2.5/M2.6.

Implemented exactly this scope. `zm_lifecycle.superseded_by` / `active_key` columns are
created and seeded `NULL` (their population/enforcement is M2.4). No relations, scopes, FTS5,
retention, retrieval, ranking, routing, MCP, Obsidian, or injection.

## Files changed (product code)

- `src/storage/migrations/migrate_3.py` (new) — v3 DDL: `zm_lifecycle`, `zm_provenance`; `down` drops both.
- `src/storage/migrations/__init__.py` (modified) — register `migrate_3`; `CURRENT_SCHEMA_VERSION` auto-bumps to 3.
- `src/storage/ingest.py` (modified) — seed `zm_lifecycle` + `zm_provenance` on `new_event`
  (same per-line transaction); add `rebuild_from_jsonl`, `get_lifecycle`, `get_provenance`,
  `list_by_lifecycle_state`, `verify_rebuild_parity`; extend `scan_sqlite_for_secrets` to cover
  the new tables; update module docstring.
- `tests/unit/test_m2_rebuild.py` (new) — 22 focused M2.3 tests.
- M2.1/M2.2 test assertions updated to track `CURRENT_SCHEMA_VERSION == 3` (no product-code defect).

## Required rules satisfied

1. SQLite derived, disposable, rebuildable; JSONL authoritative/immutable.
2. Lifecycle projection mirrors `lifecycle_status`; `conflicted`/`archived`/`deleted` stored verbatim.
3. Provenance projection seeds exactly one row per event: `verifier='deterministic_check'`,
   `verification_status` from envelope, `evidence_ref=trace_id`; verifier-rank stored as data only.
4. Idempotence: duplicate `event_id`/`content_hash` and conflicts add no lifecycle/provenance rows; original kept.
5. `rebuild_from_jsonl` reproduces identical `zm_meta`+`zm_lifecycle`+`zm_provenance` key sets and
   states vs incremental ingest (parity verified); deterministic repeated rebuild identical.
6. Malformed JSONL lines during rebuild are sanitized `invalid_record` and ingestion continues.
7. Crash safety: a simulated per-line commit failure rolls back the entire line (zm_meta + lifecycle
   + provenance); no partial row; resume/rebuild reconstructs cleanly.
8. Migration v3->v2 drops the new tables; unknown-future version (db > code) rejected; downgrade to
   >= current rejected; downgrade to 2 succeeds.
9. Secret scan clean across zm_meta/zm_lifecycle/zm_provenance/zm_ingest_log.
10. JSONL byte-for-byte immutable; no real `~/.hermes` writes; no LLM/network calls.
11. No later-M2 tables/behavior (zm_relations/zm_scopes/zm_fts/zm_artifacts absent; no replay/dead-letter).

## Environment

- SQLite 3.53.1 (Python 3.11.15); WAL, `foreign_keys=ON`, `synchronous=NORMAL`, `busy_timeout=5000ms`.
- Schema version: 3.

## Test results

- Focused M2.3 (`tests/unit/test_m2_rebuild.py`): **22 passed**.
- Focused M2.2 (`tests/unit/test_m2_ingest.py`): **36 passed** (assertions updated to v3).
- Focused M2.1 (`tests/unit/test_m2_sqlite_foundation.py`): **25 passed** (assertions updated to v3).
- Canonical (`tests/`): **249 passed** (no regression vs 227 prior).
- Ad-hoc (temp `hermes-verify-` dirs, cleaned): parity=True, schema=3, secret_clean, JSONL immutable,
  lifecycle+provenance seeded; real `~/.hermes` unchanged (67,763 before/after identical); exit 0.

## Acceptance criteria mapping (plan §9)

| # | Criterion | Test |
|---|-----------|------|
| 1 | v3 tables created; CURRENT_SCHEMA_VERSION==3 | `test_migration_v2_to_v3` |
| 2 | lifecycle mirrors status; conflicted/archived/deleted verbatim | `test_lifecycle_mirrors_envelope`, `test_lifecycle_records_conflicted_archived_deleted` |
| 3 | provenance one row/event; verifier deterministic_check; evidence=trace_id | `test_provenance_seeded_per_event`, `test_provenance_rank_stored_as_data_only` |
| 4 | idempotence; original kept | `test_first_write_seeds_lifecycle_provenance`, `test_duplicate_event_id_no_extra_lifecycle_provenance`, `test_conflict_keeps_original_no_new_lifecycle` |
| 5 | rebuild parity with incremental | `test_rebuild_parity_with_incremental` |
| 6 | deterministic repeated rebuild identical | `test_rebuild_deterministic_repeatable`, `test_rebuild_into_empty_db` |
| 7 | malformed line sanitized + continues | `test_rebuild_malformed_line_sanitized_and_continues`, `test_rebuild_populates_all_projections` |
| 8 | crash roll-back whole line; resume clean | `test_per_line_crash_rolls_back_whole_event` |
| 9 | downgrade v3->v2 drops new tables; future rejected | `test_downgrade_v3_to_v2_drops_new_tables`, `test_reopen_v3_idempotent` (+ M2.1 `test_unknown_future_schema_version_rejected`, `test_unsupported_downgrade_rejected`) |
| 10 | secret scan clean | `test_secret_absent_across_projections` (+ ad-hoc) |
| 11 | JSONL immutable; no ~/.hermes; no LLM/net; no later-M2 | `test_jsonl_byte_for_byte_unchanged`, `test_no_real_hermes_home_writes`, `test_no_network_calls`, `test_no_later_m2_tables_or_behavior` |
| 12 | canonical no regression | `pytest tests/ -q` → 249 passed |

## Lifecycle / provenance design notes

- `current_state` is a direct projection of the envelope `lifecycle_status` (no invented transition
  logic); the envelope remains the source of truth, so incremental ingest and rebuild are identical.
- `verifier='deterministic_check'` reflects that M1 capture is a deterministic local operation
  (no LLM). Verifier-rank ordering is recorded as data only; M2 applies no ranking/scoring/retrieval.
- `superseded_by` / `active_key` are created as `NULL` and intentionally left for M2.4 (supersession
  link creation + active-key uniqueness enforcement), per master M2 plan §12.

## Proof of no later-M2 behavior

- Store exposes no `rebuild_from_jsonl`/`replay`/`dead_letter` method; module-level `rebuild_from_jsonl`
  is M2.3's own deliverable. `zm_relations`/`zm_scopes`/`zm_fts`/`zm_artifacts` are absent.
- Commit diff limited to `migrate_3.py`, registry bump, `ingest.py` (M2.3 additions), tests.

## Migration (v2 -> v3)

- `ensure_schema` applies v3 after v2 (deterministic ascending order, transactional).
- `downgrade_to(2)` drops `zm_lifecycle`/`zm_provenance`, returns to v2 (M2.2 state).
- `rebuild_from_jsonl` drops all derived tables + the `zm_migrations` ledger, then re-applies
  migrations 1->3, fully recreating the derived layer; final schema version is 3.

## Next

M2.4 — Relations and project/profile/knowledge-space mappings. Not started.
