"""T4 — image adapter: stdlib header parsing, real OCR-absent degrade, injected OCR."""
from __future__ import annotations

import builtins
import importlib.util
import re
import sys
import types

import pytest

from src.corpus.adapters import ImageAdapter
from src.corpus.adapters.image import parse_image_header
from src.corpus.extract import ExtractionStatus

from tests.unit.adapters_fixtures import (
    make_bmp,
    make_gif,
    make_jpeg,
    make_png,
    make_tiff,
    make_webp,
)

REF = "SRC"
OCR_LIBS_PRESENT = any(
    importlib.util.find_spec(m) is not None for m in ("rapidocr_onnxruntime", "pytesseract")
)


def _img(content: bytes, hint: str = "png", **kw):
    return ImageAdapter(**kw).extract(source_ref=REF, content=content, kind_hint=hint)


# ---------------------------------------------------------------------------
# Header parsing (stdlib only)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("builder,args,fmt,dims", [
    (make_png, (3, 2), "png", (3, 2)),
    (make_png, (640, 480), "png", (640, 480)),
    (make_jpeg, (17, 9), "jpeg", (17, 9)),
    (make_gif, (5, 4), "gif", (5, 4)),
    (make_bmp, (6, 5), "bmp", (6, 5)),
    (make_webp, (11, 7), "webp", (11, 7)),
    (make_tiff, (13, 8), "tiff", (13, 8)),
])
def test_header_parse_formats_and_dimensions(builder, args, fmt, dims):
    info = parse_image_header(builder(*args))
    assert info is not None
    assert (info.format, info.width, info.height) == (fmt, dims[0], dims[1])


def test_header_parse_big_endian_tiff():
    info = parse_image_header(make_tiff(21, 34, big_endian=True))
    assert (info.format, info.width, info.height) == ("tiff", 21, 34)


def test_header_parse_bmp_negative_height_is_absolute():
    data = bytearray(make_bmp(6, 5))
    data[22:26] = (-5).to_bytes(4, "little", signed=True)
    assert parse_image_header(bytes(data)).height == 5


def test_header_parse_jpeg_skips_non_sof_segments_and_progressive_sof2():
    data = bytearray(make_jpeg(40, 30))
    sof = data.index(b"\xff\xc0")
    data[sof + 1] = 0xC2  # progressive
    info = parse_image_header(bytes(data))
    assert (info.width, info.height) == (40, 30)


@pytest.mark.parametrize("blob", [b"", b"\x89PNG", b"GIF8", b"\xff\xd8", b"BM", b"RIFF", b"hello world", bytes(64)])
def test_header_parse_garbage_returns_none(blob):
    assert parse_image_header(blob) is None


def test_header_parse_truncated_png_keeps_format_without_dimensions():
    info = parse_image_header(make_png()[:12])
    assert info is not None and info.format == "png" and info.width is None


# ---------------------------------------------------------------------------
# Degrade path (no OCR engine)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(OCR_LIBS_PRESENT, reason="an OCR library is installed; absence path not exercised")
def test_default_adapter_degrades_for_real_when_no_ocr_library_is_installed():
    adapter = ImageAdapter()
    assert adapter.is_available() is True
    res = adapter.extract(source_ref=REF, content=make_png(3, 2), kind_hint="png")
    assert res.status == ExtractionStatus.PARTIAL.value
    assert len(res.units) == 1
    unit = res.units[0]
    assert unit.kind == "metadata" and unit.unit_id == f"{REF}#meta"
    assert "png" in unit.text and "3x2" in unit.text and "ocr unavailable" in unit.text
    assert str(len(make_png(3, 2))) in unit.text


@pytest.mark.parametrize("builder,hint,fmt", [
    (make_png, "png", "png"), (make_jpeg, "jpg", "jpeg"), (make_jpeg, "jpeg", "jpeg"),
    (make_gif, "gif", "gif"), (make_bmp, "bmp", "bmp"), (make_webp, "webp", "webp"),
    (make_tiff, "tiff", "tiff"),
])
def test_disabled_ocr_yields_one_metadata_unit_per_format(builder, hint, fmt):
    res = _img(builder(), hint=hint, ocr_engine=None)
    assert res.status == ExtractionStatus.PARTIAL.value
    assert [u.kind for u in res.units] == ["metadata"]
    assert fmt in res.units[0].text and "ocr unavailable" in res.units[0].text
    assert res.error_reason and "ocr" in res.error_reason


def test_metadata_unit_is_deterministic_and_mentions_size():
    a, b = _img(make_png(), ocr_engine=None), _img(make_png(), ocr_engine=None)
    assert a.as_dict() == b.as_dict()


def test_mislabeled_hint_uses_magic_bytes():
    res = _img(make_png(), hint="jpg", ocr_engine=None)
    assert "png" in res.units[0].text


def test_bytes_without_image_magic_are_corrupt_source():
    res = _img(b"this is not an image at all", ocr_engine=None)
    assert res.status == ExtractionStatus.CORRUPT_SOURCE.value and res.error_reason


def test_empty_image_is_empty_source():
    assert _img(b"", ocr_engine=None).status == ExtractionStatus.EMPTY_SOURCE.value


def test_truncated_png_still_findable_without_dimensions():
    res = _img(make_png()[:12], ocr_engine=None)
    assert res.status == ExtractionStatus.PARTIAL.value
    assert "png" in res.units[0].text
    assert re.search(r"\d+x\d+", res.units[0].text) is None


# ---------------------------------------------------------------------------
# OCR present (injected engine)
# ---------------------------------------------------------------------------

def test_injected_ocr_text_becomes_text_units():
    seen: list[bytes] = []

    def fake(data: bytes):
        seen.append(data)
        return "Invoice 2024-001\nTotal due: 500 USD\n\nThank you for your business"

    png = make_png()
    res = _img(png, ocr_engine=fake)
    assert seen == [png]
    assert res.status == ExtractionStatus.COMPLETE.value
    assert [u.kind for u in res.units] == ["text", "text"]
    assert res.units[0].text == "Invoice 2024-001\nTotal due: 500 USD"
    assert res.units[1].text == "Thank you for your business"
    assert [u.unit_id for u in res.units] == [f"{REF}#o1", f"{REF}#o2"]
    assert res.parser_name and "ocr" in res.parser_name


def test_injected_ocr_line_sequence_is_accepted():
    res = _img(make_png(), ocr_engine=lambda b: ["line one", "", "line two", "   "])
    assert [u.text for u in res.units] == ["line one", "line two"]
    assert all(u.kind == "text" for u in res.units)


def test_injected_ocr_long_text_is_chunked():
    res = _img(make_png(), ocr_engine=lambda b: "receipt line item. " * 200)
    assert len(res.units) >= 3 and all(len(u.text) <= 800 for u in res.units)
    assert len({u.unit_id for u in res.units}) == len(res.units)


def test_ocr_engine_failure_degrades_to_metadata_without_leaking_message():
    def boom(_data):
        raise RuntimeError("secret internal detail /home/x")

    res = _img(make_png(), ocr_engine=boom)
    assert res.status == ExtractionStatus.PARTIAL.value
    assert [u.kind for u in res.units] == ["metadata"]
    assert "RuntimeError" in res.error_reason and "secret internal" not in res.error_reason
    assert "ocr failed" in res.units[0].text


@pytest.mark.parametrize("ret", ["", "  \n ", [], None, ["", " "]])
def test_ocr_returning_nothing_degrades_to_metadata(ret):
    res = _img(make_png(), ocr_engine=lambda b: ret)
    assert res.status == ExtractionStatus.PARTIAL.value
    assert [u.kind for u in res.units] == ["metadata"]
    assert "no text" in res.units[0].text


def test_oversized_image_skips_ocr():
    calls = []
    res = _img(make_png(), ocr_engine=lambda b: calls.append(1) or "text", max_ocr_bytes=10)
    assert calls == []
    assert [u.kind for u in res.units] == ["metadata"]


def test_ocr_text_secret_is_not_sanitized_by_adapter():
    res = _img(make_png(), ocr_engine=lambda b: "login password=hunter2")
    assert "hunter2" in res.units[0].text


# ---------------------------------------------------------------------------
# Real backend wrappers against fake third-party modules (API-shape tests)
# ---------------------------------------------------------------------------

@pytest.fixture()
def no_ocr_modules(monkeypatch):
    for name in ("rapidocr_onnxruntime", "pytesseract", "PIL", "PIL.Image"):
        monkeypatch.setitem(sys.modules, name, None)  # None => ImportError on import


def test_rapidocr_backend_wrapper_with_fake_module(monkeypatch, no_ocr_modules):
    class FakeRapidOCR:
        def __call__(self, img):
            assert isinstance(img, (bytes, bytearray))
            return [[[[0, 0], [1, 0], [1, 1], [0, 1]], "Hello OCR", 0.99],
                    [[[0, 2], [1, 2], [1, 3], [0, 3]], "Second line", 0.95]], 0.01

    mod = types.ModuleType("rapidocr_onnxruntime")
    mod.RapidOCR = FakeRapidOCR
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", mod)
    res = _img(make_png())  # default "auto" discovery
    assert res.status == ExtractionStatus.COMPLETE.value
    assert "Hello OCR" in res.units[0].text and "Second line" in " ".join(u.text for u in res.units)
    assert "rapidocr" in res.parser_name


def test_rapidocr_none_result_means_no_text(monkeypatch, no_ocr_modules):
    class FakeRapidOCR:
        def __call__(self, img):
            return None, 0.0

    mod = types.ModuleType("rapidocr_onnxruntime")
    mod.RapidOCR = FakeRapidOCR
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", mod)
    res = _img(make_png())
    assert res.status == ExtractionStatus.PARTIAL.value and res.units[0].kind == "metadata"


def test_tesseract_backend_wrapper_with_fake_modules(monkeypatch, no_ocr_modules):
    pil = types.ModuleType("PIL")
    pil_image = types.ModuleType("PIL.Image")

    class FakeImg:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    pil_image.open = lambda fp: FakeImg()
    pil.Image = pil_image
    tess = types.ModuleType("pytesseract")
    tess.get_tesseract_version = lambda: "5.0"
    tess.image_to_string = lambda im: "Scanned receipt total 42"
    monkeypatch.setitem(sys.modules, "PIL", pil)
    monkeypatch.setitem(sys.modules, "PIL.Image", pil_image)
    monkeypatch.setitem(sys.modules, "pytesseract", tess)
    res = _img(make_png())
    assert res.status == ExtractionStatus.COMPLETE.value
    assert res.units[0].text == "Scanned receipt total 42"
    assert "tesseract" in res.parser_name


def test_tesseract_binary_missing_degrades(monkeypatch, no_ocr_modules):
    pil = types.ModuleType("PIL")
    pil_image = types.ModuleType("PIL.Image")
    pil_image.open = lambda fp: None
    pil.Image = pil_image
    tess = types.ModuleType("pytesseract")

    def missing():
        raise RuntimeError("tesseract is not installed")

    tess.get_tesseract_version = missing
    tess.image_to_string = lambda im: "never"
    monkeypatch.setitem(sys.modules, "PIL", pil)
    monkeypatch.setitem(sys.modules, "PIL.Image", pil_image)
    monkeypatch.setitem(sys.modules, "pytesseract", tess)
    res = _img(make_png())
    assert res.status == ExtractionStatus.PARTIAL.value and res.units[0].kind == "metadata"


def test_backend_discovery_is_lazy_not_at_construction(monkeypatch):
    imported: list[str] = []
    real_import = builtins.__import__

    def spy(name, *a, **k):
        imported.append(name.split(".")[0])
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", spy)
    adapter = ImageAdapter()
    adapter.is_available()
    adapter.supports("png")
    assert not {"rapidocr_onnxruntime", "pytesseract", "PIL"} & set(imported)
