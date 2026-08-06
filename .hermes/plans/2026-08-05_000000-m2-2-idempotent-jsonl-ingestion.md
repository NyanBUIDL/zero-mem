# M2.2 — Idempotent JSONL Metadata Ingestion — Detailed Implementation Plan

**Status:** READY FOR APPROVAL
**Milestone:** M2.2
**Authority:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`, `ARCHITECTURE.md`, `AGENTS.md`,
the approved M2 plan (`dac2f919…`), `acceptance-m2-increment-1.md`, verified M1 JSONL event
contract (`src/capture/validation.py`, `src/storage/jsonl_capture.py`), verified M2.1 SQLite store
(`src/storage/sqlite_store.py`, `src/storage/migrations/`), ADR-M1-001…ADR-M1-007.
**Predecessor state:** M0/M1 VERIFIED; M2.1 VERIFIED (HEAD `f6f010cdb75257bc51ff60cb83ec58092f53af7d`,
canonical suite 191 passed); M2 overall IN PROGRESS.

---

## 1. Objective and non-goals

M2.2 populates the **derived** SQLite `zm_meta` table by reading the canonical M1 JSONL raw event
stream and inserting only derived metadata. It does NOT make SQLite authoritative; JSONL remains the
source of record and SQLite stays a disposable, fully-rebuildable projection (ADR-M1-001).

The ingestion primitive built here is reused by M2.3's `rebuild_from_jsonl()`, but M2.2 itself only
ingests (idempotently, resumably) and does not implement rebuild orchestration, lifecycle/
provenance/relation/scope projection, FTS5 indexing, retention tombstones, retrieval, ranking,
routing, MCP, Obsidian, context injection, or any M2.3+ behavior.

## 2. Canonical source of record

- The M1 JSONL stream (`events-v1.jsonl`, the `JsonlCaptureStore` path) is the **only** authoritative
  input. M2.2 opens it **read-only** as a byte/line stream; it never appends, rewrites, reorders, or
  deletes any JSONL line.
- Each JSONL line is a complete, already-sanitized M1 envelope (redaction + validation enforced at
  M1 capture). M2.2 re-validates each line with `validate_envelope` (reused from
  `src.capture.validation`) as a defensive boundary; a line that fails is *not* a store defect.
- `rebuild_from_jsonl()` (M2.3) will drop derived tables and re-run this ingester; M2.2 provides the
  `ingest_file` primitive that makes that safe and idempotent.

## 3. Reading canonical JSONL records

- A `JsonlEventSource` reader yields, in **file order**, tuples
  `(line_number, raw_line, parsed)` where `parsed` is the `dict` (or `None` if the line is not valid
  JSON). Line numbering is 1-based and stable; it is the deterministic processing order.
- The reader uses text mode with `utf-8` and splits on `\n`. A trailing partial line (file does not end
  with `\n` and the final segment is non-empty) is treated as `invalid_record` (truncation guard) and
  is **not** ingested; the checkpoint stops before it so a later completed append is picked up on
  resume (matches M1 append-only guarantee).
- The source is identified by a **safe source identifier**: `Path(jsonl_path).name` (basename only).
  The full path is never placed in SQLite, checkpoints, failures, or test artifacts (leak guard,
  consistent with M2.1 sanitization).

## 4. Validating each record before ingestion

Reuse `validate_envelope(envelope)` from `src.capture.validation`. A record is ingestable only if:
- it parses as a JSON object, and
- `validate_envelope` returns without raising.

Any `json.JSONDecodeError`, `TypeError`, or `ValueError` from validation → `invalid_record` outcome
with a fixed `failure_class` and a sanitized `diagnostic_code` (never the raw exception text or the
raw line).

## 5. Inserting only derived metadata

The `zm_meta` row is a **direct projection** of envelope fields — no synthesis, no inference:

| zm_meta column | source |
|---|---|
| event_id, trace_id, event_type, source, schema_version, created_at, observed_at, sequence | envelope |
| session_id, profile_id, project_id, task_id, turn_id, parent_trace_id | envelope (optional; `NULL` if absent) |
| lifecycle_status, verification_status, confidence, sensitivity, retention | envelope |
| content_hash | envelope `sanitized_content_hash` |
| redaction_applied | `1` if envelope has non-empty `redaction_audit` else `0` |
| ingested_at | store-generated UTC timestamp |
| origin_jsonl | **safe basename** of the JSONL source |

- `sanitized_content` and `sanitized_content_ref` are **NOT** stored in `zm_meta` (only the hash).
  This guarantees secrets cannot enter the derived row by construction (M1 already redacts; M2.2
  stores nothing secret-bearing).
- No `project_id`/`profile_id`/`session_id`/correlation is **invented**. Absent optional fields are
  stored as `NULL`. Identity is taken only from explicitly-present envelope fields (ADR-M1-006).

## 6. Idempotence by event_id and sanitized_content_hash

Before insert, a single existence check runs inside the record transaction:
`SELECT event_id, content_hash FROM zm_meta WHERE event_id=? OR content_hash=?`.

Outcome resolution (see §16 for exact enum):

- `event_id` present **and** stored `content_hash ==` incoming `content_hash` → `duplicate_event_id`
  (pure duplicate; skip, no insert).
- `event_id` present **but** stored `content_hash !=` incoming `content_hash` →
  `event_id_content_conflict` (keep original; skip insert; report sanitized).
- `event_id` absent **but** `content_hash` present (different event_id) → `duplicate_content_hash`
  (skip insert; do not overwrite; report sanitized).
- neither present → `new_event` (insert, commit).

This makes re-running ingestion (or `rebuild_from_jsonl` in M2.3) idempotent: already-present events
are skipped, never duplicated or overwritten.

## 7. Conflict behavior (same event_id, different content)

`event_id_content_conflict` is **first-write-wins**: the originally-ingested row is retained, the
conflicting later line is ignored for SQLite, and a sanitized failure is recorded. JSONL remains the
authority — both lines still exist in the canonical file, so a rebuild from JSONL is deterministic
and the conflict remains visible in the source. No silent overwrite, no exception into the caller
(consistent with AGENTS prohibited shortcuts).

## 8. Per-record transaction boundaries

- Each ingestable record is processed in its own `BEGIN … COMMIT`. Validation failures and
  duplicates/conflicts are decided **before** the transaction and do not open one.
- A `transaction_failed` (insert/commit raised after validation passed) triggers `ROLLBACK` for that
  record; the record is not in SQLite; ingestion continues with the next line.
- Failed records never leave a partially-written row.

## 9. Deterministic ingestion ordering

Lines are processed strictly in ascending `line_number` (file order). The `sequence` field is
recorded but is **not** a hard gate: multi-session JSONL may interleave sequences, and idempotence by
`event_id`/`content_hash` makes ordering irrelevant to correctness. The checkpoint records
`last_line_number` so resume continues in the same deterministic order.

## 10. Resumable ingestion checkpoints

A new migration (v2) creates `zm_ingest_checkpoint` and `zm_ingest_log`:

```sql
CREATE TABLE zm_ingest_checkpoint (
  jsonl_path          TEXT PRIMARY KEY,   -- safe basename used as source identifier
  last_line_number    INTEGER NOT NULL,   -- highest line fully processed (committed outcome)
  last_event_id       TEXT,
  last_sequence       INTEGER,
  consumed_prefix_hash TEXT NOT NULL,    -- sha256 over exact bytes of lines 1..last_line_number
  updated_at          TEXT NOT NULL
);

CREATE TABLE zm_ingest_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  jsonl_path      TEXT NOT NULL,
  line_number     INTEGER NOT NULL,
  outcome         TEXT NOT NULL,   -- new_event | duplicate_event_id | duplicate_content_hash
                                   -- | event_id_content_conflict | invalid_record
  event_id        TEXT,
  content_hash    TEXT,
  diagnostic_code TEXT,
  recorded_at     TEXT NOT NULL
);
```

- `ingest_file(store, jsonl_path, source)` loads the checkpoint for the source. If absent, it starts at
  line 1 with `consumed_prefix_hash = sha256(b"")`. If present, it **verifies the consumed-prefix hash**
  of the current file (sha256 over the exact bytes of lines 1..`last_line_number`) equals the stored
  `consumed_prefix_hash`. Only if that verification passes does it seek to `last_line_number + 1` and
  continue. (See §14 for the full append-safety contract.)
- `zm_ingest_log` is the committed, sanitized record of every finalized outcome **except**
  `transaction_failed`. Each committed log row is written in the same transaction as the checkpoint
  advance (see §16/§17), so a re-read of the log is the auditable history of what was consumed.
- **No** `basename|size|mtime_ns` fingerprint is used: size and mtime changes from normal appends are
  expected and must NOT be treated as tampering.

## 11. Restart and crash behavior

- On restart, reopen the store (`ensure_schema`), load the checkpoint, **verify the consumed-prefix
  hash** (sha256 over the exact bytes of lines 1..`last_line_number`) against the stored value, seek to
  `last_line_number + 1`, and continue. Committed records persist (WAL + `synchronous`); the next run
  skips them via idempotence.
- Crash before commit: the checkpoint row and `zm_ingest_log` row for that line were **never committed**
  (transaction rolled back), so `last_line_number` still points before the line; resume re-reads and
  re-attempts it. No duplicate, no lost record (the canonical JSONL still has the line).
- Crash after commit: the checkpoint row (with the new `last_line_number` and `consumed_prefix_hash`)
  and `zm_ingest_log` row are durable; resume seeks past the line automatically.
- The M2.1 `synchronous=NORMAL` is adequate for the test harness (WAL survives process kill). For
  production ingestion the plan §6 calls for `synchronous=FULL` (or explicit `fsync` after commit);
  the ingester accepts a store opened with that setting and recommends it for durable ingestion.

## 12. Malformed-line sanitized failure reporting

A malformed line (unparseable JSON or validation failure, or truncation) yields an
`IngestionFailure`:

```python
@dataclass(frozen=True)
class IngestionFailure:
    source_id: str          # safe basename only
    line_number: int        # 1-based, or 0 if undetermined
    failure_class: str      # one of: invalid_record, event_id_content_conflict,
                            #        duplicate_event_id, duplicate_content_hash,
                            #        transaction_failed, source_changed
    diagnostic_code: str    # fixed token, e.g. "json_unparseable", "envelope_missing_field",
                            #        "envelope_invalid_value", "truncation", "txn_commit_failed"
```

The failure carries **only** source identifier, safe line number, fixed failure class, and a fixed
diagnostic code. It contains **no** raw line, no payload, no secret, no exception string, no full
path. For `invalid_record`, `duplicate_event_id`, `duplicate_content_hash`, and
`event_id_content_conflict`, the outcome is **also written to `zm_ingest_log`** in the same transaction
as the checkpoint advance (a committed, sanitized record — not a dead-letter store and not replayed;
boundary #1). `transaction_failed` is recorded only in the in-memory `IngestionReport` and is **not**
written to `zm_ingest_log` and does **not** advance the checkpoint (see §16/§17). All outcomes are
collected in the `IngestionReport` and are returned/assertable by tests.

## 13. Continuing after malformed lines (no dead-letter)

`invalid_record`, `duplicate_event_id`, `duplicate_content_hash`, and `event_id_content_conflict` are
terminal-skip outcomes: each is written to `zm_ingest_log` (committed sanitized record) and the
checkpoint advances past the line; ingestion continues. There is **no** retry, backoff, dead-letter
store, or replay mechanism in M2.2 (explicitly excluded). `transaction_failed` is the sole outcome
that does **not** advance the checkpoint (see §16/§17) so the failing line can be re-attempted on the
next resume; it is reported once in the in-memory `IngestionReport`. JSONL still holds every line, and
a future rebuild can re-evaluate.

## 14. Source file identity and offset tracking

- Identity: safe basename as `source_id` (in `origin_jsonl` and `zm_ingest_checkpoint.jsonl_path`).
- Offset: `last_line_number` in the checkpoint; `last_event_id`/`last_sequence` are recorded for
  diagnostics only (not used as a hard gate).
- **Append-safety contract (consumed-prefix hash, NOT basename|size|mtime_ns):**
  - The checkpoint stores `consumed_prefix_hash = sha256( exact bytes of lines 1..last_line_number )`,
    recomputed incrementally as each line is committed.
  - On resume, the ingester recomputes sha256 over the **exact bytes** of the current file's lines
    1..`last_line_number` and compares to the stored value.
  - **Allowed (do NOT reject):** normal file growth (more lines appended after the checkpoint);
    an `mtime` change alone; a `size` increase caused by appending (size is not part of the hash, so
    appends do not alter the prefix hash). These are the expected steady-state behaviors.
  - **Rejected (sanitized `source_changed`, ingestion stops — no silent merge):** any modification to
    the **consumed prefix** — i.e. the bytes of any line ≤ `last_line_number` differ from what was
    ingested (reordering, in-place edit, replacement of an already-consumed line, or a
    **truncation below the checkpoint** where the file now has fewer than `last_line_number` lines or
    the prefix bytes no longer match). Recovery from a `source_changed` condition is out of M2.2 scope
    (operator action / later rebuild). This protects derived state from a swapped or corrupted prefix
    while never false-failing on legitimate appends.
  - **No `basename|size|mtime_ns` fingerprint is used**, because size/mtime changes from appends would
    otherwise be (incorrectly) flagged as tampering.

## 15. Secret scanning for SQLite fields and diagnostics

- `zm_meta` stores no secret-bearing content by construction (only hashes, ids, enums, timestamps).
- After ingestion, a `scan_sqlite_for_secrets(store, secret_corpus)` helper asserts that **none** of
  the M1 `SECRET_CORPUS` tokens appear in any `zm_meta` string column **or** in any `IngestionFailure`
  field. This is defense-in-depth: it proves no secret leaked into the derived layer or its
  diagnostics. The corpus is the same synthetic set used by M1 (`SECRET_CORPUS` from
  `src.integration.capture_benchmark` or an M2-local mirror).
- Tests inject a synthetic secret into (a) a malformed line and (b) a valid envelope's
  `sanitized_content` and assert the secret is absent from `zm_meta` and from the failure report.

## 16. Exact duplicate and conflict outcomes (decision #8)

All committed outcomes (every row except `transaction_failed`) also write a sanitized `zm_ingest_log`
row in the same transaction as the checkpoint advance.

| Outcome | Trigger | SQLite effect | Checkpoint | Reported |
|---|---|---|---|---|
| `new_event` | event_id ∉ store, content_hash ∉ store | INSERT `zm_meta` + COMMIT; `zm_ingest_log` row | advance **after** committed `zm_meta` | no (counted) |
| `duplicate_event_id` | event_id ∈ store, same content_hash | no `zm_meta` insert; `zm_ingest_log` row | advance **after** committed log | yes (duplicate) |
| `duplicate_content_hash` | content_hash ∈ store, different event_id | no `zm_meta` insert; `zm_ingest_log` row | advance **after** committed log | yes (duplicate) |
| `event_id_content_conflict` | event_id ∈ store, **different** content_hash | keep original; `zm_ingest_log` row | advance **after** committed log | yes (conflict) |
| `invalid_record` | unparseable JSON / validation failure / truncation | no `zm_meta` insert; `zm_ingest_log` row | advance **after** committed log | yes (failure) |
| `transaction_failed` | validated but INSERT/COMMIT raised | ROLLBACK (no `zm_meta`, no `zm_ingest_log`) | **DO NOT advance** | yes (in-memory `IngestionReport`) |

All six outcomes are returned in the `IngestionReport` with counts; tests assert each.

## 17. Checkpoint advancement rules (decision #7)

The checkpoint (`last_line_number` + `consumed_prefix_hash`) and the `zm_ingest_log` row are written
in one transaction and advance **only after the outcome is durably committed**. Per-outcome rules:

- **`new_event`** → advance **only after the atomic `zm_meta` INSERT + COMMIT** (and its `zm_ingest_log`
  row) is durable. If the commit fails, the transaction rolls back and the checkpoint does not move.
- **`duplicate_event_id`** → advance **after the committed `zm_ingest_log` row** (sanitized duplicate
  record). No `zm_meta` change.
- **`duplicate_content_hash`** → advance **after the committed `zm_ingest_log` row**. No `zm_meta` change.
- **`event_id_content_conflict`** → advance **after the committed `zm_ingest_log` row** (sanitized
  conflict record). Original `zm_meta` row is kept.
- **`invalid_record`** → advance **after the committed `zm_ingest_log` row** (sanitized failure record).
- **`transaction_failed`** → **DO NOT advance.** The `zm_meta` INSERT/commit failed and no `zm_ingest_log`
  row is written; the checkpoint stays at the prior line so the failing line is re-attempted on the
  next resume.
- **Crash before commit** → the transaction rolled back, so the checkpoint was never updated: it still
  points before the line. Resume re-reads and re-attempts that line.
- **Crash after commit** → the committed checkpoint row (new `last_line_number` + `consumed_prefix_hash`)
  and `zm_ingest_log` row are already durable; resume seeks past the line automatically.

Net: the checkpoint moves by exactly one line **after each committed outcome** (new/duplicate/conflict/
invalid). `transaction_failed` and any crash-before-commit are the only cases where it does not advance.

## 18. Preservation of JSONL authority + SQLite rebuildability

- M2.2 never writes to JSONL. All derived state is reconstructable from JSONL via `rebuild_from_jsonl`
  (M2.3) which drops `zm_meta` (+ later derived tables) and re-runs this ingester.
- `zm_migrations` and `zm_ingest_checkpoint` survive a rebuild (schema version + resume cursor);
  `zm_meta` is regenerated.

## 19. Minimal inspection helpers (tests only; no ranking/routing)

Added to `SQLiteStore` (or a thin `ingest.py` accessor), read-only:
- `get_trace(event_id) -> Optional[dict]` — returns the `zm_meta` row for a key.
- `count_metadata() -> int` — row count in `zm_meta`.
- `get_checkpoint(source_id) -> Optional[dict]` — returns the checkpoint row.
These are index/inspection accessors only; no scoring, retrieval selection, or routing.

## 20. Files to create or modify

- **Create** `src/storage/ingest.py` — `JsonlEventSource` reader, `IngestionFailure`,
  `IngestionReport`, `ingest_file(...)`, `scan_sqlite_for_secrets(...)`, minimal helpers.
- **Create** `src/storage/migrations/migrate_2.py` — `up` creates `zm_ingest_checkpoint` (with
  `consumed_prefix_hash`) and `zm_ingest_log`; `down` drops both.
- **Modify** `src/storage/migrations/__init__.py` — register `migrate_2`, set
  `CURRENT_SCHEMA_VERSION = 2`. (Extension of the M2.1 framework; no other source touched.)
- **Create** `tests/unit/test_m2_ingest.py` — focused M2.2 tests.
- (No change to `jsonl_capture.py`, `sqlite_store.py` core, `validation.py`, `project-state.yaml`,
  `implementation-plan.json`, or any M2.1 file beyond the migration registry.)

## 21. Acceptance criteria (each maps to a test or narrow inspection)

| # | Criterion | Test / inspection |
|---|-----------|------------------|
| 1 | Reads canonical JSONL read-only; never mutates it | test: file mtime/size unchanged after ingest; asserts no write |
| 2 | Validates each record via `validate_envelope` | test: valid envelope ingested; malformed rejected |
| 3 | Inserts only derived metadata (no content blob) | test: `sanitized_content` absent from `zm_meta` columns |
| 4 | Idempotent by event_id | test: re-ingest same file → no new rows |
| 5 | Idempotent by content_hash | test: same hash, different id → `duplicate_content_hash`, no insert |
| 6 | `event_id_content_conflict` keeps original | test: same id, different hash → original retained, conflict reported |
| 7 | `new_event` inserted and committed | test: row present, count increments |
| 8 | `duplicate_event_id` skipped | test: same id+hash → no insert, duplicate counted |
| 9 | Per-record transaction boundary | test: injected INSERT failure → ROLLBACK, no row, `transaction_failed` |
| 10 | Deterministic ordering (file order) | test: ingest yields rows in ascending line/sequence order |
| 11 | Resumable checkpoint (seek to last+1) | test: partial ingest + resume → only remaining lines ingested |
| 12 | Checkpoint advances only after committed outcome | test: inspect `zm_ingest_checkpoint.last_line_number` after each committed outcome; `transaction_failed` does NOT advance |
| 13 | Crash/resume no dup/no loss | test: simulate kill after N commits → resume → total == N + rest; checkpoint reflects committed lines only |
| 14 | Malformed-line sanitized report | test: `IngestionFailure` has only source_id/line/class/code; no payload |
| 15 | Continues after malformed (no dead-letter) | test: malformed line in middle → later valid lines still ingested; `zm_ingest_log` row committed |
| 16 | Truncation guard | test: trailing partial line → `invalid_record`, not ingested; file truncated below checkpoint → `source_changed`, stops |
| 17 | Append-safe source integrity | test: appending lines / mtime change / size growth does NOT trigger `source_changed`; consumed-prefix hash matches → resume continues |
| 18 | Consumed-prefix tamper rejected | test: edit/replace/reorder an already-consumed line → `source_changed`, stops, no silent merge |
| 19 | No invented identity | test: absent project_id/profile_id → NULL, never synthesized |
| 20 | Secret scan clean (SQLite + diagnostics) | test: synthetic secret in line → absent from `zm_meta` and `zm_ingest_log`/`IngestionReport` |
| 21 | SQLite rebuildable (JSONL authoritative) | test: drop `zm_meta`, re-ingest from JSONL → identical count/ids |
| 22 | No JSONL mutation / no LLM / no network | test: patch `socket`; assert no network; file unchanged |
| 23 | Sanitized errors only | test: failure/log fields contain no raw exception text or secret |

## 22. Focused and canonical test commands

- **Focused:** `.venv/bin/python -m pytest tests/unit/test_m2_ingest.py -q`
- **Canonical:** `.venv/bin/python -m pytest tests/ -q`

## 23. Rollback strategy

- M2.2 is **additive**: migration v2 adds `zm_ingest_checkpoint`; `ingest.py` is new. Rollback =
  `store.downgrade_to(1)` (drops the checkpoint table) plus removal of `ingest.py`. No canonical
  JSONL is touched.
- If a partial ingestion run must be undone, the derived SQLite is disposable: delete the SQLite file
  (or `downgrade_to(1)` + re-`ensure_schema`) and re-ingest from JSONL. Because JSONL is canonical,
  the derived layer is always reconstructable — there is no destructive operation against the source.
- Transaction failures are already isolated per record (§8), so a bad batch never partially commits.

## 24. Explicitly out of scope for M2.2 (boundary #1)

Dead-letter storage or replay; retry or backoff; lifecycle projection (`zm_lifecycle`); supersession
state; provenance projection beyond the minimum `zm_meta` row (`zm_provenance`); relations
(`zm_relations`) or scopes (`zm_scopes`); FTS5 content indexing (`zm_fts`); retention tombstones;
retrieval, ranking, or query routing; MCP; Obsidian; context injection; and any M2.3+ work
(including `rebuild_from_jsonl` orchestration, though the `ingest_file` primitive it reuses is built
here).
