# V1.0.0 Architecture Map — Implementation Truth

Zero-Mem v1.0.0 is a local-first Python memory/evidence system. The following is a compact map of the audited implementation, not a v1.1.0 design.

| Layer | Audited modules | Responsibility |
|---|---|---|
| Release surface | `zero_mem/*` | CLI, paths, setup, doctor, backup, upgrade, Hermes descriptor/boundary |
| Capture | `src/integration/*`, `src/capture/*`, `src/redaction/*` | Host hooks, mapping, sanitization, validation, event envelopes |
| Canonical storage | `src/storage/jsonl_capture.py` | Append-only sanitized JSONL and in-process indexes |
| Derived storage | `src/storage/sqlite_store.py`, `src/storage/ingest.py`, `src/storage/migrations/*` | SQLite/WAL/FTS metadata, lifecycle, provenance, relations, scopes |
| Retrieval and access | `src/retrieval/*`, `src/access/*` | Read-only search, pagination, grants and policy enforcement |
| Context selection | `src/integration/m7/*`, `src/m8/*` | Routing, authorized evidence, bounded injection |
| Corpus and projections | `src/corpus/*`, `src/project_memory/*`, `src/projection/*` | Corpus ingestion, blobs, graph/project views, derived projections |

For code-level evidence and detailed behavior, use [SYSTEM_AUDIT.md](../audit/SYSTEM_AUDIT.md). Planned architecture is intentionally separate in [MASTER_PLAN.md](../v1.1.0/MASTER_PLAN.md).
