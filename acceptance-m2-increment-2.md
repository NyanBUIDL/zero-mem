# M2 Increment 2 Acceptance Evidence

**Increment:** M2.2 — Idempotent JSONL metadata ingestion
**Status:** VERIFIED
**M2 plan:** APPROVED (commit `dac2f91930fff6b2f1164e3df2b9108802e29d9b`)
**M2.2 plan:** APPROVED (commit `5c0a13df0659fd0f03bb2d4be5d354d87edd0e2c`)
**Starting commit:** `f6f010cdb75257bc51ff60cb83ec58092f53af7d`
**Plan checkpoint commit:** `5c0a13df0659fd0f03bb2d4be5d354d87edd0e2c`
**Implementation commit:** PENDING_IMPL_COMMIT
**Tested commit:** PENDING_TESTED_COMMIT

## Scope (approved M2.2 plan)

Deterministic, idempotent ingestion of canonical M1 JSONL event records into the
derived SQLite metadata layer (`zm_meta`), with resumable checkpoints
(`zm_ingest_checkpoint`) and a committed sanitized ingest log (`zm_ingest_log`).
JSONL remains authoritative; SQLite is derived, disposable, rebuildable, and
cannot modify JSONL.

Implemented exactly this scope. No lifecycle/provenance/relation/scope projection,
no FTS5 indexing, no retention tombstones, no retry/backoff, no dead-letter store
or replay, no retrieval/ranking/routing, no MCP/Obsidian/context injection, no M2.3+.

## Files changed (product code)

- `src/storage/ingest.py` (new) — `JsonlEventSource` (read-only line reader preserving
  exact bytes), `IngestionOutcome`, `IngestionFailure`, `IngestionReport`, `ingest_file`,
  `get_trace`, `count_metadata`, `get_checkpoint`, `scan_sqlite_for_secrets`,
  consumed-prefix hashing (`PrefixHasher` / `_compute_prefix_hash`).
- `src/storage/migrations/migrate_2.py` (new) — v2 DDL: `zm_ingest_checkpoint`
  (with `consumed_prefix_hash`) and `zm_ingest_log`; `down` drops both.
- `src/storage/migrations/__init__.py` (modified) — register `migrate_2`;
  `CURRENT_SCHEMA_VERSION` auto-bumps to 2.
- `tests/unit/test_m2_ingest.py` (new) — 36 focused M2.2 tests.

Files updated for the v2 schema bump (sanctioned test-contract update, no product
code defect): `tests/unit/test_m2_sqlite_foundation.py` (8 assertions now track
`CURRENT_SCHEMA_VERSION == 2`; future-version simulation uses v3; downgrade test
reflects current=2).

## Required rules satisfied

1. JSONL canonical/authoritative; SQLite derived only (ingest reads, never writes JSONL).
2. M2.2 ingests only approved derived metadata; `sanitized_content` blob is NOT stored.
3. Idempotent by `event_id` and `sanitized_content_hash`; re-runs add no duplicates.
4. Exact outcomes implemented: `new_event`, `duplicate_event_id`, `duplicate_content_hash`,
   `event_id_content_conflict`, `invalid_record`, `transaction_failed`, `source_changed`.
5. `event_id_content_conflict` = first-write-wins; original row kept; never overwritten.
6. Per-record atomic transaction (zm_meta insert / zm_ingest_log insert / checkpoint update).
7. Checkpoint advances ONLY after a committed outcome; `transaction_failed` and
   crash-before-commit do NOT advance it; crash-after-commit checkpoint already reflects line.
8. Append-safe via consumed-prefix hash (sha256 over exact bytes of lines 1..last_line);
   normal growth / mtime change / size-from-append allowed; consumed-prefix modification,
   reordering, replacement, and truncation-below-checkpoint are rejected (`source_changed`).
9. NO `basename|size|mtime_ns` fingerprint.
10. Malformed/invalid lines reported with only safe fields (source id, line, class, code);
    no payload/secret/exception text; `zm_ingest_log` is a committed sanitized record,
    NOT a dead-letter store and NOT replayed. No retry/backoff/replay queues.
11. Secret safety: synthetic secrets absent from `zm_meta`, `zm_ingest_log`, reports,
    diagnostics; `scan_sqlite_for_secrets` returns empty.
12. Source immutability: JSONL bytes, order, and caller dicts are unchanged by ingestion.
13. Minimal read-only helpers only (`get_trace`, `count_metadata`, `get_checkpoint`);
    no ranking/scoring/retrieval/semantic-search/routing/FTS.
14. Tests use temporary directories; nothing written to real `~/.hermes`.
15. Installed Hermes source unmodified (guard refuses paths under `~/.hermes`).
16. No LLM or network calls (socket-patch tests pass; no openai/anthropic imported).
17. No later-M2 tables/behavior present.

## Environment

- SQLite 3.53.1 (Python 3.11.15); WAL, `foreign_keys=ON`, `synchronous=NORMAL`, `busy_timeout=5000ms`.
- Schema version: 2.

## zm_meta columns (exact projection)

event_id, trace_id, event_type, source, schema_version, created_at, observed_at,
sequence, session_id, profile_id, project_id, task_id, turn_id, parent_trace_id,
lifecycle_status, verification_status, confidence, sensitivity, retention,
content_hash (= envelope `sanitized_content_hash`), redaction_applied, ingested_at,
origin_jsonl (safe basename). No `sanitized_content`.

## Test results

- Focused M2.2 (`tests/unit/test_m2_ingest.py`): **36 passed**.
- Canonical (`tests/`): **227 passed** (no regression vs 191 prior).
- Ad-hoc (temp `hermes-verify-` dirs, cleaned): ingested 1 event; SECRET_IN_DB=[];
  schema=2; real `~/.hermes` unchanged (67,738 entries before/after identical); exit 0.

## Acceptance criteria mapping (plan §21, 23 rows)

| # | Criterion | Test |
|---|-----------|------|
| 1 | Read-only JSONL, never mutates | `test_jsonl_byte_for_byte_unchanged`, `test_no_real_hermes_home_writes` |
| 2 | Validates via `validate_envelope` | `test_envelope_validation_rejects_invalid`, `test_invalid_envelope_handling` |
| 3 | Only derived metadata (no blob) | `test_approved_metadata_projection`, `test_sanitized_content_blob_excluded` |
| 4 | Idempotent by event_id | `test_duplicate_event_id`, `test_idempotent_rerun_no_duplicates` |
| 5 | Idempotent by content_hash | `test_duplicate_content_hash` |
| 6 | conflict keeps original | `test_event_id_content_conflict_first_write_wins` |
| 7 | new_event committed | `test_valid_new_event_ingestion` |
| 8 | duplicate_event_id skipped | `test_duplicate_event_id` |
| 9 | Per-record transaction | `test_per_record_transaction_isolation` |
| 10 | Deterministic file order | `test_deterministic_file_order_ingestion` |
| 11 | Resumable checkpoint | `test_checkpoint_advances_for_committed_outcomes`, resume tests |
| 12 | Advance only after committed | `test_checkpoint_advances_for_committed_outcomes` |
| 13 | Crash/resume no dup/loss | `test_crash_before_commit_resume_retries`, `test_crash_after_commit_resume_idempotent` |
| 14 | Sanitized malformed report | `test_sanitized_failure_records_no_payload` |
| 15 | Continues after malformed | `test_continuation_after_invalid_lines` |
| 16 | Truncation guard | `test_trailing_partial_line_is_truncation_guard`, `test_truncation_below_checkpoint_rejected` |
| 17 | Append-safe integrity | `test_normal_append_growth_accepted`, `test_mtime_only_change_accepted` |
| 18 | Consumed-prefix tamper rejected | `test_consumed_prefix_modification_rejected`, `test_consumed_line_reordering_rejected`, `test_consumed_prefix_replacement_rejected` |
| 19 | No invented identity | `test_no_invented_identity` |
| 20 | Secret scan clean | `test_secret_absent_from_sqlite_and_outputs` (+ ad-hoc) |
| 21 | SQLite rebuildable | idempotent re-run (`test_idempotent_rerun_no_duplicates`); full rebuild deferred to M2.3 |
| 22 | No JSONL mutation/LLM/network | `test_jsonl_byte_for_byte_unchanged`, `test_no_llm_or_network_calls` |
| 23 | Sanitized errors only | `test_sanitized_failure_records_no_payload`, `test_sanitized_migration_error_no_leak` |

## Proof of no later-M2 behavior

- `SQLiteStore` / `ingest.py` expose no lifecycle/provenance/relations/scopes/FTS/rebuild/
  replay/dead-letter methods; `test_no_later_m2_behavior` asserts those tables are absent.
- Module import graph does not load retrieval/routing/MCP/Obsidian.
- Commit diff limited to `src/storage/ingest.py`, `migrate_2.py`, registry bump, tests.

## Migration (v1 -> v2)

- `ensure_schema` applies v2 after v1 (deterministic ascending order, transactional).
- `downgrade_to(1)` drops `zm_ingest_checkpoint`/`zm_ingest_log`, returns to v1 (zm_meta kept).
- Reopening an upgraded DB is idempotent (`test_reopening_up_to_date_database_is_noop`).
- Failed migration rolls back; unknown-future version (db > code) refused.

## Next

M2.3 — Lifecycle, verification, supersession, and rebuild projection. Not started.
