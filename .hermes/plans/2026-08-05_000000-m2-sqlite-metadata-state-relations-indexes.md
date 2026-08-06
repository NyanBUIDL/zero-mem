# M2 — SQLite Metadata, State, Relations, and Indexes — Implementation Plan

**Status:** READY FOR APPROVAL
**Milestone:** M2
**Authority:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`, `ARCHITECTURE.md`, `AGENTS.md`,
`implementation-plan.json`, `project-state.yaml`, `acceptance-m1-final.md`, verified M1 source.
**Predecessor:** M1 VERIFIED (166 canonical tests; capture rate 100.0%).
**Carried open questions:** OQ-1..OQ-6 (from implementation-plan.json) remain recorded; none blocks M2
schema/ingestion design (see "Open questions" below).

---

## 1. Objective and non-goals

M2 adds a **SQLite derived index/state layer** above the M1 JSONL raw event stream. It does NOT
introduce a competing canonical store, does NOT perform retrieval ranking or query routing
(that is M3), does NOT expose MCP tools (M6), does NOT perform injection (M7), and does NOT build
the Obsidian projection (M9).

M2 makes the sidecar's metadata **rebuildable from canonical JSONL**: SQLite is a projection, never
source-of-record. A `rebuild_from_jsonl()` that reproduces the index state from the raw stream is a
first-class deliverable and a required acceptance gate.

## 2. Storage roles (authoritative vs derived)

- **Authoritative:** versioned append-only JSONL raw event stream (`JsonlCaptureStore`, M1).
  Single source of record for every trace. Never mutated in place by M2.
- **Derived:** SQLite (WAL + FTS5) holding queryable metadata, lifecycle/verification state,
  relations, and search indexes. Rebuildable from JSONL at any time.
- **Separate (referenced only):** versioned artifact store (large tool outputs/documents/diffs).
  M2 indexes artifact *metadata* (id, hash, retention, provenance); artifact *content* file storage
  is deferred to when a downstream milestone needs it (M3/M6). M2 creates the artifact registry table
  but does not yet ingest artifact bytes.

## 3. SQLite schema (initial, version 1)

All tables are prefixed `zm_` to avoid collisions. Envelope field names mirror the M1 contract
exactly. `event_id` and `sanitized_content_hash` are the dedup keys (consistent with M1).

### 3.1 `zm_meta` (core metadata / state table)
```sql
CREATE TABLE zm_meta (
  event_id            TEXT PRIMARY KEY,
  trace_id            TEXT NOT NULL,
  event_type          TEXT NOT NULL,
  source              TEXT NOT NULL,
  schema_version      INTEGER NOT NULL,
  created_at          TEXT NOT NULL,
  observed_at         TEXT NOT NULL,
  sequence            INTEGER NOT NULL,
  session_id          TEXT,
  profile_id          TEXT,
  project_id          TEXT,
  task_id             TEXT,
  turn_id             TEXT,
  parent_trace_id     TEXT,
  lifecycle_status    TEXT NOT NULL,   -- raw/observed/candidate/confirmed/active/superseded/conflicted/archived/deleted
  verification_status TEXT NOT NULL,   -- none/claimed/confirmed/refuted
  confidence          TEXT NOT NULL,
  sensitivity         TEXT NOT NULL,   -- public/internal/private/secret (never secret at rest; M1 rejects)
  retention           TEXT NOT NULL,   -- temporary/session/persistent/never_store
  content_hash        TEXT NOT NULL,   -- sanitized_content_hash (sha256)
  redaction_applied   INTEGER NOT NULL,
  ingested_at         TEXT NOT NULL,   -- when this metadata row was written (audit)
  origin_jsonl        TEXT NOT NULL    -- path of source JSONL (provenance)
);
```

### 3.2 `zm_relations` (entity/link edges)
```sql
CREATE TABLE zm_relations (
  id            INTEGER PRIMARY KEY,
  from_event_id TEXT NOT NULL,
  to_event_id   TEXT NOT NULL,
  relation      TEXT NOT NULL,         -- replaced_by / supersedes / reply_to / child_of / derived_from / conflict_with
  created_at    TEXT NOT NULL,
  UNIQUE (from_event_id, to_event_id, relation)
);
```

### 3.3 `zm_lifecycle` (supersession / active-state history)
```sql
CREATE TABLE zm_lifecycle (
  event_id      TEXT PRIMARY KEY,
  current_state TEXT NOT NULL,         -- mirrors zm_meta.lifecycle_status
  superseded_by TEXT,                  -- event_id of superseding trace, if any
  active_key    TEXT,                  -- entity/scope/state_key tuple for "active is unique" rule
  updated_at    TEXT NOT NULL
);
```

### 3.4 `zm_provenance` (verification records)
```sql
CREATE TABLE zm_provenance (
  event_id            TEXT NOT NULL,
  verification_status TEXT NOT NULL,
  verifier            TEXT NOT NULL,   -- tool_output / test / user_confirmation / deterministic_check / assistant_claim
  evidence_ref        TEXT,            -- trace_id or artifact id of the verifying evidence
  recorded_at         TEXT NOT NULL
);
```
Verified tool output/tests/user confirmation/deterministic verification outrank assistant
self-report (ARCHITECTURE §4). An `assistant_claim` verifier row never sets `confirmed` unless an
independent verifier row exists.

### 3.5 `zm_scopes` (project / profile / knowledge-space mapping)
```sql
CREATE TABLE zm_scopes (
  scope_type   TEXT NOT NULL,          -- project / profile / knowledge_space
  scope_id     TEXT NOT NULL,
  display_name TEXT,
  parent_scope TEXT,
  created_at   TEXT NOT NULL,
  PRIMARY KEY (scope_type, scope_id)
);
```
M1 already resolves `project_id`/`profile_id` explicitly (ADR-M1-006). M2 only records the scopes
actually observed in traces; it creates no inferred scopes and performs no cross-profile writes.

### 3.6 `zm_artifacts` (artifact *metadata* registry; content stored separately later)
```sql
CREATE TABLE zm_artifacts (
  artifact_id   TEXT PRIMARY KEY,
  content_hash  TEXT NOT NULL,
  kind          TEXT,                  -- diff/document/tool_output/attachment
  retention     TEXT NOT NULL,
  origin_event_id TEXT,
  stored_path   TEXT,                  -- file path in separate versioned artifact store (populated later)
  created_at    TEXT NOT NULL
);
```

### 3.7 `zm_fts` (FTS5 search index, rebuildable mirror of sanitized content)
```sql
CREATE VIRTUAL TABLE zm_fts USING fts5(
  event_id UNINDEXED,
  source UNINDEXED,
  session_id UNINDEXED,
  project_id UNINDEXED,
  profile_id UNINDEXED,
  content,                              -- extracted searchable text from sanitized_content (no secrets)
  tokenize = 'unicode61'
);
```

### 3.8 `zm_migrations` (schema version ledger)
```sql
CREATE TABLE zm_migrations (
  version   INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL,
  note       TEXT
);
```

### 3.9 `zm_ingest_checkpoint` (crash-safety cursor)
```sql
CREATE TABLE zm_ingest_checkpoint (
  jsonl_path TEXT PRIMARY KEY,
  last_event_id TEXT,
  last_sequence INTEGER,
  updated_at TEXT NOT NULL
);
```

## 4. Migrations

- Versioned, applied in-order, each wrapped in a transaction. `zm_migrations` records applied
  versions. `current_schema_version = 1`.
- Each migration module is a function `migrate_N_to_M(conn, note)` plus a symmetric
  `rollback_M_to_N(conn, note)`. Rollback is exercised by tests (apply then roll back, assert table
  state returns to prior version and `zm_migrations` reflects it).
- Migration files live in `src/storage/migrations/` (new directory). No destructive migration is
  allowed without an explicit approval gate; M2 migrations are additive only (v1 is the first).

## 5. Idempotent ingestion from JSONL

- Ingestion reads JSONL line-by-line, validates via `validate_envelope` (reuse M1), and writes a
  `zm_meta` row keyed by `event_id`. Duplicate `event_id` or `content_hash` => row skipped (no
  insert), matching M1 dedup semantics. Idempotency lets `rebuild_from_jsonl()` be safely re-run.
- Each JSONL line is ingested inside its own transaction; a failure on one line does not roll back
  prior lines (append-only resilience). A malformed JSONL line (unparseable JSON or envelope
  validation failure) is reported as a **sanitized ingestion failure** (event_id if available, line
  number, failure class, attempt count, sanitized diagnostic message) and ingestion continues.
  M2 implements **no dead-letter store and no replay mechanism** — recording an ingestion failure is
  a reported outcome only, not a persistent store or retry path. (A dead-letter store/replay remains
  out of scope unless separately approved.)
- `zm_ingest_checkpoint` records the highest `sequence`/`event_id` processed per JSONL path so a
  resumed run only ingests new lines (incremental rebuild).

## 6. Transaction and crash safety

- SQLite in WAL mode; `PRAGMA synchronous=FULL` (or `NORMAL` with explicit `fsync` on commit) so a
  committed transaction survives a crash. The raw JSONL already `fsync`s per append (M1).
- Metadata writes are atomic per line; the SQLite commit for a line happens only after the JSONL
  append that produced it is durable. Order of truth: **JSONL first, SQLite second** — SQLite is
  always reconstructable from JSONL, never the reverse.
- No raw JSONL mutation: M2 never rewrites or deletes a JSONL line. If a line fails validation it
  is reported as a sanitized ingestion failure (see §5), not altered in place and not written to a
  dead-letter store (consistent with `JsonlCaptureStore._load` hard-fail on partial/corrupt lines).
- Checkpoint/rebuild is restartable and idempotent (see §5).

## 7. Lifecycle and supersession state

- On ingest, `zm_meta.lifecycle_status` is seeded from the envelope. When a newer trace supersedes
  an older one (detected via `relation_ids` / explicit `replaced_by` relation emitted by a later
  capture), the adapter writes a `zm_relations` edge (`supersedes`/`replaced_by`) and updates
  `zm_lifecycle` so the older `event_id` shows `superseded` and `superseded_by` points to the new
  one.
- "Active is unique per entity/scope/state_key" (ARCHITECTURE §5): `zm_lifecycle.active_key` enforces
  at most one `active` row per key; a new `active` event for an existing key marks the prior one
  `superseded` (never silently overwritten — a resolution/link record is written).
- Supersession is expressed as linked traces, never silent overwrite (AGENTS prohibited shortcuts).

## 8. Provenance and verification records

- Every ingested trace seeds a `zm_provenance` row from its envelope's `verification_status` and a
  deterministic verifier (`deterministic_check` for M1-captured events).
- The verifier-rank ordering (verified tool output / tests / user confirmation / deterministic check
  outrank assistant self-report, ARCHITECTURE §4) is **recorded as data only** in M2. M2 does not
  implement ranking, scoring, retrieval selection, or query routing — those belong to M3/M4. M2
  stores the verifier and evidence_ref so later milestones can apply the ranking.

## 9. Project / profile / knowledge-space relations

- Scopes are derived only from explicitly-resolved `project_id`/`profile_id` (ADR-M1-006). No cwd/
  repo/prompt inference. `zm_scopes` records only observed scopes; no cross-profile writes occur in
  M2. Reads are global by default but profile-first and evidence-bounded (AGENTS §"Reads are
  global by default...").

## 10. Indexing strategy

- Relational indexes: `zm_meta(event_type, project_id, profile_id, session_id, lifecycle_status,
  verification_status, created_at)`, `zm_meta(content_hash)`, `zm_relations(from_event_id,
  to_event_id)`, `zm_lifecycle(active_key, current_state)`, `zm_provenance(event_id, verifier)`.
- FTS5 `zm_fts` over extracted sanitized searchable text (source/session/ids + non-secret fields
  from `sanitized_content`). Secrets cannot appear because M1 rejects `secret` sensitivity at the
  boundary (ADR-M1-004).
- All indexes are rebuildable: `rebuild_from_jsonl()` drops and recreates `zm_meta`, `zm_relations`,
  `zm_lifecycle`, `zm_provenance`, `zm_fts`, `zm_scopes`, then re-ingests. `zm_migrations` and
  `zm_artifacts` are preserved (schema version + artifact registry survive rebuild).

## 11. Retention and deletion behavior

- Retention class is carried from the envelope (`temporary/session/persistent/never_store`).
  `never_store` is already rejected at M1 capture (ADR-M1-004), so it never reaches SQLite.
- **Deletion is tombstone-based, never in-place raw mutation.** A delete request writes
  `lifecycle_status = deleted` in `zm_meta`/`zm_lifecycle` and appends a sanitized tombstone record
  to `data/tombstones/YYYY-MM-DD.jsonl` (event_id, requesting scope, reason, timestamp). The raw
  JSONL line is retained so the index remains rebuildable; the tombstone marks it logically deleted
  and excludes it from default queries.
- Reconciliation with AGENTS prohibited-shortcut "never delete raw traces / superseded decisions":
  raw JSONL is retained by default; physical purging of raw lines is only permitted by an explicit
  retention-expiry policy with a recorded audit row, and only after the tombstone + index update.
  M2 ships tombstone + logical-delete; physical purging is a documented, separately-approved
  operation (flagged, not auto-run).
- Secret-scan (ADR-M1-007) is extended to SQLite: a scanner inspects `zm_meta`, `zm_fts`,
  `zm_provenance`, and tombstone files for any synthetic secret from the M1 secret corpus; tests
  assert absence.

## 12. Tests, acceptance criteria, rollback, smallest increments

### Acceptance criteria (all must pass before M2 is VERIFIED)
1. Metadata rebuildable 100% from JSONL (rebuild produces identical `zm_meta` key set + lifecycle/
   relation state vs incremental ingest).
2. Idempotent ingestion: re-running ingest / rebuild yields no duplicate rows and identical counts.
3. Raw append-first: SQLite never precedes durable JSONL; no JSONL line mutated or deleted in place.
4. Crash safety: an interrupted ingest (killed mid-stream in tests) resumes from checkpoint and
   completes with no lost/duplicated rows.
5. Lifecycle/supersession: supersession links written; active-key uniqueness enforced; no silent
   overwrite.
6. Provenance: every row has a verification record; verifier-rank ordering is **stored as data**
   (verified > self-report), not applied as retrieval ranking in M2.
7. Delete/tombstone workflow tested: logical delete excludes from default queries; raw retained;
   rebuild still reconstructs (tombstone preserved).
8. Migration rollback documented and tested: apply v1, roll back, assert prior state.
9. Secret-scan clean across SQLite + tombstones (no synthetic secret present).
10. No LLM calls in M2 routine operations (deterministic/local only).
11. No installed Hermes source modification; no real `~/.hermes` writes.

### Smallest increments (each independently testable, verified before next)
- **M2.1 Schema + migration framework**: `src/storage/sqlite_store.py` (open/close, WAL, `zm_meta`,
  `zm_migrations`), migration runner with apply/rollback, version check. Tests: open creates schema,
  version recorded, rollback restores.
- **M2.2 Idempotent ingestion**: read JSONL -> `zm_meta` with event_id/content_hash dedup, per-line
  txn, sanitized ingestion-failure reporting on malformed lines (no dead-letter store, no replay),
  `zm_ingest_checkpoint`. Tests: dedup, resume, crash-resume, bad-line isolation.
- **M2.3 Derived state + replay/rebuild**: `zm_lifecycle`, `zm_provenance`, full
  `rebuild_from_jsonl()`. Tests: rebuild equivalence, idempotency, provenance seeding.
- **M2.4 Relations + scopes**: `zm_relations`, `zm_scopes`, `zm_lifecycle` supersession/active-key
  enforcement. Tests: supersession links, active-key uniqueness, no silent overwrite.
- **M2.5 Indexes (FTS5 + relational)**: `zm_fts` build from sanitized content, relational index
  creation, and **minimal inspection helpers only** — low-level lookups that return raw stored rows
  by key (e.g. `get_trace(event_id)` returning the `zm_meta` row, `list_by_project(project_id)`
  returning matching event_ids). These are index/inspection accessors, **not** ranking, scoring,
  retrieval selection, or query routing — those belong to M3/M4. Tests: FTS returns expected ids,
  secrets absent from `zm_fts`.
- **M2.6 Retention/deletion + secret-scan + backup/restore + rollback runbook**: tombstone workflow,
  `zm_artifacts` registry, SQLite secret-scan, `backup()`/`restore()` (copy db + JSONL),
  runbook. Tests: tombstone excludes from queries, raw retained, rebuild reconstructs, scan clean,
  backup/restore round-trip.
- **M2.7 Final M2 acceptance**: run all M2 focused + canonical suite, bind evidence (capture rate
  not applicable; rebuild fidelity is the metric), update state/plan, commit.

### Quality gates (per AGENTS.md)
Each increment: schema/migration coverage, unit + failure tests, structured logs/metrics, provenance
output, security/redaction tests (secret-scan on SQLite), runbook/rollback docs.

## 13. Open questions (carried; none blocks M2)

- **OQ-1** DOCX vs missing .md master — unchanged; DOCX text treated as authority.
- **OQ-2** service framework (FastAPI/local MCP) — M2 is local-only SQLite; no service boundary
  yet. Deferred to M6.
- **OQ-3** numeric thresholds — M2 uses rebuild fidelity (100% key/state parity) as its metric, not
  capture rate. Latency benchmarks deferred to M3.
- **OQ-4** key-management/encryption for private data — M1 already rejects `secret` at boundary, so
  M2 stores only redacted metadata; private-content encryption deferred until a private-persistence
  need is approved with a threat model.
- **OQ-5** cross-profile write authorization — M2 performs no cross-profile writes; enforcement
  deferred to M5.
- **OQ-6** third profile selection — M2 records observed scopes only; no fixed profile set needed.

### Recorded M2 design decisions (not blockers)
- Raw JSONL is immutable; deletion is logical (tombstone) by default, physical purge separately
  approved. This reconciles ARCHITECTURE §7 ("delete ... using tombstones/versioning") with AGENTS
  prohibited-shortcut ("never delete raw traces/superseded decisions"): tombstones preserve
  provenance and rebuildability.
- SQLite is a pure projection: truth order is JSONL-first, SQLite-second; rebuild reproduces index
  state exactly.

---

## 14. Files (planned, not created during planning)

- `src/storage/sqlite_store.py` (M2.1)
- `src/storage/migrations/migrate_1.py` + runner (M2.1)
- `src/storage/ingest.py` (M2.2, M2.3)
- `src/storage/indexes.py` (M2.5)
- `src/storage/retention.py` (M2.6)
- `tests/unit/test_m2_sqlite_*.py`, `tests/integration/test_m2_*.py`
- `runbooks/m2-sqlite.md` (M2.6)
- `acceptance-m2-increment-*.md`, `acceptance-m2-final.md`

## 15. Out of scope for M2 (explicit)
Retrieval ranking/routing (M3), query routing (M4), profile access policy enforcement (M5), MCP
tools (M6), controlled injection (M7), graph/calibration (M8), Obsidian projection (M9), corpus
expansion (M10), vector/embedding index (replaceable adapter, deferred), artifact *content* storage
(registry only in M2).
