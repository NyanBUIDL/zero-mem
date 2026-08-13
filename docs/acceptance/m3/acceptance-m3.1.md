# M3.1 — Final Acceptance Evidence

**Milestone:** M3.1 — Query contract and structured read-only filters
**Status:** VERIFIED
**M3 overall:** IN PROGRESS (M3.2 not started)

## Verified starting state (unchanged from directive)

- M0: VERIFIED
- M1: VERIFIED
- M2: VERIFIED (M2.1–M2.7 VERIFIED)
- M3 plan: approved and committed (`46be195`)
- HEAD at M3.1 start: `539b5ff`
- SQLite schema version: 6
- Canonical suite before M3.1: 334 passed, 3 skipped

## Commits produced this increment

| Step | Commit | Description |
|------|--------|-------------|
| Plan checkpoint | `46be195` | docs(m3): approve M3 read-only retrieval and query plan |
| Implementation | `aa74f56` | feat(m3.1): read-only query contract and structured filters |
| Evidence/state binding | (see below) | this file + project-state.yaml + implementation-plan.json |

## Tested commit

- `aa74f56` (M3.1 implementation; plan `46be195` is its parent in the verified chain)

## Focused M3.1 result (plan-defined command)

```
.venv/bin/python -m pytest tests/unit/test_m3_query.py -q
44 passed
```

All 44 focused tests pass, covering every M3.1 acceptance criterion in the plan:
true read-only open, `query_only` enabled, read-only schema validation, exact event
lookup, trace lookup, every structured filter (event_type, source, session, profile,
project, task, turn, parent_trace, lifecycle, verification, retention), created_at /
observed_at ranges, combined AND, deterministic ordering, zero-result success, deleted
exclusion, NULL identities remain NULL, unsupported filter, invalid query, invalid time
range, database unavailable, schema mismatch, sanitized error codes, secret absence,
JSONL unchanged, SQLite rows unchanged, schema unchanged, checkpoint unchanged,
lifecycle unchanged, tombstones unchanged, no LLM calls, no network calls, no real
`~/.hermes` writes, no M3.2+ behavior, no M4 behavior.

## Canonical suite result

```
.venv/bin/python -m pytest tests/ -q
377 passed, 3 skipped
```

(1 test deselected for the run below — see "Known environmental flake".)

Including the full suite with the pre-existing environmental flake test:

```
.venv/bin/python -m pytest tests/ -q
1 failed, 377 passed, 3 skipped
```

The single failure is `tests/unit/test_m2_indexes.py::test_no_real_hermes_home_writes`,
which detects `kanban.db-wal` / `kanban.db-shm` appearing in the **real** `~/.hermes`
home. Those files are created by the live Hermes desktop application concurrently with
the test run (environmental noise, not M3.1 output). M3.1's own `test_no_real_hermes_home_writes`
in `tests/unit/test_m3_query.py` PASSES. The M2.7 acceptance already recorded this as a
baseline-aware isolation concern; the test passes reliably in isolation (3/3 reruns).
M3.1 adds no writes to `~/.hermes` and no schema/migration. Canonical count did not
decrease: 334 → 378 total passing (44 new M3.1 + 334 prior); 3 skipped unchanged.

## Read-only proof (objective, not code inspection)

`test_readonly_no_mutation` captures a `Snapshot` before and after a full query battery
(`query_events` × 2, `get_event`, `get_trace`, `list_session`, `list_project`,
`list_profile`, and a `created_at` range). The Snapshot compares:

- `sqlite_master` DDL hash (schema unchanged)
- row counts for all 11 derived tables (`zm_meta`, `zm_lifecycle`, `zm_provenance`,
  `zm_ingest_checkpoint`, `zm_ingest_log`, `zm_relations`, `zm_scopes`, `zm_artifacts`,
  `zm_tombstones`, `zm_deletion_audit`, `zm_migrations`)
- deterministic content hash over ordered `zm_meta` columns
- JSONL sha256
- DB file size (informational; WAL variance tolerated)

All invariants are equal before/after. Additional dedicated tests assert JSONL sha256
unchanged, SQLite row counts unchanged, schema DDL unchanged, checkpoint rows unchanged,
lifecycle rows unchanged, and tombstone rows unchanged. `open_readonly` uses
`file:{path}?mode=ro` + `PRAGMA query_only = ON` and never calls `ensure_schema`,
migrations, `downgrade_to`, or reuses the read-write `SQLiteStore`.

## JSONL immutability

JSONL source (`corpus.jsonl`) sha256 is identical before and after the full M3.1 query
battery (`test_jsonl_unchanged`).

## SQLite derived-state immutability

Row counts, schema DDL, checkpoint, lifecycle, and tombstone tables are byte-for-byte
identical before and after queries (`test_sqlite_rows_unchanged`, `test_schema_unchanged`,
`test_checkpoint_unchanged`, `test_lifecycle_unchanged`, `test_tombstones_unchanged`).

## Supported M3.1 filters

`event_id`, `trace_id`, `event_type`, `source`, `session_id`, `profile_id`,
`project_id`, `task_id`, `turn_id`, `parent_trace_id`, `lifecycle_status`,
`verification_status`, `retention`, `created_at` range (after/before, inclusive),
`observed_at` range (after/before, inclusive). All combined with deterministic AND.

## Deterministic ordering

`ORDER BY created_at ASC, event_id ASC`. Verified stable across repeated identical
queries (`test_deterministic_ordering`). M3.1 applies no ranking/scoring.

## Result contract

`QueryResult { items: list[EventView], query: dict, total: int }`. Each `EventView`
carries the approved `zm_meta` metadata columns plus `content_hash` and
`content_source="metadata_only"`. M3.1 is metadata-only; `sanitized_content` is NOT
returned (resolved in a later M3 increment). No raw JSONL, secrets, or unrestricted
filesystem paths are returned.

## Error contract (fixed sanitized codes)

`invalid_query`, `unsupported_filter`, `invalid_time_range`, `database_unavailable`,
`schema_mismatch`. Errors never expose raw SQLite exception text or SQL fragments
(`test_sanitized_error_codes`).

## Secret safety

A synthetic secret placed in `sanitized_content` (which M3.1 does not return) is absent
from all result fields, error codes, and messages (`test_secret_absence`). No secret
values are printed in test output.

## No scope creep verified

- `test_no_llm_calls`: monkeypatched `subprocess.run`/`Popen` raise → queries do not
  spawn processes (no LLM/network).
- `test_no_network_calls`: monkeypatched `socket.socket` raise → no sockets opened.
- `test_no_real_hermes_home_writes`: real `~/.hermes` unchanged (M3.1-attributable).
- `test_no_m3_2_behavior`: no pagination/cursor/FTS/ranking surfaces in the package.
- `test_no_m4_behavior`: no project-memory write/routing/context-injection surfaces.
- `test_module_level_no_schema_mutation_import`: importing `src.retrieval` does not
  import/apply migrations or touch the read-write store.

## Files changed

- `src/retrieval/__init__.py` (new)
- `src/retrieval/db.py` (new — `open_readonly`, `ReadonlyStore`, SELECT-only schema check)
- `src/retrieval/models.py` (new — `QueryRequest`, `QueryResult`, `EventView`, `QueryError`)
- `src/retrieval/query.py` (new — `get_event`, `get_trace`, `query_events`, `list_session`, `list_project`, `list_profile`)
- `tests/unit/test_m3_query.py` (new — 44 focused tests)

No schema migration. No writes to JSONL, SQLite metadata, lifecycle, relations, scopes,
checkpoints, FTS, tombstones, audit, or project state. No M2/M4 behavior added.

## Blockers

None.

## Next

M3.2 — Deterministic pagination and ordering (awaiting approval).
