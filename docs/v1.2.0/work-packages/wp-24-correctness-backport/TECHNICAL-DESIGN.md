# WP-24 Technical Design — Correctness Backport

**Status:** `VERIFIED`

## Technologies

- Python 3.11+; standard-library `dataclasses`, `enum`, `pathlib`, `sqlite3`, `json`.
- Existing JSONL writer with process locking, append-only serialization, `flush`, and `fsync`.
- Existing SQLite derived migrations/read-only access patterns.
- `pytest` and existing packaging/build helpers.

## Libraries / dependencies

No new runtime dependency. Reuse existing `AppendResult`, `CaptureRejected`, validation, migration metadata, and read-only SQLite conventions. Optional packaging tools may be used only if already available or in the project environment.

## Algorithms

### Capture

```text
capture request
→ existing validation/redaction boundary
→ injected writer.append(event)
→ normalize receipt
→ require canonical_durable == true
→ return CAPTURED with receipt metadata
otherwise
→ return typed non-success with safe reason_code
```

The client never treats a non-raising call as success without a durable receipt. Duplicate handling remains explicit: a duplicate of an already durable canonical event is not a new append, but may be represented as an accepted duplicate status only if the approved compatibility contract allows it; it must never claim a new canonical append.

### Recovery

```text
canonical path validation
→ strict canonical framing/record inspection
→ derived file existence/type check
→ SQLite read-only open
→ inspect sqlite_master / zm_migrations / zm_meta / ingest checkpoint or watermark
→ compare canonical sequence/count with derived progress
→ return typed diagnosis
```

No recovery path writes or repairs data. Unknown/incompatible schema fails closed as a derived-unavailable/incompatible diagnosis rather than querying guessed tables.

## Formulas

- `canonical_durable = append_completed AND flush_completed AND fsync_completed` (owned by the writer; the client only consumes the receipt).
- `derived_stale = derived_watermark < canonical_watermark` when both are valid and comparable.
- No new ranking, confidence, or arbitrary weights in WP-24.

## Variables

| Name | Type | Meaning | Owner |
|---|---|---|---|
| `event_id` | `str` | canonical event identity | event/writer |
| `sequence` | `int >= 0` | canonical append order | writer |
| `canonical_durable` | `bool` | durable JSONL append result | writer receipt |
| `duplicate_class` | `str \| None` | event-id/content duplicate classification | writer |
| `reason_code` | `str \| None` | stable sanitized outcome reason | writer/client |
| `canonical_count` | `int` | validated canonical record count | recovery |
| `canonical_watermark` | `int \| None` | highest validated canonical sequence | recovery |
| `derived_watermark` | `int \| None` | latest projected sequence/checkpoint | recovery |

## Constants

Only closed status/reason values required by the existing contract and tests. No arbitrary timeout, retry, queue, or ranking constant is introduced in WP-24.

## Configuration keys

None added. Existing explicit storage/config paths remain caller-owned; no cwd/HOME inference.

## Data structures

```python
@dataclass(frozen=True)
class AppendReceipt:
    status: str
    event_id: str
    sequence: int | None
    canonical_durable: bool
    duplicate_class: str | None = None
    reason_code: str | None = None
```

If compatibility requires retaining `AppendResult`, it is normalized into `AppendReceipt` at one boundary rather than creating competing stores or contracts.

## Interfaces / signatures

- `EventWriter.append(event) -> AppendReceipt | AppendResult` during bounded compatibility transition.
- `ZeroMemClient.capture(event) -> CaptureResult` with success only for a durable receipt.
- `diagnose(*, canonical_path: Path, derived_path: Path, source_id: str | None = None) -> RecoveryDiagnosis` remains read-only and typed. The caller must provide the ingestion source id when the derived checkpoint uses a stable source id; the secure default is the canonical absolute path and never falls back by basename.

## Schemas / indexes

Recovery must inspect the actual migration/schema vocabulary. At minimum, use `sqlite_master` and existing `zm_*` metadata/checkpoint tables; do not reference `memories`. SQLite remains derived. No migration or new table is created.

## Concurrency model

No new worker or queue. Existing writer thread lock plus Linux `fcntl.flock` remain the canonical append serialization. Recovery opens a short-lived read-only connection.

## Locking model

WP-24 does not alter lock ownership. Writer process lock is bounded to append/load operations. Recovery never acquires a write lock and does not modify WAL/SQLite state.

## Retry policy

No new retry loop. Existing bounded writer behavior remains authoritative. A failed append returns a non-success receipt/status; it is not retried by the client.

## Timeout / deadline

No new deadline. Existing writer/client policy is preserved. Recovery is a bounded local read and fails closed on unreadable/incompatible state.

## Queue / budget limits

Not applicable; no queue or retrieval/context budget is introduced.

## Error / status vocabulary

Capture success: `CAPTURED` only with `canonical_durable=True`. Existing typed non-success vocabulary is preserved where possible (`CAPABILITY_UNAVAILABLE`, `CAPTURE_WRITE_FAILED`, `CAPTURE_WRITER_UNCONFIGURED`) with new explicit reason codes only where required by receipt semantics. Recovery retains `CANONICAL_MISSING`, `CANONICAL_MALFORMED`, `DERIVED_MISSING`, `DERIVED_UNAVAILABLE`, `DERIVED_STALE`, `READY` and may add `DERIVED_CORRUPT`/`SCHEMA_INCOMPATIBLE` if tests and actual schema require them.

## Ordering / tie-break

Canonical order is the writer-provided non-negative `sequence`; no wall-clock inference or database rowid is used.

## Security constraints

- No secret values in receipts, exceptions, logs, or evidence.
- No user-controlled SQL interpolation; schema inspection uses fixed SQL and parameters.
- Read-only SQLite URI and `PRAGMA query_only=ON` where compatible.
- No path traversal or absolute developer path embedded in runtime configuration.
- No authorization behavior is added or bypassed.

## Compatibility constraints

- Preserve v1.1 historical files and evidence.
- Preserve concrete JSONL append-only ordering/dedup/locking.
- No mandatory third-party dependency.
- Linux local filesystem remains the qualified target; unsupported platforms are not claimed.

## Complexity considerations

- Capture append remains amortized O(1) after in-memory indexes, with existing startup/reload O(n) behavior.
- Recovery canonical scan is O(n) in canonical records; SQLite schema inspection is bounded by schema metadata and checkpoint queries.
- No unbounded memory or retry growth is introduced.

## Prohibited approaches

- `CAPTURED` after ignored `append()` return.
- Querying `memories` or inventing an alternate derived schema.
- Repairing canonical JSONL from SQLite.
- Treating projection readiness as canonical durability.
- Adding vector/graph/LLM/cloud dependencies.
- Broad refactor or future-WP implementation.

## Open technical decisions

- `AppendResult` remains the concrete storage type; `ZeroMemClient` normalizes it and validates identity, sequence, and canonical-durable evidence into the public `AppendReceipt` contract. Direct receipts are validated through the same path.
- Current migrations define `zm_meta` and `zm_ingest_checkpoint`; recovery reads only those tables and uses a URI-quoted read-only SQLite path.
