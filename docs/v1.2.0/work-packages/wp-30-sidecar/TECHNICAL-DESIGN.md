# WP-30 Technical Design

## Technology

Python 3.11 standard library; existing M6 contracts/dispatcher and `HermesReadAdapter`; `threading.BoundedSemaphore`, bounded `queue.Queue`, `concurrent.futures` only if required. No new dependency.

## Request flow

```text
transport bytes
→ byte-size validation
→ JSON/object envelope validation
→ explicit identity extraction/preservation
→ bounded admission
→ deadline-bound canonical dispatcher call
→ sanitized M6 response
→ response serialization
→ response-byte validation
```

The adapter never evaluates authorization or retrieves candidates.

## Configuration and bounds

`max_request_bytes`, `max_response_bytes`, `max_concurrency`, `max_queue`, and `default_deadline` are explicit server-owned validated positive values. Client values may only reduce server bounds. Values outside bounds fail closed with typed transport status.

## Concurrency/queue/deadline

Admission uses bounded semaphore/queue. Full admission returns `OVERLOADED`; waiting beyond deadline returns `DEADLINE_EXCEEDED`. No infinite retry. A deadline is propagated to the canonical client/dispatcher where supported; otherwise the adapter bounds admission and marks downstream timeout deterministically.

## Status/error vocabulary

`OK`, `INVALID_REQUEST`, `PAYLOAD_TOO_LARGE`, `OVERLOADED`, `DEADLINE_EXCEEDED`, `DOWNSTREAM_ERROR`, `UNAVAILABLE`, `CLOSED`. Response diagnostics are bounded booleans/codes only; raw exception/path/SQL text is excluded.

## Identity and parity

Identity fields are copied, not inferred or rewritten. Direct API and sidecar use the same capability mapping and dispatcher; parity tests compare normalized status, reason code, items, ordering, and cursor, excluding transport-only metadata.

## Lifecycle/recovery

Open/start/close are idempotent and bounded for transport callers. Admission capacity remains owned until submitted work completes or is cancelled; queued work is cancelled on close, and in-flight callers receive `CLOSED` after shutdown rather than downstream results. An already-running dispatcher callback cannot be forcibly interrupted by Python threads and may finish in the executor; it has no sidecar response authority after close. Restart is performed by the owning integration adapter by creating a fresh sidecar instance.

## Security/prohibited approaches

No transport-local authorization, SQL, JSONL, ranking, candidate filtering, or alternate fallback. No public network listener is introduced in this WP. No secret is logged or serialized.
