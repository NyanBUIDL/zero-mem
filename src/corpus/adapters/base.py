"""M10.2 — Universal FormatAdapter boundary (no PDF/format-specific core coupling).

An adapter turns raw source bytes into a deterministic, coarse-structural
``ExtractionResult``. The corpus core depends only on this protocol — never on
PDF/HTML/DOCX objects. Adding a future adapter (Markdown, HTML, DOCX, CSV, JSON,
source code, logs) requires NO core redesign: register it in ``ADAPTER_REGISTRY``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional

from ..extract import ExtractionError, ExtractionResult, ExtractionStatus


class FormatKind(str, Enum):
    TXT = "txt"
    PDF = "pdf"
    # Shared-memory runtime (T4) adapters. ``select_adapter`` only calls
    # ``supports()``; the enum is the registry de-duplication key (one
    # adapter per ``.format``) and the alias table below.
    MD = "md"
    CSV = "csv"
    JSON = "json"
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    IMAGE = "image"
    # Reserved for future adapters: HTML, CODE, LOG

    @classmethod
    def detect(cls, kind_hint: str) -> "FormatKind | None":
        k = _normalize_hint(kind_hint)
        return _HINT_ALIASES.get(k)


def _normalize_hint(kind_hint: str) -> str:
    """Case-, whitespace- and leading-dot-insensitive hint (``.MD`` == ``md``)."""
    if not isinstance(kind_hint, str):
        return ""
    return kind_hint.lower().strip().lstrip(".")


_HINT_ALIASES: dict[str, FormatKind] = {
    "txt": FormatKind.TXT, "text": FormatKind.TXT, "plaintext": FormatKind.TXT,
    "pdf": FormatKind.PDF,
    "md": FormatKind.MD, "markdown": FormatKind.MD, "mdown": FormatKind.MD, "mkd": FormatKind.MD,
    "csv": FormatKind.CSV, "tsv": FormatKind.CSV,
    "json": FormatKind.JSON, "jsonl": FormatKind.JSON, "ndjson": FormatKind.JSON, "chat": FormatKind.JSON,
    "docx": FormatKind.DOCX,
    "xlsx": FormatKind.XLSX,
    "pptx": FormatKind.PPTX,
    "png": FormatKind.IMAGE, "jpg": FormatKind.IMAGE, "jpeg": FormatKind.IMAGE,
    "webp": FormatKind.IMAGE, "gif": FormatKind.IMAGE, "bmp": FormatKind.IMAGE,
    "tiff": FormatKind.IMAGE, "tif": FormatKind.IMAGE,
}


class FormatAdapter(ABC):
    """Smallest stable contract needed by M10.2."""

    #: The FormatKind this adapter handles.
    format: FormatKind

    #: Human-readable parser name (or "builtin" for stdlib adapters).
    parser_name: str

    @abstractmethod
    def is_available(self) -> bool:
        """True if the underlying parser/dependency is importable & usable."""

    @abstractmethod
    def supports(self, kind_hint: str) -> bool:
        """Whether this adapter can handle the given format hint."""

    @abstractmethod
    def extract(self, *, source_ref: str, content: bytes, kind_hint: str) -> ExtractionResult:
        """Deterministically extract coarse structure from ``content``.

        Must never raise an untyped exception that escapes; on a typed failure
        return an ``ExtractionResult`` with a failure status (or raise
        ``ExtractionError`` which callers convert). Never performs OCR, LLM,
        network, or semantic classification.
        """

    def _fail(self, source_ref: str, status: ExtractionStatus, reason: str,
              byte_length: Optional[int] = None) -> ExtractionResult:
        return ExtractionResult(
            source_ref=source_ref,
            status=status.value,
            error_reason=reason,
            parser_name=self.parser_name,
            byte_length=byte_length,
        )


__all__ = ["FormatKind", "FormatAdapter"]
