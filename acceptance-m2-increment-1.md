# M2 Increment 1 Acceptance Evidence

**Increment:** M2.1 — SQLite foundation and migration framework
**Status:** VERIFIED
**M2 plan:** APPROVED (committed `dac2f91930fff6b2f1164e3df2b9108802e29d9b`)
**Starting commit:** `72fe813f9e890f2f9441ccaa701751553ef9e4ee`
**Plan checkpoint commit:** `dac2f91930fff6b2f1164e3df2b9108802e29d9b`
**Implementation commit:** PENDING_IMPL_COMMIT
**Tested commit:** PENDING_TESTED_COMMIT

## Scope (approved plan M2.1)

> **M2.1 Schema + migration framework**: `src/storage/sqlite_store.py`
> (open/close, WAL, `zm_meta`, `zm_migrations`), migration runner with
> apply/rollback, version check.

Implemented exactly this scope. Schema created in M2.1 is limited to `zm_meta`
(plan §3.1) and `zm_migrations` (plan §3.8). All other tables
(`zm_relations`, `zm_lifecycle`, `zm_provenance`, `zm_scopes`, `zm_artifacts`,
`zm_fts`, `zm_ingest_checkpoint`) arrive in later M2 increments.

## Files changed

- `src/storage/sqlite_store.py` (new) — `SQLiteStore`, `SQLiteStoreConfig`,
  sanitized error hierarchy, connection lifecycle, pragmas, schema-version
  tracking, idempotent `ensure_schema`, transaction-safe `up`/`down`,
  `downgrade_to`, inspection helpers, restrictive permissions.
- `src/storage/migrations/__init__.py` (new) — `MIGRATIONS` registry,
  `CURRENT_SCHEMA_VERSION = 1`.
- `src/storage/migrations/migrate_1.py` (new) — v1 `up`/`down` DDL.
- `tests/unit/test_m2_sqlite_foundation.py` (new) — 25 focused tests.

No source code outside `src/storage/`, no `project-state.yaml` or
`implementation-plan.json` changes were part of this commit's product code;
state/plan updates are recorded separately after verification.

## Required rules satisfied

1. SQLite is derived only; JSONL remains canonical (no JSONL read/write in M2.1).
2. M2.1 does not ingest JSONL events (no `ingest`/`rebuild_from_jsonl` API).
3. Not implemented: JSONL replay, rebuild_from_jsonl, event metadata ingestion,
   lifecycle/provenance/relations/scopes projection, FTS5 content ingestion,
   retention tombstones, retry/backoff, dead-letter, retrieval, ranking, query
   routing, MCP, Obsidian, context injection, M2.2+.
4. Tests use temporary directories only; nothing written to real `~/.hermes`.
5. Installed Hermes source unmodified (guard refuses paths under `~/.hermes`).
6. Errors sanitized: no raw SQL, payloads, secrets, or uncontrolled exception
   text in exception messages (test asserts ABC123/DROPTABLE not leaked).
7. Migration idempotence: reopening an up-to-date DB applies no duplicate.
8. Failed migration rolls back and does not advance schema version.
9. Unknown future schema version (db > code) refused without DB modification.
10. No LLM or network calls (test patches `socket.socket`; store still works).

## Environment

- SQLite 3.53.1 (Python 3.11.15, `sqlite3` stdlib).
- WAL journal mode, `foreign_keys=ON`, `synchronous=NORMAL` (1), `busy_timeout=5000ms`.
- Active provider/model: nous / tencent/hy3:free.

## Test results

- Focused (`tests/unit/test_m2_sqlite_foundation.py`): **25 passed** (0.72s).
- Canonical (`tests/`): **191 passed** (0.98s); no regression vs 166 prior.

Ad-hoc verifier (temporary `hermes-verify-` dirs, cleaned): exercised full
open/ensure_schema/secure_permissions/downgrade_to/ensure_schema cycle; real
`~/.hermes` unchanged (67,729 entries before/after identical); exit 0.

## Acceptance criteria table

| # | Criterion | Result |
|---|-----------|--------|
| 1 | DB creation in temporary directory | PASS |
| 2 | Parent-directory creation | PASS |
| 3 | Connection open/close | PASS |
| 4 | Required pragmas (WAL, FK, sync, busy_timeout) | PASS |
| 5 | Initial schema version 0, then CURRENT (1) | PASS |
| 6 | Deterministic migration ordering | PASS |
| 7 | Applying pending migrations | PASS |
| 8 | Reopening up-to-date DB (no-op) | PASS |
| 9 | Migration idempotence | PASS |
| 10 | Migration transaction rollback | PASS |
| 11 | Failed migration does not advance version | PASS |
| 12 | Unknown future schema version rejection | PASS |
| 13 | Unsupported downgrade rejection | PASS |
| 14 | Sanitized initialization errors | PASS |
| 15 | Sanitized migration errors | PASS |
| 16 | Restrictive file permissions (0o600) | PASS |
| 17 | No real ~/.hermes writes | PASS |
| 18 | No installed Hermes source changes | PASS |
| 19 | No JSONL ingestion API | PASS |
| 20 | No LLM calls | PASS |
| 21 | No network calls | PASS |

## Proof of no later-M2 behavior

- `SQLiteStore` exposes no `ingest`, `rebuild_from_jsonl`, index, retrieval, or
  routing methods; only open/close, version tracking, `ensure_schema`,
  `downgrade_to`, table/PRAGMA inspection, and permission hardening.
- Module import graph does not load `src.storage.jsonl_capture`.
- No FTS5 / relation / scope / lifecycle / provenance / tombstone code present.
- Commit diff is limited to the three new `src/storage/*` files and the test.

## Next

M2.2 — Idempotent JSONL metadata ingestion. Not started.
