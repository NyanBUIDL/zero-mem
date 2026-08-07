# M3.2 — Final Acceptance Evidence

**Milestone:** M3.2 — Deterministic pagination and ordering
**Status:** VERIFIED
**M3 overall:** IN PROGRESS (M3.3 not started)

## Verified starting state

- M0/M1/M2: VERIFIED
- M3.1: VERIFIED (commits `aa74f56` → `e6c7563`)
- HEAD at M3.2 start: `e6c7563`
- SQLite schema version: 6
- Canonical before M3.2: 377 passed, 3 skipped
- M3.1 focused: 44 passed

## Commits produced this increment

| Step | Commit | Description |
|------|--------|-------------|
| Implementation | `<impl>` | feat(m3.2): deterministic pagination + versioned query-bound cursor |
| Evidence/state binding | `<evidence>` | docs(m3.2): M3.2 acceptance evidence + state binding |

(plan checkpoint `46be195` and M3.1 work `aa74f56`..`e6c7563` are the parent chain.)

## Tested commit

- `<impl>` (M3.2 implementation; parent chain `46be195` → `aa74f56` → `e6c7563`).

## Focused M3.2 result (plan-defined command)

```
.venv/bin/python -m pytest tests/unit/test_m3_pagination.py -q
36 passed
```

Covers every M3.2 acceptance criterion: default limit (50), explicit valid limit,
maximum limit (500), zero/negative/above-max/non-integer limit rejected (`invalid_limit`),
deterministic first/next page, stable `(created_at, event_id)` ordering, identical-timestamp
tie-break by event_id, valid cursor resume (keyset), malformed cursor (`invalid_cursor`),
unsupported version (`invalid_cursor`), cursor query mismatch (`cursor_query_mismatch`),
cursor limit mismatch (`cursor_limit_mismatch`), missing sort fields (`invalid_cursor`),
final page `next_cursor=None`, empty result, no duplicate rows, no skipped rows, paginated
== full deterministic result, combined structured filters, deleted exclusion across page
boundaries, cursor contains no secret, sanitized errors, SQLite unchanged, JSONL unchanged,
no LLM/network calls, no real `~/.hermes` writes, no M3.3+/M4 behavior.

## M3.1 + M3.2 focused result

```
.venv/bin/python -m pytest tests/unit/test_m3_query.py tests/unit/test_m3_pagination.py -q
80 passed
```

## Canonical suite result (no deselect)

```
.venv/bin/python -m pytest tests/ -q
414 passed, 3 skipped
```

(The previously documented environmental real-home flake
`tests/unit/test_m2_indexes.py::test_no_real_hermes_home_writes` passes in isolation
(2/2 reruns) and did not fire in this run — it is caused by the live Hermes desktop
app writing `kanban.db-wal`/`kanban.db-shm` to real `~/.hermes` concurrently, not by
M3.2. M3.2's own `~/.hermes` isolation test passes. Canonical count rose 377 → 414
(36 new M3.2 + 1 new baseline-gate test from M3.1 sync); 3 skipped unchanged.)

## Stable ordering

`ORDER BY created_at ASC, event_id ASC`. `created_at` is a non-null required column, so
no NULL sort behavior is reachable; ties on `created_at` are broken deterministically by
`event_id` (verified in `test_identical_timestamp_tie_break`). No `rowid`, insertion
order, or unspecified SQLite ordering is used.

## Cursor format

Versioned, query-bound keyset cursor. Encoded as base64url(JSON) carrying only safe
deterministic fields:

```json
{ "v": 1, "qf": "<sha256>", "sort": ["<created_at>", "<event_id>"], "lim": <int> }
```

No raw SQL, FTS content, secrets, filesystem paths, or exception text. Encoding is
transport-only; safety comes from contained fields + strict validation + fingerprint
binding, not secrecy.

## Query fingerprint algorithm

`qf = SHA-256(canonical_json(sorted_normalized_filters + {"_deleted_excluded": true}))`
where `sorted_normalized_filters` is the `QueryRequest.to_dict()` form (sorted keys,
None-excluded, deterministic separators). Equivalent queries → identical `qf`; different
filter sets → different `qf` with practical determinism. No runtime/irrelevant values
included. Verified in `test_combined_filters_pagination`.

## Limit behavior

Default 50, maximum 500. `limit=None` → 50. Invalid (0, negative, >500, non-integer,
bool) → `invalid_limit`; no silent clamping. Cursor binds the limit: a different limit
with the same cursor → `cursor_limit_mismatch`.

## Pagination behavior

Keyset pagination via parameterized `WHERE (created_at, event_id) > (?, ?)` combined with
the structured filters + deleted exclusion — no OFFSET, no rowid. Final page yields
`next_cursor=None`. `include_total` is an accepted optional read-only COUNT but not forced.

## No-duplicate / no-skip proof

`test_no_duplicate_rows_across_pages` asserts every event_id appears once; `test_no_skipped_rows_across_pages`
paginates a 13-row corpus and asserts the concatenated page order equals the unpaginated
full result; `test_paginated_equals_full` asserts page concatenation == full deterministic
result. All pass.

## Read-only proof

`test_pagination_no_mutation` captures a `Snapshot` (sqlite_master DDL hash, row counts
for all 11 derived tables, zm_meta content hash, JSONL sha256) before and after a full
pagination battery (cursor walk over project P + full-corpus walk). `test_sqlite_unchanged_by_pagination`
and `test_jsonl_unchanged_by_pagination` assert row counts / JSONL sha256 unchanged.
`open_readonly` still uses `file:?mode=ro` + `PRAGMA query_only=ON`; no `ensure_schema`/
migration/write path is invoked.

## Secret safety

A synthetic secret is confirmed absent from the encoded cursor token and its decoded
payload (`test_cursor_contains_no_secret`). M3.2 returns only discrete enum/id filters;
no free-text content is embedded in cursors.

## Error safety

Fixed sanitized codes only: `invalid_limit`, `invalid_cursor`, `cursor_query_mismatch`,
`cursor_limit_mismatch`, `invalid_query`, `schema_mismatch`, `database_unavailable`. No
raw SQLite text escapes (verified by `test_malformed_cursor`, `test_unsupported_cursor_version`,
`test_cursor_missing_sort_fields`, and the limit tests).

## Scope exclusions verified

- `test_no_m3_3_behavior`: no FTS / semantic / ranking surfaces in the package.
- `test_no_m4_behavior_pagination`: no project-memory write/routing/context-injection.
- `test_no_llm_calls_pagination` / `test_no_network_calls_pagination`: subprocess/socket
  monkeypatching raises if M3.2 calls them.
- No schema migration (only SELECT + `PRAGMA query_only`; no DDL).

## Files changed

- `src/retrieval/cursor.py` (new — fingerprint, encode/decode, binding validation)
- `src/retrieval/models.py` (extended — cursor error codes, `QueryResult.next_cursor`)
- `src/retrieval/query.py` (extended — limit validation, keyset pagination, `next_cursor`)
- `src/retrieval/__init__.py` (exports cursor helpers + error codes)
- `tests/unit/test_m3_pagination.py` (new — 36 focused tests)
- `conftest.py`, `tests/__init__.py`, `tests/unit/__init__.py` (test packaging so the
  pagination suite can reuse M3.1 helpers)

No writes to JSONL, SQLite rows, schema, checkpoints, lifecycle, FTS, relations,
tombstones, audit, or project state. No schema migration.

## Blockers

None.

## Next

M3.3 — FTS read-only search (awaiting approval).
