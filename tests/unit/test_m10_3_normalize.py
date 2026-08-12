"""M10.3 — focused unit tests: normalization + deduplication + versioning.

Scope: deterministic normalization of M10.2 extraction; exact dedup by content
hash; deterministic source versioning/supersession; cross-scope authorization
isolation; no LLM/network; no schema change (v9); no M10.4 derived SQLite store;
no FTS/semantic/graph/EvidenceSet retrieval; no real 600-PDF corpus. Fixtures only.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.corpus import (
    CorpusSourceRegistry,
    ExtractionResult,
    ExtractionStatus,
    ExtractionUnit,
    NormalizationResult,
    NormalizationStatus,
    NormalizedUnit,
    ScopeKey,
    UnitDedupIndex,
    build_version_chain,
    compute_source_version_id,
    corpus_content_hash,
    dedup_normalization_result,
    dedup_units,
    normalize_extraction,
    normalize_text,
    unit_content_hash,
    unit_logical_id,
    unit_source_location_id,
)
from src.corpus.dedup import DedupOutcome
from src.corpus.versioning import CorpusVersionChain

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"

# ---------------------------------------------------------------------------
# NORMALIZATION
# ---------------------------------------------------------------------------

def _extract(text_units):
    units = tuple(
        ExtractionUnit(
            unit_id=f"s#src#L{i}",
            kind="text",
            text=t,
            source_ref="s#src",
            order=i,
        )
        for i, t in enumerate(text_units, start=1)
    )
    return ExtractionResult(
        source_ref="s#src",
        status=ExtractionStatus.COMPLETE.value,
        units=units,
        parser_name="builtin:text",
        byte_length=sum(len(t.encode()) for t in text_units),
    )


def test_same_extraction_yields_same_normalized_output():
    content = "alpha  beta\n\ngamma"
    res1 = _extract([content, "second line"])
    res2 = _extract([content, "second line"])
    n1 = normalize_extraction(res1)
    n2 = normalize_extraction(res2)
    assert n1.status == NormalizationStatus.COMPLETE.value
    assert [u.normalized_text for u in n1.units] == [u.normalized_text for u in n2.units]
    assert [u.order for u in n1.units] == [u.order for u in n2.units]


def test_newline_whitespace_normalization_deterministic():
    # CRLF, CR, internal runs, leading/trailing whitespace all collapse to the
    # same normalized form.
    variants = [
        "Hello   world\r\nNext line",
        "Hello   world\nNext line",
        "Hello   world\rNext line",
        "  Hello   world \n Next line  ",
    ]
    normalized = {normalize_text(v) for v in variants}
    assert normalized == {"Hello world Next line"}


def test_unicode_nfc_normalization_deterministic():
    composed = "café"          # single codepoint e-acute
    decomposed = "cafe\u0301"   # base + combining acute
    assert normalize_text(composed) == normalize_text(decomposed)
    assert normalize_text(composed) == "café"


def test_structural_ordering_preserved():
    res = _extract(["first", "second", "third"])
    n = normalize_extraction(res)
    assert [u.order for u in n.units] == [1, 2, 3]
    assert [u.normalized_text for u in n.units] == ["first", "second", "third"]


def test_page_and_parent_provenance_carried_forward():
    eu = ExtractionUnit(
        unit_id="s#p#L1",
        kind="heading",
        text="  Title here  ",
        source_ref="s#p",
        order=1,
        page=3,
        parent_ref="s#p#sec1",
    )
    res = ExtractionResult(source_ref="s#p", status=ExtractionStatus.COMPLETE.value, units=(eu,))
    n = normalize_extraction(res)
    assert n.units[0].normalized_text == "Title here"
    assert n.units[0].page == 3
    assert n.units[0].parent_ref == "s#p#sec1"
    assert n.units[0].kind == "heading"


def test_unknown_coarse_unit_kind_normalizes_to_other():
    eu = ExtractionUnit(
        unit_id="s#x#L1",
        kind="semantic_claim",
        text="some text",
        source_ref="s#x",
        order=1,
    )
    res = ExtractionResult(source_ref="s#x", status=ExtractionStatus.COMPLETE.value, units=(eu,))
    n = normalize_extraction(res)
    assert n.units[0].kind == "other"


def test_empty_units_dropped():
    res = _extract(["", "   ", "real content"])
    n = normalize_extraction(res)
    assert len(n.units) == 1
    assert n.units[0].normalized_text == "real content"


def test_no_semantic_enrichment_occurs():
    # Normalization must not introduce any fact/claim/definition classification.
    res = _extract(["The Earth is round.", "2 + 2 = 4"])
    n = normalize_extraction(res)
    for u in n.units:
        assert u.kind in {"text", "other"}
        assert "fact" not in u.kind and "claim" not in u.kind


def test_extraction_failure_passes_through_no_units():
    res = ExtractionResult(
        source_ref="s#bad",
        status=ExtractionStatus.CORRUPT_SOURCE.value,
        units=(),
        error_reason="corrupt",
    )
    n = normalize_extraction(res)
    assert n.status == NormalizationStatus.FAILED.value
    assert n.units == ()
    assert n.error_reason is not None


def test_empty_source_normalizes_to_empty_status():
    res = ExtractionResult(
        source_ref="s#empty",
        status=ExtractionStatus.EMPTY_SOURCE.value,
        units=(),
        error_reason="no extractable lines",
    )
    n = normalize_extraction(res)
    assert n.status == NormalizationStatus.EMPTY.value
    assert n.units == ()


# ---------------------------------------------------------------------------
# IDENTITY
# ---------------------------------------------------------------------------

def test_same_normalized_unit_stable_content_hash():
    u1 = NormalizedUnit(
        source_location_id="A#L1", normalized_text="repeat me", kind="text",
        source_ref="A", order=1,
    )
    u2 = NormalizedUnit(
        source_location_id="B#L1", normalized_text="repeat me", kind="text",
        source_ref="B", order=1,
    )
    assert unit_content_hash(u1) == unit_content_hash(u2)  # same content
    assert unit_content_hash(u1) == corpus_content_hash("repeat me", "text")


def test_source_location_identity_distinct_across_sources():
    u1 = NormalizedUnit(source_location_id="A#L1", normalized_text="same", kind="text", source_ref="A", order=1)
    u2 = NormalizedUnit(source_location_id="B#L1", normalized_text="same", kind="text", source_ref="B", order=1)
    # Same content hash, but DISTINCT location id + DISTINCT logical id.
    assert unit_content_hash(u1) == unit_content_hash(u2)
    assert unit_source_location_id(u1) != unit_source_location_id(u2)
    assert unit_logical_id(u1) != unit_logical_id(u2)


def test_source_provenance_preserved_on_unit():
    eu = ExtractionUnit(unit_id="S#L5", kind="text", text="keep me", source_ref="S", order=5, page=2)
    res = ExtractionResult(source_ref="S", status=ExtractionStatus.COMPLETE.value, units=(eu,))
    n = normalize_extraction(res)
    assert n.units[0].source_ref == "S"
    assert n.units[0].order == 5
    assert n.units[0].page == 2


# ---------------------------------------------------------------------------
# DEDUP — exact only
# ---------------------------------------------------------------------------

def test_exact_unit_duplicate_detected_within_source():
    u1 = NormalizedUnit(source_location_id="S#L1", normalized_text="dup", kind="text", source_ref="S", order=1)
    u2 = NormalizedUnit(source_location_id="S#L2", normalized_text="dup", kind="text", source_ref="S", order=2)
    index = UnitDedupIndex()
    o1 = index.process(u1)
    o2 = index.process(u2)
    assert o1.is_duplicate is False
    assert o2.is_duplicate is True
    assert o2.duplicate_of == unit_logical_id(u1)
    assert index.duplicate_count == 1


def test_renamed_identical_copy_same_content_hash():
    # Different external location but identical normalized content => same content hash.
    u1 = NormalizedUnit(source_location_id="docA#L1", normalized_text="identical body", kind="text", source_ref="docA", order=1)
    u2 = NormalizedUnit(source_location_id="docB#L1", normalized_text="identical body", kind="text", source_ref="docB", order=1)
    assert unit_content_hash(u1) == unit_content_hash(u2)


def test_no_fuzzy_or_semantic_dedup_path_exists():
    # Two DIFFERENT texts must never collapse.
    u1 = NormalizedUnit(source_location_id="S#L1", normalized_text="machine learning model", kind="text", source_ref="S", order=1)
    u2 = NormalizedUnit(source_location_id="S#L2", normalized_text="machine learning models", kind="text", source_ref="S", order=2)
    index = UnitDedupIndex()
    o1 = index.process(u1)
    o2 = index.process(u2)
    assert o1.is_duplicate is False
    assert o2.is_duplicate is False


def test_same_text_different_authorization_scope_no_collapse():
    # Identical content in Project A vs Project B: content hash shared (physical
    # dedup allowed) but logical unit identities stay DISTINCT => no grant bleed.
    A = NormalizedUnit(source_location_id="A#L1", normalized_text="secret spec", kind="text", source_ref="A", order=1)
    B = NormalizedUnit(source_location_id="B#L1", normalized_text="secret spec", kind="text", source_ref="B", order=1)
    index = UnitDedupIndex()
    oA = index.process(A)
    oB = index.process(B)
    # Not a duplicate: distinct source_ref => distinct logical identity.
    assert oA.is_duplicate is False
    assert oB.is_duplicate is False
    assert unit_logical_id(A) != unit_logical_id(B)
    # But content sharing across scopes IS observed (allowed) without merging.
    assert index.content_shared_across_scopes() is True


def test_dedup_provenance_preserved_not_merged():
    u1 = NormalizedUnit(source_location_id="S#L1", normalized_text="shared", kind="text", source_ref="S", order=1)
    u2 = NormalizedUnit(source_location_id="S#L2", normalized_text="shared", kind="text", source_ref="S", order=2)
    outcomes = dedup_units([u1, u2])
    assert outcomes[1].duplicate_of == unit_logical_id(u1)
    # The duplicate retains its own source location + source_ref (provenance intact).
    assert outcomes[1].source_location_id == "S#L2"


# ---------------------------------------------------------------------------
# VERSIONING
# ---------------------------------------------------------------------------

def _make_record(content, source_id, project_id, content_hash_value, lifecycle="observed"):
    from src.corpus.identity import compute_source_hash, source_descriptor
    from src.corpus.contracts import CorpusSourceRecord, SourceSensitivity, SourceLifecycle

    desc = source_descriptor(external_ref=source_id, kind="txt", project_id=project_id)
    ch = content_hash_value or compute_source_hash(content, desc)
    return CorpusSourceRecord(
        source_id=source_id,
        content_hash=ch,
        external_ref=source_id,
        kind="txt",
        created_at="2026-01-01T00:00:00+00:00",
        project_id=project_id,
        sensitivity=SourceSensitivity.INTERNAL.value,
        lifecycle_status=lifecycle,
    )


def test_unchanged_source_does_not_create_new_version():
    rec = _make_record(b"v1 bytes", "src1", "P", "ch_v1")
    chain = CorpusVersionChain()
    v1 = chain.register_from_record(rec)
    v2 = chain.register_from_record(rec)  # identical re-ingest
    assert v1.source_version_id == v2.source_version_id
    assert chain.version_count("src1") == 1


def test_changed_source_creates_new_version_with_supersedes():
    rec_v1 = _make_record(b"v1 bytes", "src1", "P", "ch_v1")
    rec_v2 = _make_record(b"v2 bytes", "src1", "P", "ch_v2")
    chain = CorpusVersionChain()
    v1 = chain.register_from_record(rec_v1)
    v2 = chain.register_from_record(rec_v2)
    assert chain.version_count("src1") == 2
    assert v2.supersedes == v1.source_version_id
    assert v2.predecessor_content_hash == "ch_v1"
    # Historical version remains fully traceable.
    assert chain.get_versions("src1")[0].content_hash == "ch_v1"


def test_real_registry_output_builds_one_superseding_version_chain(tmp_path):
    reg = CorpusSourceRegistry(root=tmp_path)
    first = reg.register_source(content=b"v1", external_ref="docs/a.txt", kind="txt", project_id="P")
    second = reg.register_source(content=b"v2", external_ref="docs/a.txt", kind="txt", project_id="P")
    chain = build_version_chain(reg.all_records())
    versions = chain.get_versions(first.source_id)
    assert [v.content_hash for v in versions] == [first.content_hash, second.content_hash]
    assert versions[1].supersedes == versions[0].source_version_id


def test_no_silent_overwrite_version_chain_deterministic():
    rec_v1 = _make_record(b"first", "s", "P", "h1")
    rec_v2 = _make_record(b"second", "s", "P", "h2")
    chain = CorpusVersionChain()
    chain.register_from_record(rec_v1)
    chain.register_from_record(rec_v2)
    # Rebuild deterministically from the same records => byte-identical chain.
    rebuilt = build_version_chain([rec_v1, rec_v2])
    assert [v.source_version_id for v in rebuilt.get_versions("s")] == \
           [v.source_version_id for v in chain.get_versions("s")]


def test_cross_scope_same_content_distinct_version():
    recA = _make_record(b"same body", "srcA", "projA", "ch_same")
    recB = _make_record(b"same body", "srcB", "projB", "ch_same")
    chain = CorpusVersionChain()
    vA = chain.register_from_record(recA)
    vB = chain.register_from_record(recB)
    # Content identical but DIFFERENT source + scope => distinct version ids.
    assert vA.source_version_id != vB.source_version_id
    assert vA.source_id != vB.source_id


def test_lifecycle_only_change_is_idempotent_at_version_level():
    rec = _make_record(b"body", "src", "P", "ch_body", lifecycle="observed")
    chain = CorpusVersionChain()
    v1 = chain.register_from_record(rec)
    # Lifecycle-only change with identical content => same version id.
    rec2 = _make_record(b"body", "src", "P", "ch_body", lifecycle="archived")
    v2 = chain.register_from_record(rec2)
    assert v1.source_version_id == v2.source_version_id
    assert chain.version_count("src") == 1


def test_version_id_changes_when_normalization_logic_changes():
    rec = _make_record(b"body", "src", "P", "ch_body")
    v1 = compute_source_version_id(source_id="src", content_hash_value="ch_body", scope=ScopeKey(project_id="P"), normalization_version="m10.3")
    v2 = compute_source_version_id(source_id="src", content_hash_value="ch_body", scope=ScopeKey(project_id="P"), normalization_version="m10.3b")
    assert v1 != v2


# ---------------------------------------------------------------------------
# SECURITY / CANONICAL BOUNDARY
# ---------------------------------------------------------------------------

def test_m6_6_isolation_unchanged_after_m10_3():
    from src.access.contracts import _VALID_RESOURCE_TYPES
    from src.m8.vocabulary import RESOURCE_TYPES

    assert "corpus_source" in _VALID_RESOURCE_TYPES
    assert "corpus_unit" in _VALID_RESOURCE_TYPES
    assert RESOURCE_TYPES == frozenset(_VALID_RESOURCE_TYPES)


def test_normalized_units_not_persisted_into_memory_jsonl(tmp_path, monkeypatch):
    # M10.3 must not write document content into memory JSONL. Exercise the
    # registry path used by M10.1/M10.2 and assert no normalized text leaks.
    reg = CorpusSourceRegistry(root=tmp_path / "corpus")
    content = b"%PDF-1.4 secret finance doc content"
    rec = reg.register_source_with_blob(
        content=content, external_ref="s3://b/a.pdf", kind="pdf", project_id="p1",
    )
    raw = (tmp_path / "corpus" / "corpus_sources.jsonl").read_text()
    assert rec.source_id in raw
    assert "secret finance doc content" not in raw
    # No M10.4 derived SQLite tables exist.
    from src.storage.migrations import MIGRATIONS
    assert max(MIGRATIONS.keys()) == 10


def test_no_schema_migration_pulled_forward():
    from src.storage.migrations import CURRENT_SCHEMA_VERSION
    assert CURRENT_SCHEMA_VERSION == 10


def test_normalization_does_not_bypass_redaction_boundary():
    from src.corpus.redact import scan_extracted_text
    # Redaction boundary remains explicit and is reused; normalization alone
    # must not admit secret-shaped content silently.
    eu = ExtractionUnit(unit_id="S#L1", kind="text", text="api_key=sk-1234567890abcdef", source_ref="S", order=1)
    res = ExtractionResult(source_ref="S", status=ExtractionStatus.COMPLETE.value, units=(eu,))
    n = normalize_extraction(res)
    # Normalization preserves the (still-secret) text verbatim — it does NOT
    # redact. The redaction boundary must be applied separately (as in M10.2).
    assert n.units[0].normalized_text == "api_key=sk-1234567890abcdef"
    assert scan_extracted_text(n.units[0].normalized_text).contained_secret is True


def test_zero_llm_no_network_imports():
    import inspect
    import src.corpus.normalize as nm
    import src.corpus.dedup as dd
    import src.corpus.versioning as vr

    for mod in (nm, dd, vr):
        src = inspect.getsource(mod)
        assert "openai" not in src and "requests" not in src and "httpx" not in src
        assert "import torch" not in src and "transformers" not in src
