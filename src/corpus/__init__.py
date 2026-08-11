"""M10.1 — corpus source registry + authorization boundary (package init).

This package establishes corpus source identity and an append-first registry,
and plugs corpus under the existing M5 authorization model. It performs NO
document ingestion, extraction, normalization, FTS, embeddings, or graph work
(those are M10.2–M10.6). The MEMORY != CORPUS boundary is preserved: corpus
source records live in their own registry store (`corpus_sources.jsonl`), never
in memory JSONL.
"""
from __future__ import annotations

from .contracts import CorpusSourceRecord, ValidationError
from .identity import compute_source_hash, derive_source_id
from .registry import CorpusSourceRegistry

__all__ = [
    "CorpusSourceRecord",
    "ValidationError",
    "compute_source_hash",
    "derive_source_id",
    "CorpusSourceRegistry",
]
