"""M10 — universal knowledge corpus package.

M10.1: corpus source registry + M5 authorization boundary (corpus_source /
corpus_unit resource types). M10.2: multi-format ingestion + structural
extraction (PDF + TXT adapters), content-addressed blob store, fail-closed
redaction boundary. MEMORY != CORPUS: corpus records/bytes never enter memory
JSONL. No LLM, no network. Schema remains v9 (canonical = blob store +
corpus_sources.jsonl).
"""
from .contracts import (
    CORPUS_SOURCE_RESOURCE_TYPE,
    CorpusSourceRecord,
    SourceLifecycle,
    SourceSensitivity,
    ValidationError,
)
from .identity import compute_source_hash, derive_source_id
from .registry import CorpusSourceRegistry
from .blob_store import CorpusBlobStore
from .extract import (
    ExtractionError,
    ExtractionResult,
    ExtractionStatus,
    ExtractionUnit,
    UnitKind,
)
from .redact import (
    CorpusRedactionError,
    RedactionOutcome,
    require_safe,
    scan_extracted_text,
)
from .adapters import (
    ADAPTER_REGISTRY,
    FormatAdapter,
    FormatKind,
    PdfAdapter,
    TxtAdapter,
    select_adapter,
)

__all__ = [
    "CORPUS_SOURCE_RESOURCE_TYPE",
    "CorpusSourceRecord",
    "SourceLifecycle",
    "SourceSensitivity",
    "ValidationError",
    "compute_source_hash",
    "derive_source_id",
    "CorpusSourceRegistry",
    "CorpusBlobStore",
    "ExtractionError",
    "ExtractionResult",
    "ExtractionStatus",
    "ExtractionUnit",
    "UnitKind",
    "CorpusRedactionError",
    "RedactionOutcome",
    "require_safe",
    "scan_extracted_text",
    "ADAPTER_REGISTRY",
    "FormatAdapter",
    "FormatKind",
    "PdfAdapter",
    "TxtAdapter",
    "select_adapter",
]
