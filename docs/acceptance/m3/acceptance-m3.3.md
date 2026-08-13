# M3.3 — Final Acceptance Evidence

**Milestone:** M3.3 — FTS read-only search
**Status:** VERIFIED
**M3 overall:** IN PROGRESS (M3.4 not started)

## Verified starting state

- M0/M1/M2: VERIFIED
- M3.1: VERIFIED (e6c7563 root; impl f3e09e8 → evidence 05634e1 for M3.2)
- M3.2: VERIFIED (f3e09e8 → 05634e1)
- M3.3 starting commit: `05634e1`
- Working tree clean; schema v6; no M3 migration; true read-only (`mode=ro` + `query_only=ON`).

## Files changed (M3.3)

- `src/retrieval/models.py` — added `FTS_UNAVAILABLE`, `MALFORMED_FTS_EXPRESSION` error codes;
  `SearchHit` (deterministic metadata + sanitized `snippet`, `content_source="fts"`) and
  `SearchResult` (typed `results`/`error`/`next_cursor`).
- `src/retrieval/cursor.py` — `make_fingerprint(req, text=None)` now also binds the normalized
  FTS `text` to the query fingerprint (whitespace-collapsed, deterministic).
- `src/retrieval/search.py` (NEW) — `search_text(store, text, req, limit, cursor)`:
  - Read-only capability detection by inspecting the actual database (`sqlite_master` for
    `zm_fts`) — NOT the mutable `FTS5_AVAILABLE` module global — so a stale global from another
    fixture cannot misreport availability. `zm_fts` absent → `fts_unavailable`.
  - Parameterized `zm_fts MATCH ?` (FTS5 syntax passed through; no caller text concatenated into
    SQL). Snippet markers/token-count are fixed string literals (snippet() cannot take bound
    params). All selected/compared columns qualified `zm_meta.` to avoid JOIN ambiguity.
  - `sqlite3.OperationalError` (malformed MATCH) → `malformed_fts_expression`; no raw text leaks.
  - Deleted exclusion via the same derived-state subquery (`zm_meta.event_id NOT IN (SELECT ...
    FROM zm_lifecycle WHERE current_state='deleted')`); stale/synth FTS rows cannot surface a
    deleted event.
  - Deterministic ordering `zm_meta.created_at ASC, zm_meta.event_id ASC` (no bm25/rowid/relevance).
  - M3.2 pagination + cursor binding reused: `limit` default 50 / max 500 (invalid → `invalid_limit`,
    no clamp); versioned base64url cursor binding text + structured filters + limit
    (`cursor_query_mismatch` / `cursor_limit_mismatch` / `invalid_cursor`).
  - No writes: SELECT-only; reuses M2.5 `zm_fts` substrate; no new index/table/migration.
- `src/retrieval/query.py` — `_DELETED_EXCLUSION` qualified `zm_meta.event_id` (fixes JOIN
  ambiguity for FTS search; valid for the metadata-only path too).
- `src/retrieval/__init__.py` — export `search_text`, `SearchHit`, `SearchResult`, FTS codes.
- `tests/unit/test_m3_fts.py` (NEW) — 32 focused tests (see below).

## FTS capability behavior

Detection inspects `sqlite_master` for `zm_fts` on the read-only connection (a `SELECT`). When
absent, `search_text` returns `SearchResult(results=[], error="fts_unavailable")` — an empty
list is NEVER used to mean "unavailable". Metadata queries are unaffected. (The M2.5
`FTS5_AVAILABLE` global is intentionally NOT consulted, because `rebuild_from_jsonl` can flip it
to False mid-session — see "Pre-existing M2 note" below.)

## Allowed query syntax

The raw FTS5 MATCH expression is passed through verbatim and parameterized (`WHERE zm_fts MATCH ?`).
No escaping/transformation is applied; malformed expressions (e.g. `alpha OR`, `alpha OR AND (`)
raise `malformed_fts_expression`. This matches the M3 plan/M2.5 contract (no silent rewrite into
a materially different search).

## Search result contract

`SearchResult { results: list[SearchHit], error: Optional[str], next_cursor: Optional[str] }`.
| situation | results | error |
|-----------|---------|-------|
| success (>=1) | hits | null |
| success, zero | [] | null |
| FTS5 substrate absent | [] | `fts_unavailable` |
| malformed MATCH | [] | `malformed_fts_expression` |

Each `SearchHit` exposes approved structured metadata + `snippet` (from `snippet(zm_fts,1,'[',']','...',8)`)
+ `content_source="fts"`. No raw FTS row, raw payload, secret-bearing text, filesystem path, raw SQL,
or ranking field is exposed.

## Snippet behavior

Deterministic: `snippet(zm_fts, 1, '[', ']', '...', 8)` over the M2.5 sanitized FTS content. Markers
`[`/`]`/`...` and token count 8 are fixed literals. A zero-result search returns no snippet. FTS
snippets come only from the sanitized indexed text; SQLite JSONL is never read to build a snippet.

## Structured-filter composition

FTS candidates are intersected (AND) with M3.1 structured filters via `query_mod._build_where`,
qualified with `zm_meta.`, e.g. `text + project_id`, `+ profile_id`, `+ event_type`, `+ created_at
range`. Zero matches from a combined filter set returns `[]` with `error=None` (not an error; no
global fallback / scope broadening).

## Deterministic ordering

`ORDER BY zm_meta.created_at ASC, zm_meta.event_id ASC`. FTS determines the candidate set only;
no bm25/rowid/relevance. Identical-timestamp ties are broken by `event_id` (verified).

## FTS pagination + cursor binding

Keyset `(zm_meta.created_at, zm_meta.event_id) > (?, ?)` resume; stable ordering; `limit` 50/500;
cursor = versioned base64url `{v:1, qf, sort:[created_at,event_id], lim}` where `qf` (SHA-256) binds
the normalized structured filters AND the normalized FTS text. A cursor for `text="alpha"` is
rejected for `text="beta"` (`cursor_query_mismatch`); a cursor with different structured filters is
rejected (`cursor_query_mismatch`); a cursor with a different limit is rejected
(`cursor_limit_mismatch`). The cursor contains only the fingerprint hash + sort tuple + limit — no
secret, raw SQL, or FTS content.

## Deleted exclusion

Normal FTS search excludes `current_state='deleted'` via the derived-state subquery (verified with a
tombstone deleting an FTS-indexed event; it disappears). `archived`/`superseded` (non-deleted) events
remain returned. No administrative deleted-search mode is added.

## Read-only proof (objective, before/after)

`test_sqlite_and_jsonl_unchanged_by_fts` snapshots before/after a battery of FTS queries +
pagination + cursor: schema DDL hash, derived row counts (zm_meta/lifecycle/provenance/checkpoint/
log/relations/scopes/artifacts/tombstones/audit/migrations), zm_meta content hash, **zm_fts content
hash + row count**, and JSONL sha256. All equal. SQLite access is `mode=ro` + `query_only=ON`;
`search_text` issues only SELECT/parameterized MATCH. No writes to JSONL, rows, schema, checkpoints,
lifecycle, FTS, relations, scopes, tombstones, audit, or project state.

## Secret-safety result

- `zm_fts` content is the M1-sanitized text (fail-closed redaction), so raw secrets cannot enter FTS
  by construction.
- `test_cursor_contains_no_secret`: cursor contains no `SK-M3-...` secret.
- `test_snippet_scan_covers_fts`: injecting a synthetic secret into `zm_fts` is detected by
  `scan_sqlite_for_secrets` (defense-in-depth covers `zm_fts`); the test restores clean content.
- `test_error_contains_no_secret`: malformed-query error is the fixed code `malformed_fts_expression`,
  never echoing caller input.
- No raw SQLite exception text, SQL, DB path, stack trace, or raw FTS internals escape.

## Error contract (covered)

`fts_unavailable`, `malformed_fts_expression`, `invalid_query`, `invalid_limit`, `invalid_cursor`,
`cursor_query_mismatch`, `cursor_limit_mismatch`, `database_unavailable` (defensive), `schema_mismatch`
(inherited). All fixed sanitized codes; no raw SQLite/exception text.

## Focused M3.3 result

`32 passed` (tests/unit/test_m3_fts.py)

## Combined M3.1–M3.3 result

`112 passed` (test_m3_query 44 + test_m3_pagination 36 + test_m3_fts 32)

## Canonical result

`446 passed, 3 skipped` (full `tests/`). No failures. (The one pre-documented environmental real-home
test flake — `test_m2_indexes.py::test_no_real_hermes_home_writes` — did NOT trigger in this run; it
passes independently x2. M3.3's own `test_no_real_hermes_home_writes_during_fts` passes.)

## Pre-existing M2 note (not M3.3 scope)

`rebuild_from_jsonl` drops derived tables but omits `zm_fts` from `DERIVED_TABLES`; because it also
resets `zm_migrations`, the subsequent `ensure_schema` re-runs migration 5 whose `CREATE VIRTUAL TABLE
zm_fts` then fails (table already exists) and flips the module-global `FTS5_AVAILABLE` to False. This
is why M3.3 detects FTS availability by inspecting the actual database rather than the global. M3.3
fixtures are built via the verified M2.5 `_open_store` + `ingest_file` path (single `up()` run), which
correctly populates `zm_fts`. No M2 source was modified by M3.3 (read-only scope preserved).

## Exclusions honored

No FTS pagination of a NEW kind beyond M3.2 reuse; no M3.4 relation/scope traversal; no M3.5 policy
beyond deleted exclusion; no ranking/bm25/relevance/recency; no semantic/vector/embedding search; no
LLM query rewrite; no context injection; no authorization policy; no M4 behavior; no schema migration;
no SQLite writes; no network/LLM calls (verified).

## Acceptance checklist

- [x] all mapped M3.3 acceptance criteria pass
- [x] M3.1 remains VERIFIED (44 passed)
- [x] M3.2 remains VERIFIED (36 passed)
- [x] focused M3.3 tests pass (32)
- [x] combined M3.1–M3.3 pass (112)
- [x] canonical suite passes (446 passed, 3 skipped)
- [x] FTS errors distinguishable from zero results (fts_unavailable / malformed_fts_expression)
- [x] deleted results excluded
- [x] results deterministically ordered
- [x] pagination deterministic
- [x] FTS access objectively read-only
- [x] sanitized-content guarantees pass
- [x] no schema migration
- [x] no M3.4+ behavior
- [x] working tree clean after commit

## Conclusion

M3.3: VERIFIED. M3 overall: IN PROGRESS. Next: M3.4 — Relation and scope read queries.
