"""M10.2 — deterministic TXT adapter (stdlib only; flows through FormatAdapter)."""
from __future__ import annotations

from typing import Optional

from .base import FormatAdapter, FormatKind
from ..extract import ExtractionResult, ExtractionStatus, ExtractionUnit


class TxtAdapter(FormatAdapter):
    """Plain-text extraction: deterministic line/order provenance, no over-structure."""

    format = FormatKind.TXT
    parser_name = "builtin:text"

    #: Encodings tried in order; first that decodes cleanly wins (deterministic).
    ENCODINGS = ("utf-8", "utf-8-sig", "latin-1")

    def is_available(self) -> bool:
        return True

    def supports(self, kind_hint: str) -> bool:
        return FormatKind.detect(kind_hint) == FormatKind.TXT

    def extract(self, *, source_ref: str, content: bytes, kind_hint: str) -> ExtractionResult:
        if not content:
            return self._fail(source_ref, ExtractionStatus.EMPTY_SOURCE, "empty source bytes", byte_length=0)

        text, decode_ok = self._decode(content)
        if not decode_ok:
            return self._fail(
                source_ref, ExtractionStatus.CORRUPT_SOURCE,
                "undecodable text under configured encodings", byte_length=len(content),
            )

        units = self._structure(source_ref, text)
        status = ExtractionStatus.COMPLETE if units else ExtractionStatus.EMPTY_SOURCE
        if status == ExtractionStatus.EMPTY_SOURCE:
            return self._fail(source_ref, ExtractionStatus.EMPTY_SOURCE, "no extractable lines", byte_length=len(content))
        return ExtractionResult(
            source_ref=source_ref,
            status=status.value,
            units=tuple(units),
            parser_name=self.parser_name,
            byte_length=len(content),
        )

    def _decode(self, content: bytes) -> tuple[str, bool]:
        last_err: Optional[Exception] = None
        for enc in self.ENCODINGS:
            try:
                return content.decode(enc), True
            except UnicodeDecodeError as exc:
                last_err = exc
        # latin-1 is a lossless fallback that always succeeds; if we reached here
        # it means even latin-1 path wasn't taken (shouldn't happen) — treat as corrupt.
        return "", False

    def _structure(self, source_ref: str, text: str) -> list[ExtractionUnit]:
        units: list[ExtractionUnit] = []
        for order, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            units.append(ExtractionUnit(
                unit_id=f"{source_ref}#L{order}",
                kind="text",
                text=line,
                source_ref=source_ref,
                order=order,
            ))
        return units


__all__ = ["TxtAdapter"]
