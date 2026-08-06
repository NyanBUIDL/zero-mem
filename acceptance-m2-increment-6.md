# M2 Increment 6 Acceptance Evidence

**Increment:** M2.6 — Retention tombstones, logical deletion, secret scanning, and rollback
**Status:** VERIFIED (Decision B — logical deletion only)
**M2 plan:** APPROVED (`dac2f91930fff6b2f1164e3df2...`), M2.6 plan file `.hermes/plans/2026-08-06_000000-m2-6-retention-tombstones-deletion-secret-scan-rollback.md`
**Plan checkpoint:** `28030c4` (approved plan only)
**Predecessor:** M2.5 VERIFIED (HEAD `6af8f4e`, canonical 283 passed).

## Decision B (final)

- Logical deletion only. Canonical JSONL remains **immutable and append-only**.
- M2.6 does **not** physically delete, rewrite, truncate, or compact canonical JSONL.
- Deletion is represented by an explicit append-only **deletion event** (envelope with
  `lifecycle_status='deleted'` + `deletion` block). SQLite projects that into `zm_tombstones`,
  `zm_deletion_audit`, lifecycle state, active indexes, and FTS.
- Deleted records are excluded from active helpers/FTS; only administrative helpers
  (`list_deleted`/`get_tombstone`/`get_deletion_audit`) retrieve them.
- Rebuild from canonical JSONL reproduces the deleted state exactly.
- Physical purge of canonical JSONL is deferred to a separate future milestone (explicit policy
  required: authorization, compliance, backups, audit retention, key destruction, rebuild
  implications, irreversible-deletion confirmation).

## Scope (objective acceptance criteria → evidence)

| # | Criterion | Evidence |
|---|-----------|----------|
| 1 | Migration v5→v6; `CURRENT_SCHEMA_VERSION == 6`; new tables `zm_tombstones`, `zm_deletion_audit` + indexes | `test_migration_v5_to_v6`, `migrate_6.py` (`up`/`down`), `__init__.py` registers v6 |
| 2 | v6→v5 downgrade drops tombstone tables; no partial advance | `test_downgrade_v6_to_v5_drops_tombstone_tables` |
| 3 | Reopen schema v6 idempotent; unknown-future rejected; transaction rollback no partial advance | `test_reopen_schema_v6_idempotent`, `test_migration_rollback_on_failure_no_partial_advance`, M2.1 `test_unknown_future_schema_version_rejected` (now v7) |
| 4 | Deletion event contract validated (target required when `deletion` present; rejected on non-deleted) | `test_validate_envelope_accepts_deletion_block`, `test_validate_envelope_rejects_deletion_without_target`, `test_validate_envelope_rejects_deletion_block_on_non_deleted` |
| 5 | Known-target tombstone: applied; prior state preserved; target `current_state='deleted'` | `test_known_target_tombstone_applied` |
| 6 | active/archived/superseded/conflicted → deleted (prior state retained in audit) | `test_active_to_deleted`, `test_archived_to_deleted`, `test_superseded_to_deleted`, `test_conflicted_to_deleted` |
| 7 | Duplicate `deletion_event_id` idempotent (no double tombstone / inconsistent state) | `test_duplicate_deletion_event_idempotent`, `test_repeated_tombstone_idempotent` |
| 8 | Unknown target → `pending_unknown_target`; no invented relationship; applied when target arrives | `test_unknown_target_tombstone_pending`, `test_pending_unknown_target_retained`, `test_target_arriving_after_tombstone` |
| 9 | Out-of-order rebuild; incremental == rebuilt; repeated rebuild deterministic | `test_out_of_order_tombstone_rebuild`, `test_incremental_vs_rebuild_parity`, `test_repeated_rebuild_determinism` |
| 10 | Deleted excluded from active helpers (`find_by_trace_id`/`list_events_in_scope`/FTS); admin helpers expose them | `test_deleted_excluded_from_active_inspection`, `test_deleted_excluded_from_fts`, `test_admin_helpers_expose_deleted` |
| 11 | Historical metadata/provenance retained after delete | `test_historical_metadata_retained_after_delete` |
| 12 | Retention values projected without invented expiry; no scheduler | `test_retention_values_projected_no_expiry`, `test_no_scheduler_exists` |
| 13 | Secret scan covers `zm_tombstones` + `zm_deletion_audit`; benign ingestion clean; diagnostics sanitized; no raw payload/replayable input in audit | `test_secret_scan_covers_tombstones`, `test_secret_scan_covers_deletion_audit`, `test_secret_absent_normal_ingestion`, `test_deletion_diagnostics_sanitized`, `test_no_secret_in_deletion_audit_log` |
| 14 | JSONL byte-for-byte unchanged | `test_jsonl_byte_for_byte_unchanged` |
| 15 | No real `~/.hermes` writes; no LLM/network; no M2.7/M3 behavior; no physical purge | `test_no_real_hermes_home_writes`, `test_no_llm_or_network_calls`, `test_no_later_m2_tables_or_behavior`, `test_no_physical_purge_behavior` |

## Test evidence

- **Focused M2.6** (`tests/unit/test_m2_tombstones.py`): **35 passed** (all green; FTS5 available on this build so FTS-exclusion tests ran and passed).
- **Canonical suite** (`pytest tests/ -q`): **318 passed, 3 skipped** (normal run, fully green; the 3 skips are the FTS5-unavailable capability branches). Note canonical grew from 283 → 318 (+35 focused M2.6 tests).
- Sanctioned version-tracking test updates (not product defects): `test_m2_indexes.py`, `test_m2_sqlite_foundation.py`, `test_m2_relations.py`, `test_m2_rebuild.py` updated from hard-coded `== 5` to `CURRENT_SCHEMA_VERSION`/range (now 6).

## Real ~/.hermes write test — exact method

`test_no_real_hermes_home_writes` is baseline-aware: capture exact real `~/.hermes` entry set, run
ingest into an **explicitly temp** store (never real home), set isolated `HERMES_HOME`, then assert
real `~/.hermes` unchanged — excluding only the specific unrelated sidecars `kanban.db-wal`/
`kanban.db-shm`. The M2.6 store path is under `tmp_path`, so the code never resolves to real home.

## Known issue (NOT an M2.6 defect — pre-existing M1 flake, logged for separate maintenance)

`tests/unit/test_hermes_payload_fixtures.py::test_mapping_is_deterministic` (M1) is intermittently
flaky (`redaction_audit.observed_at = datetime.now()` per call; `src/redaction/redactor.py:60`).
Present before M2.6 and **untouched** by this increment (working tree does not modify `redactor.py`).
M2.7 final acceptance must run the complete suite without deselecting after the separate M1
maintenance fix is committed. Reported separately; not relabeled as a pass.

## Files

- `src/storage/migrations/migrate_6.py` (new) — v6 `zm_tombstones` + `zm_deletion_audit` DDL, indexes, capability-safe `up`/`down`.
- `src/storage/migrations/__init__.py` (modified) — register v6; `CURRENT_SCHEMA_VERSION=6`.
- `src/storage/ingest.py` (modified) — `_apply_tombstone` / `_apply_pending_tombstones` (tombstone projection, pending-apply, FTS row removal, capability-guarded); active-helper exclusion (`find_by_trace_id`/`list_events_in_scope`); admin helpers `list_deleted`/`get_tombstone`/`get_deletion_audit`; secret scanner extended to `zm_tombstones`+`zm_deletion_audit`; `verify_rebuild_parity` extended (tombstones + audit); `DERIVED_TABLES` extended; docstring updated.
- `src/capture/validation.py` (modified) — accept `deletion` block; require `target_event_id` only when a `deletion` block is present; reject `deletion` on non-deleted events; plain `deleted` lifecycle still ingestible.
- `tests/unit/test_m2_tombstones.py` (new) — 35 focused M2.6 tests.
- Sanctioned version-tracking updates: `tests/unit/test_m2_indexes.py`, `test_m2_sqlite_foundation.py`, `test_m2_relations.py`, `test_m2_rebuild.py`.

## Schema version: 6. Verification of physical-purge non-implementation

Decision B prohibits physical deletion/reordering/rewriting of canonical JSONL. Verified by:
- No code path in M2.6 opens, truncates, rewrites, compacts, or reorders the canonical JSONL file.
- `ingest_file`/`rebuild_from_jsonl` only **read** JSONL; `test_jsonl_byte_for_byte_unchanged` asserts the file is unmodified.
- `test_no_physical_purge_behavior` asserts no `physical_purge`/`purge_canonical_jsonl`/`compact_jsonl` entry points exist.
- Rollback is `store.downgrade_to(5)` (drops derived tombstone tables) + `rebuild_from_jsonl` (re-derives from unchanged JSONL). JSONL is never touched.

## Git evidence

- Plan checkpoint commit: `28030c4`
- Implementation + tests + acceptance commit: <this commit>
- Schema version: 6. Derived tombstone/audit indexes rebuildable via `rebuild_from_jsonl`.

## Rollback / runbook

`store.downgrade_to(5)` drops `zm_tombstones` + `zm_deletion_audit` and their indexes; re-derive the
derived layer from canonical JSONL via `rebuild_from_jsonl` (canonical JSONL is the system of record
and is never modified). Historical provenance survives because the deletion events remain in the
canonical JSONL.
