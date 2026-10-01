"""M10.2 — deterministic TXT adapter (stdlib only; flows through FormatAdapter).

T4: units are **paragraphs** (blank-line separated, long ones chunked to ~800
characters), not single lines. One-line-per-unit hurt recall and ranking for
prose (design section 2). Unit ids stay deterministic and line anchored:
``<source_ref>#L<start_line>`` (``.<k>`` suffix for the k-th extra chunk of a
long paragraph), so a single-line paragraph keeps the id the old per-line
scheme gave it.
"""
from __future__ import annotations

from .base import FormatAdapter, FormatKind
from ._common import (
    DEFAULT_MAX_UNITS,
    UnitSink,
    build_result,
    decode_text,
    normalize_newlines,
    split_paragraphs,
)
from ..extract import ExtractionResult, ExtractionStatus


class TxtAdapter(FormatAdapter):
    """Plain-text extraction: paragraph units with line provenance, no over-structure."""

    format = FormatKind.TXT
    parser_name = "builtin:text"

    #: Encodings tried in order (plus UTF-16 by BOM); first that decodes cleanly wins.
    ENCODINGS = ("utf-8", "utf-8-sig", "latin-1")

    def __init__(self, max_units: int = DEFAULT_MAX_UNITS) -> None:
        self.max_units = max_units

    def is_available(self) -> bool:
        return True

    def supports(self, kind_hint: str) -> bool:
        return FormatKind.detect(kind_hint) == FormatKind.TXT

    def extract(self, *, source_ref: str, content: bytes, kind_hint: str) -> ExtractionResult:
        if not content:
            return self._fail(source_ref, ExtractionStatus.EMPTY_SOURCE, "empty source bytes", byte_length=0)

        text = self._decode(content)
        if text is None:
            return self._fail(
                source_ref, ExtractionStatus.CORRUPT_SOURCE,
                "undecodable text under configured encodings", byte_length=len(content),
            )

        sink = UnitSink(source_ref, self.max_units)
        for start_line, paragraph in split_paragraphs(normalize_newlines(text)):
            if sink.full:
                sink.truncated = True
                break
            sink.add_chunks(f"L{start_line}", "text", paragraph)
        return build_result(
            self, sink, source_ref=source_ref, byte_length=len(content),
            empty_reason="no extractable lines",
        )

    def _decode(self, content: bytes):
        return decode_text(content)


__all__ = ["TxtAdapter"]
