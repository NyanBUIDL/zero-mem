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
    # Reserved for future adapters (not implemented in M10.2):
    # MD, HTML, DOCX, CSV, JSON, CODE, LOG

    @classmethod
    def detect(cls, kind_hint: str) -> "FormatKind | None":
        k = kind_hint.lower().strip()
        if k in ("txt", "text", "plaintext"):
            return cls.TXT
        if k == "pdf":
            return cls.PDF
        return None


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
