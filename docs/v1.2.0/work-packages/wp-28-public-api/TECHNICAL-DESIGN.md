# WP-28 Technical Design

## Technologies and dependencies

Python 3.11 standard library, existing `zero_mem` modules, `asyncio`, and `ThreadPoolExecutor`. No new dependency, schema, transport, or database.

## Algorithm

```text
explicit config/identity
→ validate request and lifecycle state
→ map operation to stable capability name
→ call explicit writer/client only where owned
→ normalize to typed result/status
→ sanitize errors
→ return deterministic response
```

Read capability placeholders terminate at `CAPABILITY_UNAVAILABLE` and do not query storage; implementation belongs to later ownership WPs.

## Data structures and statuses

- `CoreConfig`: immutable enabled/project/profile configuration.
- `CaptureResult`: `CAPTURED` or `CAPABILITY_UNAVAILABLE` with reason code.
- `CapabilityResult`: capability, status, sanitized reason, immutable item tuple.
- `Health`: API version, health status, session and writer flags.
- Errors: `ZeroMemAPIError`, `ClientClosedError`, `InvalidRequestError`, `AsyncQueueFullError`, `AsyncTimeoutError`.
- Statuses: `SESSION_ACTIVE`, `SYNCED`, `CAPTURED`, `CAPABILITY_UNAVAILABLE`, `OK`, `SHUTDOWN`, `ALREADY_SHUTDOWN`.

## Interfaces

Public imports are from `zero_mem` only. No public result exposes a writer, SQLite handle, path, SQL, internal `src` object, or transport envelope.

## Concurrency / bounds

Sync client is caller-thread owned. Async client owns one worker and a bounded semaphore (`queue_capacity >= 1`, current default 16). A caller deadline bounds semaphore acquisition and operation wait; timeout raises typed `AsyncQueueFullError` or `AsyncTimeoutError`. Async shutdown closes the client and executor exactly once.

## Locking / retry

The public API does not own canonical storage locks and performs no retry. Writer lifecycle and durability are delegated to the explicit injected writer/runtime owner. Async queue slots are released in `finally`.

## Security and compatibility

No inferred identity, no authorization behavior, no raw payload in error text, no secret persistence, no Hermes import, and no internal storage import. Preserve existing v1.1 `zero_mem` imports and API version independence.

## Complexity

Synchronous lifecycle is O(1) plus writer cost. Async submission is O(1) bounded by queue capacity plus one worker; no unbounded task queue is introduced.

## Prohibited approaches

No retrieve-then-filter, storage exposure, implicit writer/path creation, infinite retry, unbounded queue, transport-specific behavior, new schema, or future-WP capability implementation.

## Open technical decisions

None blocking for WP-28. Capability ownership remains explicitly deferred to WP-29 and later WPs.
