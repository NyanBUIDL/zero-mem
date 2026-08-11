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
from .normalize import (
    NORMALIZATION_VERSION,
    NormalizationError,
    NormalizationResult,
    NormalizationStatus,
    NormalizedUnit,
    normalize_extraction,
    normalize_text,
)
from .dedup import (
    DedupOutcome,
    UnitDedupIndex,
    corpus_content_hash,
    dedup_normalization_result,
    dedup_units,
    unit_content_hash,
    unit_logical_id,
    unit_source_location_id,
)
from .versioning import (
    CorpusSourceVersion,
    CorpusVersionChain,
    ScopeKey,
    build_version_chain,
    compute_source_version_id,
    scope_from_record,
)
from .query_planner import (
    CorpusMetadataFilter,
    CorpusQueryError,
    CorpusQueryPlan,
    VALID_METADATA_KEYS,
    build_query_plan,
    normalize_query_text,
)
from .retrieval import (
    AuthorizedCorpusScope,
    CorpusHit,
    SemanticAdapter,
    NO_SEMANTIC_ADAPTER,
    retrieve_corpus,
)
from .adapters import (
    ADAPTER_REGISTRY,
    FormatAdapter,
    FormatKind,
    PdfAdapter,
    TxtAdapter,
    select_adapter,
)
from .graph import (
    CorpusGraphEdge,
    CorpusGraphError,
    CorpusGraphReadService,
    CorpusGraphResult,
    DEFAULT_GRAPH_BOUNDS,
    GraphReadBounds,
    build_corpus_graph,
    build_corpus_graph_readonly,
)
from .enrichment import (
    ENRICHMENT_PROVENANCE_KIND,
    EnrichmentAdapter,
    EnrichmentItem,
    KeywordEnrichmentAdapter,
    UnitEnrichment,
    enrich_unit,
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
    "NORMALIZATION_VERSION",
    "NormalizationError",
    "NormalizationResult",
    "NormalizationStatus",
    "NormalizedUnit",
    "normalize_extraction",
    "normalize_text",
    "DedupOutcome",
    "UnitDedupIndex",
    "corpus_content_hash",
    "dedup_normalization_result",
    "dedup_units",
    "unit_content_hash",
    "unit_logical_id",
    "unit_source_location_id",
    "CorpusSourceVersion",
    "CorpusVersionChain",
    "ScopeKey",
    "build_version_chain",
    "compute_source_version_id",
    "scope_from_record",
    "CorpusMetadataFilter",
    "CorpusQueryError",
    "CorpusQueryPlan",
    "VALID_METADATA_KEYS",
    "build_query_plan",
    "normalize_query_text",
    "AuthorizedCorpusScope",
    "CorpusHit",
    "SemanticAdapter",
    "NO_SEMANTIC_ADAPTER",
    "retrieve_corpus",
    "ADAPTER_REGISTRY",
    "FormatAdapter",
    "FormatKind",
    "PdfAdapter",
    "TxtAdapter",
    "select_adapter",
    "CorpusGraphEdge",
    "CorpusGraphError",
    "CorpusGraphReadService",
    "CorpusGraphResult",
    "DEFAULT_GRAPH_BOUNDS",
    "GraphReadBounds",
    "build_corpus_graph",
    "build_corpus_graph_readonly",
    "ENRICHMENT_PROVENANCE_KIND",
    "EnrichmentAdapter",
    "EnrichmentItem",
    "KeywordEnrichmentAdapter",
    "UnitEnrichment",
    "enrich_unit",
]
