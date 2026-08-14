# V1.0.0 Current Data Flow — Implementation Truth

```text
Host / Hermes callback
  -> integration payload mapping, redaction, validation
  -> JsonlCaptureStore.append()
  -> canonical sanitized JSONL

Separate host-owned operation
  -> ingest_file()
  -> SQLite/WAL/FTS derived state
  -> access policy + retrieval
  -> M7/M8 evidence selection
  -> agent context or tool response
```

Canonical event JSONL is intended as the durable event source. SQLite/FTS and associated views are derived/rebuildable. Corpus registry/blob storage is separately canonical for corpus content.

This is a statement of audited v1.0.0 behavior. The missing lifecycle guarantees and intended v1.1.0 direction are recorded separately in [FINDINGS_INDEX.md](../audit/FINDINGS_INDEX.md) and [MASTER_PLAN.md](../v1.1.0/MASTER_PLAN.md).
