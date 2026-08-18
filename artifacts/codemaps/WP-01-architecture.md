# WP-01 Architecture CodeMap

## Existing source owners

- `src/integration/hermes_registration.py`: Hermes adapter registration, observer callback, optional injected writer.
- `src/integration/capture_adapter.py`: mapped event to capture-store adapter.
- `src/storage/jsonl_capture.py`: append-first JSONL canonical raw trace writer with redaction/validation boundary.
- `src/storage/ingest.py`: explicit derived SQLite ingestion/projection path.
- `src/storage/sqlite_store.py`: derived/queryable SQLite substrate.
- `src/access/`: authorization and read/write boundaries.
- `src/retrieval/`: read-only query/FTS/relation/verification surfaces.
- `src/integration/m7/`: bounded context/evidence/injection behavior.
- `zero_mem/`: release lifecycle/CLI/packaging layer; currently no operational public API export.

## Boundary direction

Host adapter → transport-neutral runtime/client → core capture/policy/retrieval/conflict → composite canonical trace contract → rebuildable derived indexes/projections. Core must not import Hermes or transport modules. Adapters may import the public runtime contract.

## Gaps corroborated

1. Writer construction and projection scheduling are not owned by one lifecycle object.
2. Capture append and derived ingest are separate public operations.
3. `zero_mem/__init__.py` exports only `__version__`.
4. Hermes registration can be constructed without a store; behavior is then observation-only/no persistence.
5. Mutable runtime configuration is process-global in `src/integration/zero_mem_runtime.py`.

## Cost/rollback

Prefer a thin facade and adapters over moving existing subsystem implementations. Preserve JSONL/artifacts/approved write-back as append-first provenance; derived SQLite/FTS/graph/projection state remains rebuildable. Rollback is removal of the facade/adapter binding without rewriting canonical traces.
