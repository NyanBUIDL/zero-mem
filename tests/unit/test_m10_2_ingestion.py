"""M10.2 — focused unit tests: multi-format ingestion + structural extraction.

Scope: universal FormatAdapter boundary (PDF + TXT only in M10.2), deterministic
coarse extraction, content-addressed blob store, fail-closed redaction boundary,
registry blob binding, M6.6 isolation unchanged. No LLM/network. No real 600-PDF
corpus. Fixtures only.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from src.corpus import (
    CorpusBlobStore,
    CorpusSourceRegistry,
    ExtractionStatus,
    FormatKind,
    PdfAdapter,
    TxtAdapter,
    select_adapter,
)
from src.corpus.extract import ExtractionResult, ExtractionUnit
from src.corpus.redact import CorpusRedactionError, scan_extracted_text, require_safe

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"
PYPDF_AVAILABLE = importlib.util.find_spec("pypdf") is not None


# ---------------------------------------------------------------------------
# FormatAdapter boundary
# ---------------------------------------------------------------------------
def test_txt_adapter_selected_for_txt():
    assert isinstance(select_adapter("txt"), TxtAdapter)
    assert select_adapter("txt").supports("txt")


def test_pdf_adapter_selected_for_pdf():
    assert isinstance(select_adapter("pdf"), PdfAdapter)


def test_unsupported_format_returns_none():
    assert select_adapter("docx") is None
    assert select_adapter("") is None


def test_future_adapter_can_register_without_core_change():
    # Proves the registry is open for extension without touching corpus core:
    # a new adapter instance is selectable by its `supports()` predicate, and
    # selection iterates the registry in registration order.
    class MdAdapter(TxtAdapter):
        format = FormatKind.TXT  # reuse an existing enum member; only `supports` differs

        def supports(self, kind_hint: str) -> bool:
            return kind_hint.lower() == "md"

    from src.corpus.adapters.registry import ADAPTER_REGISTRY

    adapter = MdAdapter()
    ADAPTER_REGISTRY.append(adapter)  # direct extension, no core change
    try:
        assert select_adapter("md") is adapter
        # Unrelated formats still resolve to their own adapters.
        assert isinstance(select_adapter("txt"), TxtAdapter)
    finally:
        ADAPTER_REGISTRY[:] = [a for a in ADAPTER_REGISTRY if a is not adapter]


# ---------------------------------------------------------------------------
# TXT adapter
# ---------------------------------------------------------------------------
def test_txt_extraction_deterministic_and_ordered():
    content = b"line one\n\nline two\nline three\n"
    res = TxtAdapter().extract(source_ref="s#1", content=content, kind_hint="txt")
    assert res.status == ExtractionStatus.COMPLETE.value
    # Only non-empty lines become units; order reflects sequential line numbers.
    assert [u.text.strip() for u in res.units] == ["line one", "line two", "line three"]
    assert [u.order for u in res.units] == [1, 3, 4]
    assert all(u.kind == "text" for u in res.units)


def test_txt_empty_source_is_empty_status():
    res = TxtAdapter().extract(source_ref="s#e", content=b"   \n\n", kind_hint="txt")
    assert res.status == ExtractionStatus.EMPTY_SOURCE.value


def test_txt_encoding_fallback_latin1():
    # Only latin-1-encodable characters (no em-dash etc.).
    content = "café naïve résumé".encode("latin-1")
    res = TxtAdapter().extract(source_ref="s#enc", content=content, kind_hint="txt")
    assert res.status == ExtractionStatus.COMPLETE.value
    assert res.units[0].text.strip() == "café naïve résumé"


# ---------------------------------------------------------------------------
# PDF adapter (optional parser)
# ---------------------------------------------------------------------------
def test_pdf_adapter_absent_is_parser_unavailable():
    if PYPDF_AVAILABLE:
        pytest.skip("pypdf installed; absence path not exercised")
    adapter = PdfAdapter()
    assert adapter.is_available() is False
    res = adapter.extract(source_ref="s#pdf", content=(FIX / "sample.pdf").read_bytes(), kind_hint="pdf")
    assert res.status == ExtractionStatus.PARSER_UNAVAILABLE.value
    assert res.error_reason and "pypdf" in res.error_reason


def test_pdf_corrupt_is_corrupt_source():
    if not PYPDF_AVAILABLE:
        pytest.skip("pypdf not installed; cannot exercise corrupt path")
    adapter = PdfAdapter()
    res = adapter.extract(source_ref="s#bad", content=(FIX / "corrupt.pdf").read_bytes(), kind_hint="pdf")
    assert res.status == ExtractionStatus.CORRUPT_SOURCE.value


def test_pdf_valid_extraction_has_page_provenance():
    if not PYPDF_AVAILABLE:
        pytest.skip("pypdf not installed; cannot exercise valid path")
    adapter = PdfAdapter()
    content = (FIX / "sample.pdf").read_bytes()
    res = adapter.extract(source_ref="s#ok", content=content, kind_hint="pdf")
    assert res.status == ExtractionStatus.COMPLETE.value
    assert res.units[0].page == 1
    assert "Hello Corpus World" in res.units[0].text


# ---------------------------------------------------------------------------
# Blob store (canonical source artifact; path safety)
# ---------------------------------------------------------------------------
def test_blob_store_roundtrip_and_idempotent(tmp_path):
    store = CorpusBlobStore(root=tmp_path / "corpus")
    assert store.available
    digest = store.put(content=b"hello corpus", source_ref="src1")
    assert store.exists(digest)
    assert store.get(digest) == b"hello corpus"
    # idempotent: second put returns same digest, single physical file
    assert store.put(content=b"hello corpus", source_ref="src1") == digest


def test_blob_store_path_escape_rejected(tmp_path):
    store = CorpusBlobStore(root=tmp_path / "corpus")
    assert store._blob_dir is not None
    with pytest.raises(Exception):
        store._assert_within_root(store._blob_dir.parent.parent / "../escape")


def test_blob_store_unavailable_is_safe():
    store = CorpusBlobStore(root=None, config_path=Path("/no/corpus.yaml"))
    assert store.available is False
    with pytest.raises(Exception):
        store.put(content=b"x", source_ref="s")


# ---------------------------------------------------------------------------
# Redaction boundary (fail-closed, reuses M1)
# ---------------------------------------------------------------------------
def test_redact_detects_secret_in_extracted_text():
    text = "here is my api_key=sk-1234567890abcdef and more"
    outcome = scan_extracted_text(text)
    assert outcome.contained_secret is True
    assert outcome.safe is False


def test_require_safe_raises_on_secret():
    with pytest.raises(CorpusRedactionError):
        require_safe("password=hunter2")


def test_redact_allows_clean_text():
    outcome = scan_extracted_text("This is a normal paragraph about markets.")
    assert outcome.safe is True
    assert outcome.contained_secret is False


# ---------------------------------------------------------------------------
# Registry + blob binding (MEMORY != CORPUS; source bytes in blob only)
# ---------------------------------------------------------------------------
def test_register_source_with_blob_binds_blob_ref_and_persists_bytes(tmp_path):
    reg = CorpusSourceRegistry(root=tmp_path / "corpus")
    content = b"%PDF-1.4 fake finance doc"
    rec = reg.register_source_with_blob(
        content=content, external_ref="s3://b/a.pdf", kind="pdf",
        profile_id="p1", project_id="proj-x",
    )
    assert rec.blob_ref is not None
    # Bytes recoverable from blob store, not in memory JSONL.
    store = CorpusBlobStore(root=tmp_path / "corpus")
    assert store.get(rec.blob_ref) == content
    # Registry JSONL contains record but NOT raw bytes.
    raw = (tmp_path / "corpus" / "corpus_sources.jsonl").read_text()
    assert rec.source_id in raw
    assert b"%PDF-1.4 fake finance doc" not in (tmp_path / "corpus" / "corpus_sources.jsonl").read_bytes()


def test_register_source_with_blob_idempotent_by_content(tmp_path):
    reg = CorpusSourceRegistry(root=tmp_path / "corpus")
    content = b"some source bytes"
    r1 = reg.register_source_with_blob(content=content, external_ref="e1", kind="txt", project_id="p")
    r2 = reg.register_source_with_blob(content=content, external_ref="e1", kind="txt", project_id="p")
    assert r1.source_id == r2.source_id
    assert r1.blob_ref == r2.blob_ref


# ---------------------------------------------------------------------------
# M6.6 isolation unchanged (regression guard within M10.2)
# ---------------------------------------------------------------------------
def test_corpus_resource_types_still_isolated():
    from src.access.contracts import _VALID_RESOURCE_TYPES
    from src.m8.vocabulary import RESOURCE_TYPES

    assert "corpus_source" in _VALID_RESOURCE_TYPES
    assert "corpus_unit" in _VALID_RESOURCE_TYPES
    assert RESOURCE_TYPES == frozenset(_VALID_RESOURCE_TYPES)
