# WP-26 Technical Design

## Technologies / dependencies

Python 3.11 standard library: `dataclasses`, `enum`, `queue.Queue`, `threading`, `time`, and `pathlib`. Reuse `src.storage.ingest.ingest_file` and existing SQLite store/checkpoint schema. No new dependency.

## Data structures

```python
class ProjectionStatus(str, Enum):
    CURRENT = "DERIVED_CURRENT"
    PENDING = "DERIVED_PENDING"
    UNAVAILABLE = "DERIVED_UNAVAILABLE"
    CLOSED = "PROJECTION_CLOSED"

@dataclass(frozen=True)
class ProjectionConfig:
    queue_capacity: int
    batch_size: int

@dataclass(frozen=True)
class ProjectionWatermark:
    canonical_sequence: int
    derived_sequence: int
    status: ProjectionStatus
```

## Algorithm

```text
canonical append receipt
  → notification(source_id, source_path, canonical_sequence)
  → bounded queue.put_nowait
  → PENDING when accepted but not committed, or queue full
  → worker consumes notification
  → ingest_file(existing transactional path)
  → derive committed checkpoint/watermark
  → CURRENT only when derived_sequence >= canonical_sequence
  → terminal worker error → UNAVAILABLE
```

A queue-full result is not a canonical append failure. A failed ingestion does not advance the derived watermark. No automatic retry after a terminal worker failure; caller may construct a new coordinator after diagnosis/recovery.

## Variables / limits

- `queue_capacity: int > 0`, coordinator-owned validated bound, supplied by configuration.
- `batch_size: int > 0`, passed only to an implementation that supports bounded batches; otherwise one notification per ingestion call.
- `canonical_sequence`, `derived_sequence: int >= 0`, monotonic watermarks.
- `flush_timeout: float > 0 | None`, caller deadline; no infinite wait.

No default numeric limits are introduced until configuration source is confirmed; tests use explicit values.

## Interfaces

```python
ProjectionCoordinator(config: ProjectionConfig, *, store: DerivedStore, source_reader: ...)
start() -> None
submit(source_path: Path, source_id: str, canonical_sequence: int) -> ProjectionStatus
snapshot() -> ProjectionWatermark
flush(timeout: float | None = None) -> ProjectionStatus
close(timeout: float | None = None) -> None
```

The coordinator owns worker lifecycle but not canonical writer ownership. The derived store is explicit and disposable.

## Database / watermark semantics

`ingest_file` remains the sole writer of ingestion rows/checkpoints. The coordinator reads the committed checkpoint after ingestion and never updates checkpoint metadata independently. A checkpoint is considered current only when it identifies the requested source and its last committed sequence covers the notification watermark.

## Concurrency / locking

One daemon worker thread per coordinator; `queue.Queue(maxsize=queue_capacity)`; a lock protects watermark/status snapshots; `queue.join()` is used only with a finite deadline wrapper. A stuck external projector cannot block process termination; normal ingestion is expected to be bounded. Worker shutdown uses an event and a sentinel. SQLite locking remains in existing store/ingest code.

## Error/status vocabulary

- `PROJECTION_ENQUEUED` — notification accepted by the bounded queue.
- `DERIVED_PENDING` — notification was not accepted because the queue was full; caller must retry explicitly.
- `DERIVED_UNAVAILABLE`
- `PROJECTION_CLOSED`
- `PROJECTION_INVALID_REQUEST`

Statuses are sanitized and do not include exception strings or payload data.

## Security / data integrity

The coordinator is an internal runtime component. `projector` is trusted dependency injection for tests/runtime composition, not a public or transport-controlled callback. Production construction uses `from_ingest()` and the existing read-only canonical ingestion contract. `source_root` is defense-in-depth against accidental path scope errors; adversarial symlink/TOCTOU hardening for user-facing profile/project paths belongs to WP-34.

## Compatibility / complexity

Existing ingestion and WP-25 APIs remain available. Submission is O(1) bounded queue insertion; worker work is bounded by existing ingestion cost; memory is O(queue_capacity). Shutdown is bounded by caller timeout.

## Prohibited approaches

- unbounded queue or thread creation;
- infinite retry/backoff;
- updating watermark before commit;
- declaring current on queue acceptance alone;
- mutating canonical JSONL;
- separate ranking, authorization, or public API path.

## Open decision

The first implementation test must select the narrowest existing derived-store adapter needed to call `ingest_file`. If that adapter requires schema or public API changes, stop and escalate rather than inventing a new storage boundary.
