"""T4 — image adapter with OPTIONAL OCR (png/jpg/jpeg/webp/gif/bmp/tiff).

No runtime dependency. OCR engines are discovered lazily (first image only), in order:
``rapidocr_onnxruntime`` then ``PIL`` + ``pytesseract`` (+ the ``tesseract`` binary).
An engine can also be injected (``ImageAdapter(ocr_engine=callable)``; ``None``/``"off"``
disables OCR) - the callable takes the image bytes and returns text or a sequence of lines.

Outcomes:

- OCR text found      -> ``complete``; ``text`` units, one per blank-line separated block
                         (``#o<n>``, chunked to ~800 chars), ``parser_name`` = ``ocr:<engine>``
- no engine / OCR failed / no text / oversized
                      -> ``partial`` with ONE ``metadata`` unit (``#meta``): format, WxH parsed
                         from the file header with the stdlib, byte size and why OCR did not run,
                         so the source stays findable. ``is_available()`` stays True: a missing
                         optional engine must not count as an extraction failure. Installing an
                         engine later upgrades the source on the next projection.
- not an image / empty -> ``corrupt_source`` / ``empty_source``

The adapter never raises: engine exceptions are reduced to their type name (no message).
"""
from __future__ import annotations

import io
import struct
from dataclasses import dataclass
from typing import Any, Callable, Optional, Union

from .base import FormatAdapter, FormatKind
from ._common import DEFAULT_MAX_UNITS, UnitSink, build_result, normalize_newlines, split_paragraphs
from ..extract import ExtractionResult, ExtractionStatus

DEFAULT_MAX_OCR_BYTES = 25 * 1024 * 1024

OcrEngine = Callable[[bytes], Any]


# ---------------------------------------------------------------------------
# Header parsing (stdlib only)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ImageInfo:
    format: str
    width: Optional[int] = None
    height: Optional[int] = None


_JPEG_SOF = {m for m in range(0xC0, 0xD0)} - {0xC4, 0xC8, 0xCC}
_BMP_DIB_SIZES = {12, 40, 52, 56, 64, 108, 124}


def _jpeg_dims(data: bytes) -> tuple[Optional[int], Optional[int]]:
    i, n = 2, len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
            continue
        if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if marker in (0xD9, 0xDA):
            break
        (length,) = struct.unpack(">H", data[i + 2:i + 4])
        if marker in _JPEG_SOF:
            if i + 9 <= n:
                height, width = struct.unpack(">HH", data[i + 5:i + 9])
                return width, height
            break
        if length < 2:
            break
        i += 2 + length
    return None, None


def _tiff_dims(data: bytes) -> tuple[Optional[int], Optional[int]]:
    end = "<" if data[:2] == b"II" else ">"
    try:
        (ifd,) = struct.unpack(end + "I", data[4:8])
        (count,) = struct.unpack(end + "H", data[ifd:ifd + 2])
        width = height = None
        for k in range(min(count, 64)):
            entry = data[ifd + 2 + 12 * k: ifd + 14 + 12 * k]
            if len(entry) < 12:
                break
            tag, typ = struct.unpack(end + "HH", entry[:4])
            if tag not in (256, 257):
                continue
            if typ == 3:
                (value,) = struct.unpack(end + "H", entry[8:10])
            elif typ == 4:
                (value,) = struct.unpack(end + "I", entry[8:12])
            else:
                continue
            if tag == 256:
                width = value
            else:
                height = value
        return width, height
    except struct.error:
        return None, None


def _webp_dims(data: bytes) -> tuple[Optional[int], Optional[int]]:
    chunk = data[12:16]
    try:
        if chunk == b"VP8X" and len(data) >= 30:
            return (1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little"))
        if chunk == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
            return struct.unpack("<H", data[26:28])[0] & 0x3FFF, struct.unpack("<H", data[28:30])[0] & 0x3FFF
        if chunk == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
            (bits,) = struct.unpack("<I", data[21:25])
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    except struct.error:
        pass
    return None, None


def parse_image_header(data: bytes) -> Optional[ImageInfo]:
    """Format + dimensions from magic bytes / headers, or ``None`` if not a known image.

    Dimensions are ``None`` when the header is recognisable but truncated.
    """
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            if len(data) >= 24 and data[12:16] == b"IHDR":
                w, h = struct.unpack(">II", data[16:24])
                return ImageInfo("png", w, h)
            return ImageInfo("png")
        if data[:3] == b"\xff\xd8\xff":
            w, h = _jpeg_dims(data)
            return ImageInfo("jpeg", w, h)
        if data[:6] in (b"GIF87a", b"GIF89a"):
            if len(data) >= 10:
                w, h = struct.unpack("<HH", data[6:10])
                return ImageInfo("gif", w, h)
            return ImageInfo("gif")
        if data[:2] == b"BM" and len(data) >= 26:
            (dib,) = struct.unpack("<I", data[14:18])
            if dib in _BMP_DIB_SIZES:
                if dib == 12:
                    w, h = struct.unpack("<HH", data[18:22])
                else:
                    w, h = struct.unpack("<ii", data[18:26])
                return ImageInfo("bmp", abs(w), abs(h))
            return None
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            w, h = _webp_dims(data)
            return ImageInfo("webp", w, h)
        if data[:4] in (b"II*\x00", b"MM\x00*") and len(data) >= 8:
            w, h = _tiff_dims(data)
            return ImageInfo("tiff", w, h)
    except Exception:  # defensive: a header parser must never raise
        return None
    return None


# ---------------------------------------------------------------------------
# OCR backends (lazy; absence is a normal condition)
# ---------------------------------------------------------------------------

def _rapidocr_engine() -> OcrEngine:
    from rapidocr_onnxruntime import RapidOCR  # type: ignore

    engine = RapidOCR()

    def run(data: bytes) -> list[str]:
        result, _elapsed = engine(data)
        return _group_boxes_into_lines(result or [])

    return run


def _group_boxes_into_lines(result: Any) -> list[str]:
    """Join per-word OCR boxes ``[quad, text, score]`` into one string per visual line.

    rapidocr emits a box per word/fragment; emitting each as its own line would shred phrases
    (DEF-078). Boxes are grouped by vertical-centre overlap and ordered left to right.
    """
    boxes: list[tuple[float, float, float, str]] = []  # (cy, height, x0, text)
    for item in result:
        try:
            quad, text = item[0], str(item[1])
            ys = [float(pt[1]) for pt in quad]
            xs = [float(pt[0]) for pt in quad]
        except (TypeError, ValueError, IndexError):
            continue
        if text.strip() and ys:
            boxes.append(((min(ys) + max(ys)) / 2, max(ys) - min(ys), min(xs), text.strip()))
    boxes.sort(key=lambda b: b[0])
    lines: list[list[tuple[float, float, float, str]]] = []
    for box in boxes:
        if lines:
            ref = lines[-1][0]
            if abs(box[0] - ref[0]) <= 0.5 * max(box[1], ref[1]):
                lines[-1].append(box)
                continue
        lines.append([box])
    return [" ".join(b[3] for b in sorted(line, key=lambda b: b[2])) for line in lines]


def _tesseract_engine() -> OcrEngine:
    import pytesseract  # type: ignore
    from PIL import Image  # type: ignore

    pytesseract.get_tesseract_version()  # raises when the tesseract binary is missing

    def run(data: bytes) -> str:
        with Image.open(io.BytesIO(data)) as image:
            return pytesseract.image_to_string(image)

    return run


def discover_ocr_engine() -> Optional[tuple[str, OcrEngine]]:
    """First usable engine as ``(name, callable)``, else ``None``. Never raises."""
    for name, factory in (("rapidocr", _rapidocr_engine), ("tesseract", _tesseract_engine)):
        try:
            return name, factory()
        except Exception:
            continue
    return None


def _engine_text(output: Any) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    if isinstance(output, (bytes, bytearray)):
        return bytes(output).decode("utf-8", errors="replace")
    try:
        return "\n".join(str(x) for x in output if x is not None)
    except TypeError:
        return str(output)


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class ImageAdapter(FormatAdapter):
    format = FormatKind.IMAGE
    parser_name = "builtin:image"

    def __init__(
        self,
        ocr_engine: Union[OcrEngine, str, None] = "auto",
        max_ocr_bytes: int = DEFAULT_MAX_OCR_BYTES,
        max_units: int = DEFAULT_MAX_UNITS,
    ) -> None:
        self._setting = ocr_engine
        self._resolved: Optional[tuple[str, OcrEngine]] = None
        self._discovered = False
        self.max_ocr_bytes = max_ocr_bytes
        self.max_units = max_units

    def is_available(self) -> bool:
        return True

    def supports(self, kind_hint: str) -> bool:
        return FormatKind.detect(kind_hint) == FormatKind.IMAGE

    def _engine(self) -> Optional[tuple[str, OcrEngine]]:
        setting = self._setting
        if setting is None or setting == "off":
            return None
        if callable(setting):
            return "custom", setting
        if not self._discovered:  # "auto": discover once, lazily
            self._resolved = discover_ocr_engine()
            self._discovered = True
        return self._resolved

    def extract(self, *, source_ref: str, content: bytes, kind_hint: str) -> ExtractionResult:
        if not content:
            return self._fail(source_ref, ExtractionStatus.EMPTY_SOURCE, "empty source bytes", byte_length=0)
        info = parse_image_header(content)
        if info is None:
            return self._fail(
                source_ref, ExtractionStatus.CORRUPT_SOURCE,
                "not a recognizable image (unknown magic bytes)", byte_length=len(content),
            )
        try:
            return self._extract(source_ref, content, info)
        except Exception as exc:  # defensive
            return self._fail(
                source_ref, ExtractionStatus.ADAPTER_FAILED,
                f"image extraction failure: {type(exc).__name__}", byte_length=len(content),
            )

    def _extract(self, source_ref: str, content: bytes, info: ImageInfo) -> ExtractionResult:
        reason: str
        phrase: str
        engine = self._engine()
        if engine is None:
            reason = "ocr unavailable: install the optional 'ocr' extra (rapidocr-onnxruntime) or pytesseract+Pillow"
            phrase = "ocr unavailable"
        elif len(content) > self.max_ocr_bytes:
            reason = f"ocr skipped: image exceeds {self.max_ocr_bytes} bytes"
            phrase = "ocr skipped (image too large)"
        else:
            name, run = engine
            try:
                text = _engine_text(run(content))
            except Exception as exc:  # never leak the engine's message
                reason = f"ocr failed: {type(exc).__name__}"
                phrase = "ocr failed"
            else:
                if text.strip():
                    return self._ocr_result(source_ref, content, text, name)
                reason = "ocr found no text"
                phrase = "ocr found no text"
        return self._metadata_result(source_ref, content, info, phrase, reason)

    def _ocr_result(self, source_ref: str, content: bytes, text: str, engine_name: str) -> ExtractionResult:
        sink = UnitSink(source_ref, self.max_units)
        for n, (_line, paragraph) in enumerate(split_paragraphs(normalize_newlines(text)), start=1):
            sink.add_chunks(f"o{n}", "text", paragraph)
        return build_result(
            self, sink, source_ref=source_ref, byte_length=len(content),
            empty_reason="ocr produced no text", parser_name=f"ocr:{engine_name}",
        )

    def _metadata_result(
        self, source_ref: str, content: bytes, info: ImageInfo, phrase: str, reason: str,
    ) -> ExtractionResult:
        dims = f" {info.width}x{info.height}" if info.width and info.height else ""
        text = f"image {info.format}{dims}, {len(content)} bytes; {phrase}"
        sink = UnitSink(source_ref, self.max_units)
        sink.add("meta", "metadata", text)
        return ExtractionResult(
            source_ref=source_ref,
            status=ExtractionStatus.PARTIAL.value,
            units=tuple(sink.units),
            parser_name=self.parser_name,
            error_reason=reason,
            byte_length=len(content),
        )


__all__ = ["ImageAdapter", "ImageInfo", "parse_image_header", "discover_ocr_engine"]
