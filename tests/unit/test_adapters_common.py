"""T4 — shared adapter contract: registry wiring, hint aliases, chunking, decoding.

Covers the cross-cutting guarantees every FormatAdapter must keep: distinct
``.format`` (registry dedup key), deterministic output, unique unit ids per
source, never raising on empty/garbage input, and stdlib-only core formats.
"""
from __future__ import annotations

import random

import pytest

from src.corpus.adapters import (
    ADAPTER_REGISTRY,
    CsvAdapter,
    DocxAdapter,
    FormatKind,
    ImageAdapter,
    JsonAdapter,
    MarkdownAdapter,
    PdfAdapter,
    PptxAdapter,
    TxtAdapter,
    XlsxAdapter,
    select_adapter,
)
from src.corpus.adapters._common import chunk_text, decode_text
from src.corpus.extract import ExtractionResult, ExtractionStatus

from tests.unit.adapters_fixtures import (
    make_docx,
    make_pptx,
    make_png,
    make_xlsx,
)

SUCCESS = {ExtractionStatus.COMPLETE.value, ExtractionStatus.PARTIAL.value}
ALL_STATUS = {s.value for s in ExtractionStatus}

#: (kind hint, expected adapter class)
HINTS = [
    ("txt", TxtAdapter), ("text", TxtAdapter), ("plaintext", TxtAdapter),
    ("md", MarkdownAdapter), ("markdown", MarkdownAdapter),
    ("csv", CsvAdapter), ("tsv", CsvAdapter),
    ("json", JsonAdapter), ("jsonl", JsonAdapter), ("ndjson", JsonAdapter), ("chat", JsonAdapter),
    ("docx", DocxAdapter), ("xlsx", XlsxAdapter), ("pptx", PptxAdapter),
    ("png", ImageAdapter), ("jpg", ImageAdapter), ("jpeg", ImageAdapter), ("webp", ImageAdapter),
    ("gif", ImageAdapter), ("bmp", ImageAdapter), ("tiff", ImageAdapter),
    ("pdf", PdfAdapter),
]


@pytest.mark.parametrize("hint,cls", HINTS)
def test_select_adapter_resolves_every_supported_hint(hint, cls):
    adapter = select_adapter(hint)
    assert isinstance(adapter, cls), (hint, adapter)
    assert adapter.supports(hint)


@pytest.mark.parametrize("hint,cls", [
    (".md", MarkdownAdapter), ("MD", MarkdownAdapter), ("  Markdown ", MarkdownAdapter),
    ("CSV", CsvAdapter), (".TSV", CsvAdapter), ("JSONL", JsonAdapter),
    (".docx", DocxAdapter), ("PNG", ImageAdapter), (".jpeg", ImageAdapter), ("TIF", ImageAdapter),
])
def test_hint_aliases_are_case_and_dot_insensitive(hint, cls):
    assert isinstance(select_adapter(hint), cls)


@pytest.mark.parametrize("hint", ["", "binary", "mp4", "zip", "exe", "doc", "xls", "unknown"])
def test_unsupported_hints_still_resolve_to_none(hint):
    assert select_adapter(hint) is None


def test_every_registered_adapter_has_distinct_format():
    formats = [a.format for a in ADAPTER_REGISTRY]
    assert len(formats) == len(set(formats)), formats
    expected = {
        FormatKind.TXT, FormatKind.PDF, FormatKind.MD, FormatKind.CSV, FormatKind.JSON,
        FormatKind.DOCX, FormatKind.XLSX, FormatKind.PPTX, FormatKind.IMAGE,
    }
    assert expected <= set(formats)


def test_format_kind_detect_maps_hints():
    assert FormatKind.detect("markdown") is FormatKind.MD
    assert FormatKind.detect("ndjson") is FormatKind.JSON
    assert FormatKind.detect("tsv") is FormatKind.CSV
    assert FormatKind.detect("jpeg") is FormatKind.IMAGE
    assert FormatKind.detect("nope") is None


def test_core_adapters_are_available_without_optional_dependencies():
    for cls in (TxtAdapter, MarkdownAdapter, CsvAdapter, JsonAdapter, DocxAdapter,
                XlsxAdapter, PptxAdapter, ImageAdapter):
        assert cls().is_available() is True, cls


# ---------------------------------------------------------------------------
# chunk_text
# ---------------------------------------------------------------------------

def _squash(s: str) -> str:
    return "".join(s.split())


def test_chunk_text_short_text_is_single_chunk():
    assert chunk_text("hello world") == ["hello world"]


def test_chunk_text_empty_and_whitespace():
    assert chunk_text("") == []
    assert chunk_text("  \n\t ") == []


def test_chunk_text_respects_cap_and_is_lossless():
    sentence = "The quick brown fox jumps over the lazy dog. "
    text = sentence * 60  # ~2700 chars
    chunks = chunk_text(text, max_chars=800)
    assert len(chunks) >= 4
    assert all(0 < len(c) <= 800 for c in chunks)
    assert _squash("".join(chunks)) == _squash(text)


def test_chunk_text_prefers_sentence_boundaries():
    text = ("A" * 300 + ". ") + ("B" * 300 + ". ") + ("C" * 300 + ".")
    chunks = chunk_text(text, max_chars=700)
    assert chunks[0].endswith(".")
    assert all(len(c) <= 700 for c in chunks)
    assert _squash("".join(chunks)) == _squash(text)


def test_chunk_text_hard_splits_unbroken_tokens():
    blob = "x" * 5000
    chunks = chunk_text(blob, max_chars=800)
    assert all(len(c) <= 800 for c in chunks)
    assert "".join(chunks) == blob
    assert len(chunks) == 7


def test_chunk_text_prefers_line_boundaries():
    lines = [f"line number {i:03d} with some padding text here" for i in range(40)]
    chunks = chunk_text("\n".join(lines), max_chars=300)
    for c in chunks:
        # no line was cut in half: every chunk line is an original line
        assert all(ln in lines for ln in c.split("\n"))


def test_chunk_text_is_deterministic():
    text = " ".join(f"word{i}" for i in range(2000))
    assert chunk_text(text) == chunk_text(text)


def test_chunk_text_never_splits_surrogate_free_unicode_incorrectly():
    text = "Xin chào thế giới. " * 200
    chunks = chunk_text(text, max_chars=500)
    assert all(len(c) <= 500 for c in chunks)
    assert _squash("".join(chunks)) == _squash(text)


# ---------------------------------------------------------------------------
# decode_text
# ---------------------------------------------------------------------------

def test_decode_text_utf8_bom_is_stripped():
    assert decode_text(b"\xef\xbb\xbfhello") == "hello"


def test_decode_text_utf16_with_bom():
    assert decode_text("héllo\nworld".encode("utf-16")) == "héllo\nworld"
    assert decode_text(b"\xfe\xff" + "abc".encode("utf-16-be")) == "abc"


def test_decode_text_latin1_fallback():
    assert decode_text("café".encode("latin-1")) == "café"


def test_decode_text_binary_rejected_when_requested():
    assert decode_text(b"abc\x00def", reject_binary=True) is None
    assert decode_text(b"abc\x00def", reject_binary=False) is not None


# ---------------------------------------------------------------------------
# Generic invariants across every adapter
# ---------------------------------------------------------------------------

SAMPLES = {
    "txt": (b"alpha paragraph\n\nbeta paragraph\n", "txt"),
    "md": (b"# Title\n\nbody text\n\n```\ncode\n```\n", "md"),
    "csv": (b"a,b\n1,2\n3,4\n", "csv"),
    "tsv": (b"a\tb\n1\t2\n", "tsv"),
    "json": (b'{"k": "v", "n": [1, 2]}', "json"),
    "jsonl": (b'{"role":"user","content":"hi"}\n{"role":"assistant","content":"yo"}\n', "jsonl"),
    "docx": (make_docx([("h", 1, "Head"), ("p", "body")]), "docx"),
    "xlsx": (make_xlsx([("S", [["a", "b"], [1, 2]])]), "xlsx"),
    "pptx": (make_pptx([{"title": "T", "body": ["b"]}]), "pptx"),
    "png": (make_png(), "png"),
}


def _adapter_for(hint: str):
    adapter = select_adapter(hint)
    assert adapter is not None
    return adapter


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_sample_extracts_successfully_with_unique_stable_ids(name):
    content, hint = SAMPLES[name]
    adapter = _adapter_for(hint)
    r1 = adapter.extract(source_ref="SRC", content=content, kind_hint=hint)
    r2 = adapter.extract(source_ref="SRC", content=content, kind_hint=hint)
    assert r1.status in SUCCESS, (name, r1.status, r1.error_reason)
    assert r1.units, name
    assert r1.as_dict() == r2.as_dict()  # determinism
    ids = [u.unit_id for u in r1.units]
    assert len(ids) == len(set(ids)), ids
    assert all(i.startswith("SRC#") for i in ids), ids
    assert all(u.source_ref == "SRC" for u in r1.units)
    orders = [u.order for u in r1.units]
    assert orders == sorted(orders) and len(set(orders)) == len(orders)
    assert all(u.text.strip() for u in r1.units)
    assert r1.byte_length == len(content)
    assert r1.parser_name


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_same_bytes_new_instance_same_unit_ids(name):
    content, hint = SAMPLES[name]
    a = type(_adapter_for(hint))().extract(source_ref="S1", content=content, kind_hint=hint)
    b = type(_adapter_for(hint))().extract(source_ref="S1", content=content, kind_hint=hint)
    assert [u.unit_id for u in a.units] == [u.unit_id for u in b.units]


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_empty_bytes_is_empty_source_never_raises(name):
    _, hint = SAMPLES[name]
    res = _adapter_for(hint).extract(source_ref="S", content=b"", kind_hint=hint)
    assert res.status == ExtractionStatus.EMPTY_SOURCE.value
    assert res.error_reason


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_garbage_bytes_never_raise_and_use_a_typed_status(name):
    _, hint = SAMPLES[name]
    adapter = _adapter_for(hint)
    rng = random.Random(1234)
    for size in (1, 2, 7, 64, 513, 4096):
        blob = bytes(rng.randrange(256) for _ in range(size))
        res = adapter.extract(source_ref="S", content=blob, kind_hint=hint)
        assert isinstance(res, ExtractionResult)
        assert res.status in ALL_STATUS
        if res.status not in SUCCESS:
            assert res.error_reason


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_truncated_input_never_raises(name):
    content, hint = SAMPLES[name]
    adapter = _adapter_for(hint)
    for cut in (1, len(content) // 3, len(content) // 2, len(content) - 1):
        res = adapter.extract(source_ref="S", content=content[:cut], kind_hint=hint)
        assert res.status in ALL_STATUS


def test_headings_are_bounded_and_overflow_is_kept_as_child_text():
    long_heading = "Very long heading words " * 100  # ~2400 chars, no newline
    md = MarkdownAdapter().extract(source_ref="S", content=f"# {long_heading}\n".encode(), kind_hint="md")
    assert md.units[0].kind == "heading" and len(md.units[0].text) <= 800
    assert len(md.units) >= 3
    assert all(u.kind == "text" and u.parent_ref == md.units[0].unit_id for u in md.units[1:])
    assert all(len(u.text) <= 800 for u in md.units)
    kept = "".join("".join(u.text.split()) for u in md.units)
    assert kept == "".join(long_heading.split())

    wide_csv = ("," .join(f"column_{i}" for i in range(500)) + "\n" + ",".join(["1"] * 500) + "\n").encode()
    csv_res = CsvAdapter().extract(source_ref="S", content=wide_csv, kind_hint="csv")
    assert csv_res.units[0].kind == "heading" and all(len(u.text) <= 800 for u in csv_res.units)

    docx = DocxAdapter().extract(
        source_ref="S", content=make_docx([("h", 1, long_heading), ("p", "tail")]), kind_hint="docx")
    assert docx.units[0].kind == "heading" and all(len(u.text) <= 800 for u in docx.units)


def test_unit_sink_clips_unbounded_text_defensively():
    from src.corpus.adapters._common import MAX_UNIT_CHARS, UnitSink, build_result

    sink = UnitSink("S", max_units=10)
    sink.add("a", "text", "x" * (MAX_UNIT_CHARS * 3))
    assert len(sink.units[0].text) == MAX_UNIT_CHARS and sink.clipped == 1
    res = build_result(TxtAdapter(), sink, source_ref="S", byte_length=1)
    assert res.status == ExtractionStatus.PARTIAL.value and "clipped" in res.error_reason


def test_adapters_do_not_sanitize_secrets_the_pipeline_owns_that():
    # Design section 2: "Adapters must not sanitize" - rejection is require_safe's job.
    content = b"# Notes\n\npassword=hunter2 is stored here\n"
    res = MarkdownAdapter().extract(source_ref="S", content=content, kind_hint="md")
    assert any("hunter2" in u.text for u in res.units)
