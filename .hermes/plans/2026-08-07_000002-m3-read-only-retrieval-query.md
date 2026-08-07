# M3 — Read-only retrieval and query

**Status:** PLAN (final M3 design; not implemented)
**Milestone:** M3 (read-only retrieval/query over the verified M2 substrate)
**Authority:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` (DOCX authoritative); `AGENTS.md`; `ARCHITECTURE.md`; `IDEA.md`; `implementation-plan.json`; `project-state.yaml`; verified M2 code (`src/storage/ingest.py`, migrations 1–6).
**Predecessor state:** M0–M2 VERIFIED (M2.7 final acceptance `c97357e`); HEAD `539b5ff`; schema v6; canonical 334 passed / 3 skipped; working tree clean; M3/M4 not started.

This plan defines M3 only. No source code, tests, `project-state.yaml`, or `implementation-plan.json` changes are made by this artifact.

## 1. Reconciled starting state

- HEAD `539b5ff` (matches expected final M2 state). Clean tree.
- M0/M1/M2 VERIFIED; M2.1–M2.7 VERIFIED.
- Schema version **6**. Canonical suite **334 passed, 3 skipped**.
- M3 not started; M4 not started.
- No conflict → planning proceeds.

## 2. Proposed M3 architecture

M3 adds a **deterministic, read-only query layer** (`src/retrieval/`) that composes the verified M2
exact-key inspection helpers. It introduces **no writes**, **no new canonical store**, **no new SQLite
schema migration**, and **no LLM/network** in the query path.

- JSONL remains the authoritative raw source of record (never read-modified by M3).
- SQLite remains derived/disposable/rebuildable/non-canonical (M3 only reads it).
- M3 returns **stable, ordered, filtered** result sets; it does **not** inject anything into LLM
  context, does **not** rewrite queries via an LLM, and does **not** perform relevance ranking
  (see §7).
- M3 reuses the existing M2.5 FTS5 layer (`zm_fts`, `search_fts`) for text search — no second index.
- All M3 query functions are pure reads over a `SQLiteStore` (already constructed by callers); M3
  opens no connections and performs no `INSERT/UPDATE/DELETE`.

### 2.1 Dedicated TRUE read-only database access path (Correction 1)

The verified M2 `SQLiteStore` opens with `sqlite3.connect(path)` then `PRAGMA journal_mode=WAL` +
`commit()` — a **mutating** open (it can create/rotate WAL/SHM state). M3 must NOT use that path.

M3 opens an explicitly read-only connection via a dedicated helper (new `src/retrieval/readonly.py`):

- `open_readonly_store(path)` builds a URI connection:
  `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`.
- Immediately after open, execute `PRAGMA query_only = ON` (no-op/ignored where unsupported, but
  set when available to reject any write at the engine level).
- M3 must **never** call: `ensure_schema`, `migrate*`, `downgrade_to`, schema initialization,
  `PRAGMA journal_mode=WAL`, or any helper that can create tables/indexes or open a write
  transaction.

Read-only enforcement (objective proof, not "we didn't call INSERT"):
- Before/after each query battery, record: `sqlite_master` DDL state (schema hash), per-table row
  counts, a content hash over a deterministic dump of every read table (zm_meta, zm_lifecycle,
  zm_provenance, zm_relations, zm_scopes, zm_artifacts, zm_fts, zm_tombstones, zm_deletion_audit,
  zm_ingest_checkpoint, zm_ingest_log, zm_migrations), the database file's mtime/size, and the
  canonical JSONL sha256.
- Assert all of the above are byte-identical before vs after. Any drift → test failure.
- Schema-version validation is performed by a read-only `SELECT MAX(version) FROM zm_migrations`
  (no `ensure_schema` call).

### 2.2 Authoritative M3 content-source matrix (Correction 2)

`zm_meta` stores **no** `sanitized_content` blob (M2.2: only `content_hash` is projected; the blob is
excluded). Verified existing content sources in the M2 substrate:

| Mode | Authoritative source | FTS5 required? | Notes |
|------|----------------------|----------------|-------|
| 1. Metadata-only | `zm_meta` columns (incl. `content_hash` reference) | No | Always available |
| 2. Text-content | canonical JSONL `sanitized_content` (read-only line lookup by `event_id`) | No | Resolved from the source-of-record JSONL only; M3 reads JSONL read-only and does NOT modify it |
| 3. FTS snippet | `zm_fts.content` via `snippet(zm_fts, ...)` | Yes | FTS5 unavailable → snippet empty, metadata still returned |
| 4. Artifact reference | `zm_artifacts.stored_path` (pointer only) | No | M3 returns the reference, never reconstructs/fetches external file content |

M3 must **not** reconstruct missing content or invent content. If `sanitized_content` is requested
but FTS5 is unavailable, M3 resolves it from canonical JSONL (mode 2) — it is **not** made to depend
accidentally on FTS5. Metadata-only and artifact-reference retrieval work regardless of FTS5. (If a
future decision requires inline SQLite content storage, that is a separate schema-migration milestone;
it is NOT silently added here.)
- Administrative deleted-state inspection is delegated to existing M2 helpers
  (`list_deleted`, `get_tombstone`, `get_deletion_audit`) — M3 normal queries simply exclude `deleted`.

### 2.1 True read-only SQLite access path (mandatory)

M3 must **not** merely avoid writing SQL. It must open SQLite through an explicitly read-only
connection distinct from M2's `SQLiteStore` (which sets `journal_mode=WAL` and can create tables).

- New accessor `src/retrieval/db.py: open_readonly(path) -> ReadonlyStore` opens the database with a
  URI read-only connection: `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`, `row_factory =
  sqlite3.Row`, and enables `PRAGMA query_only = ON` (where supported). `mode=ro` prevents any write
  at the connection level; `query_only` blocks even read-only pragmas that could checkpoint.
- M3 **must NOT** call: `ensure_schema`, `migrations`, `downgrade_to`, schema initialization, WAL
  configuration that mutates the database, any helper that creates tables/indexes, or any write
  transaction. It must not reuse `SQLiteStore` (which is read-write).
- **Read-only schema-version validation:** `get_schema_version()` reads `MAX(version)` from
  `zm_migrations` (a `SELECT` only). If the store lacks `zm_migrations`, version is reported as `0`.
  This validation performs no migration and no table creation.
- Opening and executing M3 queries must not create or modify: database rows; schema; WAL/SHM state
  attributable to M3; checkpoints; FTS rows; lifecycle state; audit rows.
- Canonical JSONL is read **only** (resolved, never written) for content resolution (see §6).

### 2.2 Objective read-only proof (test requirements)

Tests must prove database state is unchanged before and after a query battery, not merely assert
"we did not call INSERT". Before/after each M3 query session, record and compare:

- `sqlite_master` DDL hash (schema identity);
- row counts for `zm_meta`, `zm_lifecycle`, `zm_provenance`, `zm_relations`, `zm_scopes`, `zm_artifacts`,
  `zm_fts`, `zm_tombstones`, `zm_deletion_audit`, `zm_ingest_checkpoint`, `zm_ingest_log`;
- content hashes over a stable column-ordered dump of those tables (excluding volatile `updated_at`
  where measured separately);
- SQLite database file size / inode metadata (must not grow due to M3 WAL/SHM writes);
- JSONL file sha256 (byte-for-byte unchanged).

A mismatch fails the test. This is implemented as a `Snapshot` helper in the M3 test module.

## 3. Exact read-only API (smallest surface)

Names are illustrative but follow repository conventions; reuse existing M2 helpers where equivalent.

- `query_events(store, query: QueryRequest) -> QueryResult` — multi-filter AND query (primary entry).
- `get_event(store, event_id: str) -> Optional[EventView]` — exact-key single event (wraps `get_trace`).
- `get_trace(store, trace_id: str) -> list[EventView]` — all non-deleted events of a trace (wraps `find_by_trace_id`).
- `search_text(store, text: str, limit: int = 20) -> list[SearchHit]` — FTS5 sanitized search (wraps `search_fts`).
- `get_related(store, event_id: str, relation_type: Optional[str] = None) -> list[RelatedView]` — relations both directions (wraps `find_related` + `get_relations`); bounded, no graph traversal.
- `list_session(store, session_id: str) -> list[EventView]` — session scoping.
- `list_project(store, project_id: str) -> list[EventView]` — project scoping (wraps `list_events_in_scope`).
- `list_profile(store, profile_id: str) -> list[EventView]` — profile scoping (wraps `list_events_in_scope`).
- `get_provenance(store, event_id: str)` and `get_lifecycle(store, event_id: str)` are exposed as
  optional view enrichments (read-only, already in M2).

No redundant helpers: `list_events_in_scope`, `find_by_trace_id`, `find_related`, `search_fts`,
`get_trace`, `get_lifecycle`, `get_provenance`, `get_relations`, `get_scopes`, `get_artifact`,
`list_deleted`, `get_tombstone`, `get_deletion_audit`, `count_metadata`, `get_checkpoint` are reused
directly. M3 does **not** re-implement them.

## 4. Supported query filters

Mapped to verified `zm_meta` columns / derived tables:

| Filter | Column / source | M3 support |
|--------|----------------|-----------|
| event_id | zm_meta.event_id | Supported (exact-key) |
| trace_id | zm_meta.trace_id | Supported |
| event_type | zm_meta.event_type | Supported |
| source | zm_meta.source | Supported |
| session_id | zm_meta.session_id | Supported |
| profile_id | zm_meta.profile_id | Supported (scope) |
| project_id | zm_meta.project_id | Supported (scope) |
| task_id | zm_meta.task_id | Supported |
| turn_id | zm_meta.turn_id | Supported |
| parent_trace_id | zm_meta.parent_trace_id | Supported |
| lifecycle_status | zm_meta.lifecycle_status | Supported (default: exclude `deleted`) |
| verification_status | zm_meta.verification_status | Supported |
| retention | zm_meta.retention | Supported |
| created_at range | zm_meta.created_at | Supported (ISO-8601 string compare; see §5) |
| observed_at range | zm_meta.observed_at | Supported (ISO-8601 string compare) |
| relation IDs | zm_relations.relation / to_event_id | Supported (filter by relation_type/edge) |
| knowledge-space mapping | zm_scopes (scope_type='knowledge_space') | Supported (scope filter) |
| artifact reference | zm_artifacts.artifact_id | Supported (post-filter / join) |
| keyword / FTS text | zm_fts.content (sanitized) | Supported via `search_text` |

**Explicitly unsupported in M3:** semantic/vector similarity, LLM query rewriting, autonomous query
expansion, cross-encoder reranking, BM25-vs-FTS5 selection by the engine. These are out of M3 scope
(see §14).

**Reserved for later milestones:** relevance ranking/scoring (later), query routing (M4), authorization
/ access-control policy (M5), MCP exposure (M6), injection (M7).

OR semantics: **not** in M3 base contract (AND-only). If a caller needs OR, it issues multiple queries
and unions results locally. Documented as explicitly unsupported to avoid guessing.

## 5. Query semantics

- **Exact-key lookup:** `get_event` returns one `EventView` or `None`; never raises for a missing id.
- **Multi-filter AND:** `query_events` ANDs all supplied non-null filters. Empty filter set → returns
  all non-deleted events (bounded by limit; see pagination).
- **Time-range:** `created_at`/`observed_at` compared as ISO-8601 strings (already normalized on
  ingest). Filters `after`/`before` are inclusive; malformed timestamps → sanitized error
  `invalid_time_range`.
- **Pagination:** server-side `LIMIT ? OFFSET ?` plus a stable cursor (see §8). Default `limit=50`,
  `max_limit=500`.
- **Stable ordering:** results ordered by `(created_at ASC, event_id ASC)` by default — never by
  `rowid`. Deterministic for identical DB state + identical query.
- **Duplicate suppression:** `event_id` is the primary key; each event appears once.
- **Deleted-record exclusion (lifecycle default — grounded in an approved decision, not inferred from
  M2 helpers alone):** default `lifecycle_status != 'deleted'`. Basis: **Decision B** (approved M2.6,
  recorded in `project-state.yaml`) establishes `deleted` as a logical deletion that is excluded from
  active retrieval helpers (`find_by_trace_id`, `list_events_in_scope` already exclude it); and
  `IDEA.md` "global read access by default" supports returning all other stored lifecycle states.
  Therefore the M3 default is: **exclude `deleted`; include raw / observed / candidate / confirmed /
  active / superseded / conflicted / archived** unless the caller filters `lifecycle_status`. Overridable
  only via the explicit admin deleted-inspection path (reuse `list_deleted` / `get_tombstone` /
  `get_deletion_audit`).
- **Archived / superseded / conflicted:** included by default (they remain valid stored states per the
  default above); the caller may filter them out via `lifecycle_status` if desired. `superseded` is NOT
  auto-hidden.
- **Verification-state filtering:** `verification_status` filter supported (e.g. `verified`,
  `none`, `user_statement`, `assistant_claim`, `inference`). M3 does **not** treat `assistant_claim`
  as a fact; it is surfaced as a `verification_status` label and never reordered above `verified`.
- **Empty result:** returns `QueryResult(items=[], next_cursor=None, total=0)` — never an error.
- **Malformed query:** sanitized error `invalid_query` (e.g. unknown filter key, non-string event_id).
- **Unsupported filter:** sanitized error `unsupported_filter` (e.g. a vector/similarity filter).

Same DB state + same query ⇒ identical ordered result set. Verified by a determinism test (run twice,
assert byte-equal JSON).

## 6. Retrieval result contract (EventView)

Only approved fields are returned:

- `event_id`, `trace_id`, `event_type`, `source`, `schema_version`
- `created_at`, `observed_at`, `sequence`
- `session_id`, `profile_id`, `project_id`, `task_id`, `turn_id`, `parent_trace_id` (where present)
- `lifecycle_status`, `verification_status`, `confidence`, `sensitivity`, `retention`
- `content_hash` (sanitized content reference — from `zm_meta`, no blob)
- `sanitized_content`: present only when `include_content=True` and the source resolves (see content
  resolution below); `None` otherwise. When present it is the M1-sanitized dict, never reconstructed.
- `content_source`: one of `metadata_only` | `jsonl` | `artifact` — records the authoritative source
  used for `sanitized_content` (see content resolution below).
- `relation_info` (only when explicitly requested via `include_relations=True`): list of
  `{relation, to_event_id, verifier}` from `get_relations`
- `artifact_refs` (only when explicitly requested via `include_artifacts=True`): from `get_artifact`
  (returns the `stored_path` reference only — M3 never fetches external file content)
- `match_metadata`: `{matched_filters: [...], fts_snippet: Optional[str], fts_error: Optional[str]}`
- `provenance_metadata`: `{verifier, evidence_ref, verification_status}` (from `get_provenance`)

**Content resolution (explicit — grounded in the verified M2 substrate):**

The verified `zm_meta` table stores **only `content_hash` + `redaction_applied`** (it does NOT store
the full `sanitized_content` blob). The authoritative sanitized content lives in the **canonical
JSONL** envelope (M1 redaction produces and appends it). `zm_fts.content` is a derived FTS5 index of
that sanitized content (present only when FTS5 is available and the event had sanitized content) — it
is NOT the system of record. M3 defines four distinct retrieval modes and never invents or
reconstructs content:

1. **metadata-only** (`include_content=False`, default): return the `zm_meta` columns only. Works
   with or without FTS5 — no content resolution needed.
2. **text-content** (`include_content=True`): resolve `sanitized_content` **read-only from the canonical
   JSONL** by `event_id` (the source of record). M3 reads the JSONL line, extracts the already-redacted
   `sanitized_content`, and returns it. JSONL is never modified. This path is **independent of FTS5
   availability** — ordinary content retrieval does NOT depend on FTS being present.
3. **FTS snippet** (`match_metadata.fts_snippet`): populated only via `zm_fts` `snippet()` when FTS5 is
   available; `None` otherwise. It is a search-context snippet, never a substitute for full text-content.
4. **artifact-reference**: returns `zm_artifacts.stored_path` reference only; M3 never reads external
   file bytes.

If a requested content source does not exist for an event (e.g. `include_content=True` but the JSONL
line has no `sanitized_content`), M3 returns `sanitized_content=None` with `content_source=metadata_only`
and a `content_unavailable` note — it does not fabricate content.

**Distinction:**
- *stored data*: the EventView fields above (metadata from `zm_meta`; content from JSONL/artifact ref).
- *derived match metadata*: `match_metadata` (what the query matched / FTS snippet / FTS error code).
- *caller-supplied*: the original `QueryRequest` is echoed in `result.query` for auditability.

**Never returned:** raw JSONL lines, raw secret-bearing payloads, unrestricted filesystem paths, raw
exceptions, internal credentials, deleted content (normal path), `origin_jsonl` internal path, or
internal `rowid`.

## 7. Ranking decision — NO ranking in M3 (re-checked against the M3 objective)

The M3 objective defines **read-only retrieval and query** with a deterministic query model; it
specifies **no relevance score, no confidence weighting, no recency score, and no LLM ranking**. M2.5/
M2.7 explicitly prohibited ranking/scoring from the derived layer, and `search_fts` returns unordered
candidate IDs (no relevance score). ARCHITECTURE.md/IDEA.md describe ranking only at the system routing
layer, not as an M3 retrieval-scoring feature. Therefore M3 uses deterministic stable ordering only:

- M3 returns **stable filtered + deterministically ordered** results only.
- No FTS relevance score, no confidence-weighted ordering, no recency score, no LLM rerank.
- `search_text` returns FTS candidates; `query_events` with a text filter joins FTS result set ids and
  then applies the same stable `(created_at, event_id)` ordering as structured queries.
- If a later milestone (e.g. M4) explicitly defines a deterministic ranking model over already-stored
  structured signals, it is implemented there — not silently invented in M3. This is the documented,
  spec-consistent choice; **no NEEDS DECISION**.

## 8. Pagination & cursor model

- `default_limit = 50`, `max_limit = 500` (values > max → sanitized error `invalid_limit`).
- Results ordered by the stable sort tuple `(created_at ASC, event_id ASC)` — never by `rowid`.

### Cursor (versioned + query-bound, not reversible encoding)

The cursor is a **versioned, deterministic, query-fingerprint-bound** token — not a reversible base64
of a tuple described as "opaque".

Structure (then serialized as base64url of UTF-8 JSON; the encoding is transport only, the contents
are what make it safe):

```
{
  "v": 1,                       # cursor version
  "qf": "<sha256>",             # query fingerprint (see below)
  "sort": ["<created_at>", "<event_id>"],   # last row's stable sort tuple
  "lim": <limit>
}
```

- **Query fingerprint `qf`** = SHA-256 of the canonical JSON serialization of the *normalized, safe*
  filter set (all supplied filters, sorted keys, normalized values; excludes any raw FTS expression
  text, paths, or secrets). This binds a cursor to exactly one normalized query.
- A cursor built for query A **must not** be silently reused for query B: if `qf` of the cursor does
  not equal the `qf` of the current query → sanitized error `cursor_query_mismatch`.
- Cursor contents must **not** contain: secrets, raw FTS content, filesystem paths, raw SQL, or raw
  exception text.

Cursor behaviors:
- **malformed cursor** (undecodable / not JSON / missing fields) → `invalid_cursor`.
- **unsupported cursor version** (`v` not recognized) → `invalid_cursor` (with version note in code).
- **query-fingerprint mismatch** → `cursor_query_mismatch`.
- **changed limit** (cursor `lim` != current `limit`) → `cursor_limit_mismatch` (or re-derive from
  current limit and continue — chosen: `cursor_limit_mismatch` to be explicit and deterministic).
- **missing sort fields** → `invalid_cursor`.
- **end-of-results**: when fewer than `limit` rows remain, `next_cursor = None`.
- Continuation uses `WHERE (created_at, event_id) > (cursor.sort)` in lexicographic tuple order
  (deterministic; no `rowid`).
- No external secret or network service is required to create/validate cursors.
- No total-count scan forced on every page; `total` is best-effort (None when not requested) to avoid
  full-table scans. `include_total=True` triggers one `COUNT(*)` for that filter set.
- Performance: rely on existing M2 indexes (zm_meta columns indexed in M2.5) + FTS5; no new cache
  unless a later benchmark proves one necessary.

## 9. FTS behavior (reuse M2.5)

- Exposes `search_text(store, text, limit)` wrapping `search_fts`.
- Query syntax: raw FTS5 MATCH expression passed through; `search_fts` already wraps in a `try/except
  sqlite3.OperationalError` returning `[]` on malformed expressions.
- Capability detection: if `FTS5_AVAILABLE is False`, `search_text` returns `[]` and sets
  `match_metadata.fts_available = False`. No second index is created.
- Deleted-record exclusion: `zm_fts` is already stripped of deleted events at ingest (M2.6), so FTS
  results never include deleted content.
- Sanitized-content-only guarantee: `zm_fts.content` is the M1-sanitized content (fail-closed
  redaction), so FTS cannot leak raw secrets by construction.
- Deterministic secondary ordering: FTS candidates are re-sorted by `(created_at, event_id)` before
  pagination, identical to structured queries.

### FTS result + error contract (Correction 3 — unambiguous)

`search_text` and the FTS branch of `query_events` return a typed result; an empty list is **never**
used to mean both "zero results" and "error". No raw SQLite exception text escapes.

```
SearchResult:
  results: list[SearchHit]      # [] on success-with-zero OR on error
  error:   Optional[str]        # fixed code, or null
```

| Situation | results | error |
|-----------|---------|-------|
| success (≥1 hit) | `[...hits]` | `null` |
| success, zero hits | `[]` | `null` |
| FTS5 unavailable | `[]` | `fts_unavailable` |
| malformed FTS expression | `[]` | `malformed_fts_expression` |

The same fixed error codes are used by `query_events` where an FTS sub-query applies. Callers
distinguish zero-results from errors by inspecting `error`.

## 10. Error contract (fixed sanitized codes)

`invalid_query`, `unsupported_filter`, `invalid_time_range`, `invalid_cursor`, `invalid_limit`,
`cursor_query_mismatch`, `cursor_limit_mismatch`, `fts_unavailable` (informational, returns `[]`),
`malformed_fts_expression` (returns `[]` + flag), `database_unavailable`, `schema_mismatch`,
`content_unavailable` (informational, `sanitized_content=None`). All map to a `QueryError(code,
message=None)` with a fixed code and **no** raw SQLite/exception text. Callers receive a stable
structure; diagnostics logs use the same codes only.

## 11. Secret-safety model

- M3 returns only `sanitized_content` (already redacted at M1) + derived metadata. No raw payload.
- Synthetic-secret verification (M2 pattern): inject `SK-M3-*` into a fixture's `zm_meta` benign
  column / `zm_tombstones` / `zm_fts` and assert M3 results + diagnostics never contain the secret and
  `scan_sqlite_for_secrets` (reused) detects it if present in derived state.
- FTS search over sanitized content cannot surface secret-bearing raw data (sanitized by construction).
- Query errors never echo raw input; cursors contain no secrets.
- Logs/diagnostics use fixed sanitized codes only.

## 12. Read-only enforcement (tested)

A dedicated test captures SQLite state (table-row counts + a content hash over a stable dump of
zm_meta/zm_lifecycle/zm_fts/zm_relations/zm_tombstones/zm_deletion_audit + JSONL sha256) BEFORE and
AFTER a battery of M3 queries, and asserts byte/row equality. Covers: JSONL bytes unchanged; SQLite
rows unchanged; lifecycle/checkpoint/ingest_log/FTS/tombstones/audit unchanged; schema version
unchanged. Plus a no-LLM / no-network guard (socket + subprocess monkeypatch raising on any socket
call, as in M2).

## 13. Scope & profile behavior

- Filters use explicitly supplied `project_id` / `profile_id` / `session_id` / `knowledge_space`
  constraints. No inference of cross-profile / cross-project / cross-knowledge-space membership.
- A query scoped to a profile/project with no matching data returns `[]` (no global fallback) unless a
  later spec explicitly permits fallback (reserved).
- M3 does **not** implement M5 authorization; it only honors caller-supplied scope filters.

## 14. Explicit M3 exclusions

Unless the authoritative spec explicitly places them in M3, exclude: writes to memory; mutation through
retrieval; automatic memory capture; automatic context injection; prompt assembly; LLM memory
selection; LLM summarization; semantic/vector embedding; autonomous query rewriting; project-state
mutation; requirement registry; decision-log management; M4 project-memory behavior; M5
access-control policy; Obsidian synchronization; MCP integration; background scheduler; retry/backoff;
dead-letter storage; physical JSONL deletion; M4 or later implementation.

## 15. Proposed M3 increments

No schema migration is required (see §16). Each increment is independently verifiable.

### M3.1 — Query contract + exact structured filters
- Scope: `QueryRequest`/`QueryResult`/`EventView` models; **true read-only access** via `src/retrieval/db.py: open_readonly` (`file:..?mode=ro` + `PRAGMA query_only=ON`, read-only `get_schema_version`); `query_events` AND semantics over zm_meta columns (event_id, trace_id, event_type, source, session_id, profile_id, project_id, task_id, turn_id, parent_trace_id, lifecycle_status, verification_status, retention); exact-key `get_event`, `get_trace`, `list_session`, `list_project`, `list_profile`. **Must NOT call** ensure_schema/migrations/downgrade_to or reuse the read-write `SQLiteStore`.
- Files: `src/retrieval/db.py` (read-only accessor), `src/retrieval/query.py`, `src/retrieval/models.py` (new); reuses `src/storage/ingest.py` read-only helpers.
- Schema impact: none (read-only connection; no migration).
- Tests: `tests/unit/test_m3_query.py` (exact lookup, trace lookup, each filter, combined AND, empty
  result, malformed query, sanitized errors) **plus read-only enforcement** (sqlite_master hash + row
  counts + content hashes + JSONL sha256 unchanged before/after; DB file size unchanged).
- Acceptance: every supported filter returns correct subset; deleted excluded by default; deterministic
  ordering; no DB mutation (objective snapshot proof, not "no INSERT" assertion).
- Rollback: pure-additive new module; revert commit.
- Deps: M2 VERIFIED.
- Exclusions: no FTS, no ranking, no writes.

### M3.2 — Deterministic pagination & ordering
- Scope: limit/max_limit, **versioned query-bound cursor** (§8: `v`/`qf`/sort/limit; NOT reversible
  base64 described as opaque), stable `(created_at, event_id)` ordering, `include_total`,
  time-range filters (`created_at`/`observed_at`), duplicate suppression.
- Files: extends `src/retrieval/query.py` (reuses `src/retrieval/db.py` read-only accessor).
- Schema impact: none.
- Tests: `tests/unit/test_m3_pagination.py` (default/max limit, invalid limit, cursor round-trip,
  invalid cursor, unsupported cursor version, query-fingerprint mismatch, changed limit, time range,
  no duplicates, deterministic order across two runs, read-only enforcement).
- Acceptance: identical ordered pages for identical state; cursor encodes no secret/SQL/path; cursor
  bound to its query (fingerprint mismatch → `cursor_query_mismatch`); stale cursor yields
  deterministic continuation.
- Rollback: revert.
- Deps: M3.1.
- Exclusions: no ranking.

### M3.3 — FTS read-only search
- Scope: `search_text` wrapping `search_fts`; safe escaping; capability detection; deleted exclusion
  (inherited); sanitized-only guarantee; deterministic secondary ordering; malformed-expression
  handling; pagination.
- Files: `src/retrieval/search.py` (new).
- Schema impact: none (reuses M2.5 `zm_fts`).
- Tests: `tests/unit/test_m3_search.py` (sanitized search hit; **typed result distinguishes** legitimate
  zero results `error=null` vs `fts_unavailable` vs `malformed_fts_expression`; FTS-unavailable path
  returns `error=fts_unavailable`; malformed expression returns `error=malformed_fts_expression`;
  deleted excluded; deterministic order; no raw SQLite text escapes).
- Acceptance: no second index; FTS results never leak raw secret; no ranking; zero/malformed/unavailable
  are distinguishable via the fixed error contract.
- Rollback: revert.
- Deps: M3.1, M2.5.
- Exclusions: no vector/semantic search.

### M3.4 — Relation / scope read queries
- Scope: `get_related` (both directions, `relation_type` filter), artifact-reference lookup,
  knowledge-space scope filter; bounded (no full graph traversal).
- Files: extends `src/retrieval/query.py` (reuses `find_related`, `get_relations`, `get_artifact`,
  `get_scopes`).
- Schema impact: none.
- Tests: `tests/unit/test_m3_relations.py` (parent/child, explicit relation_ids, artifact refs,
  knowledge-space filter, no mutation, no inferred edges).
- Acceptance: read-only; no relation creation; explicit edges only.
- Rollback: revert.
- Deps: M3.1.
- Exclusions: no graph traversal beyond direct edges; no authorization.

### M3.5 — Verification / lifecycle-aware retrieval
- Scope: `verification_status` filtering semantics; surfacing `assistant_claim`/`user_statement`/
  `inference`/`verified` as labels without treating claims as facts; `lifecycle_status` visibility
  rules (default exclude `deleted`; archived/superseded/conflicted included unless filtered);
  `provenance_metadata` enrichment; admin deleted inspection passthrough (`list_deleted`/
  `get_tombstone`/`get_deletion_audit`).
- Files: extends `src/retrieval/query.py` + `src/retrieval/views.py` (enrichment).
- Schema impact: none.
- Tests: `tests/unit/test_m3_verification.py` (verification filter, claim-not-fact ordering, lifecycle
  default visibility, explicit deleted retrieval via admin path, provenance enrichment).
- Acceptance: no reordering by confidence; deleted excluded by default; provenance retained.
- Rollback: revert.
- Deps: M3.1–M3.4.
- Exclusions: no ranking; no LLM calibration.

### M3.6 — M3 integration, performance & final acceptance
- Scope: full M3 integration over a representative synthetic corpus; parity of structured vs FTS-filtered
  result sets; **true read-only enforcement** (open via `mode=ro` + `query_only`; sqlite_master hash +
  row counts + content hashes + DB file size + JSONL sha256 unchanged before/after a query battery;
  no `ensure_schema`/migration called); secret safety; JSONL immutability; no real `~/.hermes` writes;
  no LLM/network; no M4 behavior; canonical suite green.
- Files: `tests/unit/test_m3_integration.py` (new) + acceptance evidence `acceptance-m3-final.md`.
- Schema impact: none.
- Tests: deterministic integration battery (mirrors M2.7 structure) + the read-only snapshot proof.
- Acceptance: all M3 criteria pass; focused M3 suite green; full canonical suite green (334 + M3
  tests, no decrease); working tree clean; M3 marked VERIFIED; M3 overall IN PROGRESS until this passes.
- Rollback: revert commit; M3 remains the only changed area.
- Deps: M3.1–M3.5.
- Exclusions: no new schema; no M4.

## 16. Files expected to change & schema migration

- **New files:** `src/retrieval/__init__.py`, `src/retrieval/db.py` (true read-only accessor),
  `src/retrieval/models.py`, `src/retrieval/query.py`, `src/retrieval/search.py`, `src/retrieval/views.py`
  (plus focused tests per increment).
- **Reused (read-only):** M2 `src/storage/ingest.py` helpers; M2 migrations 1–6 (read-only version
  check only — M3 never calls `ensure_schema`/`downgrade_to` or reuses the read-write `SQLiteStore`).
- **Schema migration: NONE required.** Justification: every M3 filter maps to an existing `zm_meta`
  column (indexed in M2.5), and relation/scope/artifact/FTS/tombstone queries map to existing
  `zm_relations`/`zm_scopes`/`zm_artifacts`/`zm_fts`/`zm_tombstones`. Structured filtering is plain
  `SELECT ... WHERE` over those columns; FTS reuses `zm_fts`. No new derived table, index, or
  migration is needed for read-only query. A migration would only be justified if a required filter had
  no backing column — none such exists (verified against `ZM_META_COLUMNS` and migrations 1–6).

## 17. Performance acceptance

Synthetic corpus (temp dir, isolated store): ~5,000 events across traces/projects/profiles with
sanitized FTS content, tombstones, relations. Measure baseline on final HEAD, define regression limits
relative to it:
- exact `get_event`: < 5 ms p95.
- indexed structured filter (project+lifecycle): < 20 ms p95.
- FTS `search_text`: < 30 ms p95 (FTS5 available).
- pagination page fetch (limit 50): < 15 ms p95.
No premature cache. If a later benchmark shows a specific filter lacks an index, that becomes a
justified M2 index-addition (a separate M2 increment), not an M3 schema change.

## 18. Acceptance matrix (criterion → test)

| Criterion | Test |
|-----------|------|
| exact event lookup | test_m3_query::test_get_event_exact |
| trace lookup | test_m3_query::test_get_trace_non_deleted |
| project filter | test_m3_query::test_filter_project |
| profile filter | test_m3_query::test_filter_profile |
| session filter | test_m3_query::test_filter_session |
| event-type filter | test_m3_query::test_filter_event_type |
| lifecycle filter | test_m3_query::test_filter_lifecycle_default_excludes_deleted |
| verification filter | test_m3_verification::test_filter_verification |
| time range | test_m3_pagination::test_time_range |
| combined filters | test_m3_query::test_combined_and |
| deterministic ordering | test_m3_pagination::test_deterministic_order |
| pagination | test_m3_pagination::test_pagination_pages |
| invalid cursor | test_m3_pagination::test_invalid_cursor |
| max limit | test_m3_pagination::test_max_limit |
| no duplicates | test_m3_pagination::test_no_duplicates |
| deleted exclusion | test_m3_verification::test_deleted_excluded_by_default |
| archived/superseded | test_m3_verification::test_archived_superseded_included |
| FTS sanitized search | test_m3_search::test_sanitized_search |
| FTS unavailable | test_m3_search::test_fts_unavailable_returns_empty |
| relation lookup | test_m3_relations::test_get_related_both_directions |
| empty result | test_m3_query::test_empty_result |
| malformed query | test_m3_query::test_malformed_query_sanitized_error |
| sanitized errors | test_m3_query::test_sanitized_error_codes |
| secret absence | test_m3_integration::test_secret_absent_in_results |
| JSONL immutability | test_m3_integration::test_jsonl_unchanged |
| SQLite read-only | test_m3_integration::test_read_only_no_mutation |
| no checkpoint mutation | test_m3_integration::test_no_checkpoint_mutation |
| no lifecycle mutation | test_m3_integration::test_no_lifecycle_mutation |
| no tombstone mutation | test_m3_integration::test_no_tombstone_mutation |
| no LLM calls | test_m3_integration::test_no_llm (subprocess/socket guard) |
| no network calls | test_m3_integration::test_no_network |
| no real ~/.hermes | test_m3_integration::test_no_real_hermes_home_writes |
| no M4 behavior | test_m3_integration::test_no_m4_behavior |

Final M3 acceptance runs `.venv/bin/python -m pytest tests/ -q`; canonical count must not decrease
without an explicitly justified test removal.

## 19. Unresolved decisions

**None.** Two candidate decisions were resolved from explicit, approved grounding (not inferred from M2
helper behavior alone):

1. *Default lifecycle visibility* — grounded in **Decision B** (approved M2.6, recorded in
   `project-state.yaml`): `deleted` is a logical deletion excluded from active retrieval helpers, plus
   `IDEA.md` "global read access by default" supports returning all other stored lifecycle states. M3
   default: **exclude `deleted`; include raw/observed/candidate/confirmed/active/superseded/conflicted/
   archived** unless the caller filters `lifecycle_status`; explicit deleted retrieval via M2 admin
   helpers. No NEEDS DECISION.
2. *Ranking* — grounded in the **M3 objective** (defines read-only retrieval/query with no relevance
   score, confidence weighting, recency score, or LLM ranking) and M2.5/M2.7 (ranking excluded from the
   derived layer; `search_fts` returns unranked candidates). M3 uses deterministic stable ordering only;
   ranking reserved for a later milestone if explicitly specified. No silent invention. No NEEDS
   DECISION.

## 20. Final plan validation (Corrections 1–4 + re-checks)

- ✅ No schema migration is required (§16 justified against `ZM_META_COLUMNS` + migrations 1–6).
- ✅ M3 uses a **true read-only** SQLite connection: `file:<db>?mode=ro` + `PRAGMA query_only=ON`
  (`src/retrieval/db.py`); never calls `ensure_schema`/`migrations`/`downgrade_to`; never reuses the
  read-write `SQLiteStore` (§2.1).
- ✅ JSONL remains read-only (resolved, never written; §6 content resolution mode 2).
- ✅ Metadata queries work **without FTS5** (metadata-only mode reads `zm_meta` only; content resolution
  uses canonical JSONL, not FTS) (§6).
- ✅ Content source explicitly defined: metadata-only / JSONL text / FTS snippet / artifact-reference;
  `zm_meta` stores only `content_hash` (no blob); never reconstructed/invented (§6).
- ✅ Zero results (`error=null`), FTS unavailable (`error=fts_unavailable`), and malformed FTS query
  (`error=malformed_fts_expression`) are distinguishable via the typed `SearchResult` contract; no raw
  SQLite text escapes (§9, §10).
- ✅ Pagination cursor is **versioned (`v`) + query-fingerprint-bound (`qf` = SHA-256 of normalized safe
  filters)**; not reversible base64 described as opaque; malformed / unsupported-version /
  fingerprint-mismatch / changed-limit / missing-sort / end-of-results behaviors defined (§8).
- ✅ Deleted records excluded per the approved lifecycle rule (Decision B); other states included by
  default (§5).
- ✅ No authorization policy introduced (scope filters are caller-supplied only; M5 reserved) (§13).
- ✅ No context injection exists (M3 returns data; injection is M7) (§14).
- ✅ No LLM or network calls in the query path (§2, §12).
- ✅ M4 has not started (excluded throughout; M3.6 `test_no_m4_behavior`).
- ✅ Only the M3 plan file changed in this working tree (no source/test/state edits).

M3 PLAN: READY FOR APPROVAL
SQLite access: TRUE READ-ONLY
Schema migration: NONE
Working tree change: M3 plan file only
