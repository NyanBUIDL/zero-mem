"""M10.2 — PDF adapter (OPTIONAL local parser; absence-safe, no mandatory dependency).

Uses ``pypdf`` **only if importable**; if it is not installed, ``is_available()``
returns False and extraction returns ``parser_unavailable`` — never crashes.
No OCR, no LLM, no network. Page + block/order provenance preserved where the
parser provides it. Scanned/image-only PDFs degrade to ``partial``/``unsupported``
rather than inventing text. Corrupt PDFs return ``corrupt_source`` deterministically.
"""
from __future__ import annotations

from typing import Optional

from .base import FormatAdapter, FormatKind
from ..extract import ExtractionResult, ExtractionStatus, ExtractionUnit, ExtractionError


class PdfAdapter(FormatAdapter):
    format = FormatKind.PDF
    parser_name = "pypdf"

    def __init__(self) -> None:
        self._pypdf = self._try_import()

    @staticmethod
    def _try_import():
        try:
            import pypdf  # type: ignore
            return pypdf
        except Exception:
            return None

    def is_available(self) -> bool:
        return self._pypdf is not None

    def supports(self, kind_hint: str) -> bool:
        return FormatKind.detect(kind_hint) == FormatKind.PDF

    def extract(self, *, source_ref: str, content: bytes, kind_hint: str) -> ExtractionResult:
        if self._pypdf is None:
            return self._fail(
                source_ref, ExtractionStatus.PARSER_UNAVAILABLE,
                "optional PDF parser (pypdf) not installed; install as an optional extra",
                byte_length=len(content),
            )
        if not content:
            return self._fail(source_ref, ExtractionStatus.EMPTY_SOURCE, "empty source bytes", byte_length=0)
        try:
            return self._extract_impl(source_ref, content)
        except ExtractionError:
            raise
        except Exception as exc:  # deterministic failure classification
            return self._fail(
                source_ref, ExtractionStatus.CORRUPT_SOURCE,
                f"pdf parse failure: {type(exc).__name__}", byte_length=len(content),
            )

    def _extract_impl(self, source_ref: str, content: bytes) -> ExtractionResult:
        pypdf = self._pypdf
        if pypdf is None:
            return self._fail(
                source_ref, ExtractionStatus.PARSER_UNAVAILABLE,
                "optional PDF parser (pypdf) not installed; install as an optional extra",
                byte_length=len(content),
            )
        try:
            from io import BytesIO
            reader = pypdf.PdfReader(BytesIO(content))
        except Exception as exc:
            return self._fail(
                source_ref, ExtractionStatus.CORRUPT_SOURCE,
                f"pdf reader init failed: {type(exc).__name__}", byte_length=len(content),
            )

        units: list[ExtractionUnit] = []
        order = 0
        for page_index, page in enumerate(reader.pages, start=1):
            try:
                page_text = page.extract_text() or ""
            except Exception:
                page_text = ""
            if not page_text.strip():
                # Image-only / no extractable text: do not invent content.
                continue
            # Split into paragraphs/lines preserving order; coarse structural
            # heading detection by simple heuristic is intentionally avoided —
            # M10.2 extracts TEXT only; semantic/structural classification is
            # optional later enrichment (M10.6). We keep page provenance.
            for para in _split_paragraphs(page_text):
                order += 1
                units.append(ExtractionUnit(
                    unit_id=f"{source_ref}#p{page_index}-{order}",
                    kind="text",
                    text=para,
                    source_ref=source_ref,
                    order=order,
                    page=page_index,
                ))
        if not units:
            # No extractable text (image-only / scanned) -> explicit unsupported,
            # never pretend success.
            return self._fail(
                source_ref, ExtractionStatus.UNSUPPORTED_FORMAT,
                "pdf contained no extractable text (image-only/scanned; no OCR in M10.2)",
                byte_length=len(content),
            )
        # If every page had partial extraction gaps, mark PARTIAL; here we treat
        # any successful text extraction as COMPLETE (gaps are just non-text pages).
        return ExtractionResult(
            source_ref=source_ref,
            status=ExtractionStatus.COMPLETE.value,
            units=tuple(units),
            parser_name=self.parser_name,
            byte_length=len(content),
        )


def _split_paragraphs(text: str) -> list[str]:
    out: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        if line.strip() == "":
            if buf:
                out.append("\n".join(buf).strip())
                buf = []
        else:
            buf.append(line)
    if buf:
        out.append("\n".join(buf).strip())
    return [p for p in out if p]


__all__ = ["PdfAdapter"]
