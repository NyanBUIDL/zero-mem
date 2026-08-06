# M2 Final Acceptance Evidence — Full M2 Integration Verification (M2.7)

**Milestone:** M2 (SQLite metadata/state/relations/indexes/tombstones) — final increment M2.7
**Status:** M2 VERIFIED (M2.7 VERIFIED)
**Authority:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` (DOCX authoritative); `implementation-plan.json`; `project-state.yaml`; AGENTS.md.
**Verified starting state (HEAD 96d1e9a):** M0–M2.6 VERIFIED; M2 overall IN PROGRESS; schema v6; canonical 318 passed / 3 skipped; working tree clean; Decision B recorded.

## No new architecture / product behavior

M2.7 is integration verification + final acceptance only. No M2.1–M2.6 redesign. No M3 behavior.
The only non-M2.7 code change is a SEPARATE, narrowly-scoped M1 maintenance fix (timing flake) and
test-robustness hardening for real-home isolation (environmental drift tolerance). See "Maintenance &
test robustness" below.

## Commits (chronological)

| Role | Commit | Note |
|------|--------|------|
| M2.7 plan (plan-only checkpoint) | `61faf29` | approved M2.7 plan |
| M1 maintenance plan | `1d61a05` | separate; deterministic observed_at |
| M1 maintenance fix (product) | `01db767` | removes wall-clock flake in `redactor._utc` |
| M2.7 focused integration tests | `efb0fba` | `tests/unit/test_m2_integration.py` (16 tests) |
| Real-home isolation hardening (tests) | `d03aa7c` | M2.1/2.3/2.6 `test_no_real_hermes_home_writes` |
| Final evidence + state binding | (this commit) | `acceptance-m2-final.md` + state update |

## Required test execution results

1. **Focused M2.7 integration tests** — `tests/unit/test_m2_integration.py`:
   **16 passed** (`pytest tests/unit/test_m2_integration.py -q`).
2. **All M2 focused test files** (M2.1–M2.7): **168 passed, 3 skipped**.
3. **Migration-focused tests** — `tests/unit/test_m2_sqlite_foundation.py`: **25 passed, 3 skipped**.
4. **Complete normal canonical suite** (no deselect):
   `.venv/bin/python -m pytest tests/ -q` → **334 passed, 3 skipped**.
   The 3 skips are FTS5-unavailable capability branches (M2.5/M2.6). No failures.
   Run repeated 6× to confirm stability: 334 passed / 3 skipped every run.

## Acceptance criteria (all passing)

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Clean rebuild from representative corpus | PASS | `test_clean_rebuild_and_incremental_parity` |
| 2 | Incremental vs rebuild parity | PASS | `verify_rebuild_parity(inc, reb) is True` (all derived surfaces) |
| 3 | Deterministic repeated rebuild | PASS | `test_repeated_rebuild_deterministic` (identical state, no dup rows) |
| 4 | Idempotent repeated ingestion | PASS | `test_repeated_ingestion_idempotent` (first-write-wins, identical checkpoints) |
| 5 | Lifecycle + supersession | PASS | `test_lifecycle_states_and_supersession` (raw..deleted; trace_id active-key uniqueness) |
| 6 | Relations/scopes/artifacts | PASS | `test_relations_scopes_artifact_parity` (child_of, derived_from; project/profile; artifact registry) |
| 7 | FTS + indexes | PASS | `test_fts_only_sanitized_and_excludes_deleted` (sanitized-only; deleted excluded; no ranking) |
| 8 | Retention & deletion (Decision B) | PASS | `test_decision_b_logical_deletion_only` (append-only tombstones; no physical JSONL mutation; no scheduler) |
| 9 | Migration path | PASS | `test_migration_path_v1_to_v6_idempotent`, `test_unknown_future_rejected_without_mutation`, `test_failed_migration_no_partial_advance`; v6→v5 downgrade verified in M2.6 |
| 10 | Crash & resume | PASS | `test_crash_before_commit_no_checkpoint_advance`, `test_append_only_growth_resumed_and_prefix_modification_rejected` |
| 11 | Secret safety | PASS | `test_secret_absent_normal_run_and_detected_when_injected` (no secret in normal run; injected detected without printing) |
| 12 | JSONL immutability | PASS | `test_jsonl_byte_for_byte_unchanged` (sha256 + byte count unchanged) |
| 13 | Real ~/.hermes isolation | PASS | `test_no_real_hermes_home_writes` (baseline-aware M2-attributable-file check) |
| 14 | No M3 behavior | PASS | `test_no_m3_behavior` (no ranking/vectors/routing/injection/MCP/Obsidian tables/attrs) |

## Maintenance & test robustness (outside M2 product scope)

- **M1 timing flake** (`tests/unit/test_hermes_payload_fixtures.py::test_mapping_is_deterministic`)
  was the documented intermittent failure (wall-clock `datetime.now()` in `RedactionAudit.observed_at`).
  M2.7 final acceptance requires a complete normal run without deselecting it. Per the agreed
  procedure, a SEPARATE narrowly-scoped M1 maintenance plan (`1d61a05`) and fix (`01db767`) were
  applied: `redactor._utc(None)` now returns a deterministic sentinel instead of wall-clock. Real
  capture paths pass an explicit `observed_at`, so live timestamps are unchanged. Verified: the
  flake test passed 25/25 in a tight loop, and the full canonical suite is now stable.
- **Real-home isolation flakiness** (`test_no_real_hermes_home_writes` in M2.1/2.3/2.6) was
  environmental: the live Hermes desktop app mutates unrelated files in real `~/.hermes` during the
  long suite run. Hardened (`d03aa7c`) to a baseline-aware, M2-attributable-file check: a real
  regression (M2 writing a sqlite/jsonl to real home) is still caught, but unrelated background
  drift is tolerated. This is a test-robustness fix only; no product behavior changed.

## Cleanup

No caches / bytecode / temporary databases / temporary JSONL / temporary verifier scripts remain.
Verification used only `tmp_path` (pytest auto-cleaned) and inline corpus builders. Working tree
clean after the final evidence/state-binding commit.

## Final state

- M0: VERIFIED
- M1: VERIFIED (flake maintenance applied in `01db767`)
- M2.1–M2.6: VERIFIED
- **M2.7: VERIFIED**
- **M2: VERIFIED**
- Schema version: **6**
- M2 focused: **168 passed, 3 skipped**
- Canonical suite: **334 passed, 3 skipped**
- Decision B: recorded and verified (logical deletion only; canonical JSONL immutable)
- M3 NOT started.
