"""T4 — CSV / TSV adapter (stdlib ``csv``).

Units:

- ``h``        the header row -> ``heading`` (``"col1, col2, ..."``)
- ``r<N>``     one ``table`` unit per non-empty data record -> ``"col=value; ..."``
               (``N`` = 1-based record index, header = 1; ``.k`` suffix for chunked long rows);
               ``parent_ref`` = the header unit; empty cells are omitted.

Bounded: ``max_rows`` data rows and ``max_bytes`` input bytes (cut at a line
boundary); either limit yields a ``partial`` result with a reason.
"""
from __future__ import annotations

import csv
import io
from typing import Optional

from .base import FormatAdapter, FormatKind
from ._common import (
    DEFAULT_MAX_UNITS,
    UnitSink,
    build_result,
    collapse_ws,
    decode_text,
    normalize_newlines,
)
from ..extract import ExtractionResult, ExtractionStatus

DEFAULT_MAX_ROWS = 20_000
DEFAULT_MAX_BYTES = 32 * 1024 * 1024

_CANDIDATE_DELIMS = (",", "\t", ";", "|")


def _sniff_delimiter(first_line: str, hint: str) -> str:
    if hint == "tsv" or hint == "tab":
        return "\t"
    # Count candidates outside double quotes on the header line; ties favour the
    # earlier candidate (deterministic, unlike csv.Sniffer's heuristics).
    counts = dict.fromkeys(_CANDIDATE_DELIMS, 0)
    in_quote = False
    for ch in first_line:
        if ch == '"':
            in_quote = not in_quote
        elif not in_quote and ch in counts:
            counts[ch] += 1
    best = max(_CANDIDATE_DELIMS, key=lambda d: (counts[d], -_CANDIDATE_DELIMS.index(d)))
    return best if counts[best] > 0 else ","


class CsvAdapter(FormatAdapter):
    format = FormatKind.CSV
    parser_name = "builtin:csv"

    def __init__(
        self,
        max_rows: int = DEFAULT_MAX_ROWS,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_units: int = DEFAULT_MAX_UNITS,
    ) -> None:
        self.max_rows = max_rows
        self.max_bytes = max_bytes
        self.max_units = max_units

    def is_available(self) -> bool:
        return True

    def supports(self, kind_hint: str) -> bool:
        return FormatKind.detect(kind_hint) == FormatKind.CSV

    def extract(self, *, source_ref: str, content: bytes, kind_hint: str) -> ExtractionResult:
        if not content:
            return self._fail(source_ref, ExtractionStatus.EMPTY_SOURCE, "empty source bytes", byte_length=0)
        notes: list[str] = []
        data = content
        if len(data) > self.max_bytes:
            cut = data.rfind(b"\n", 0, self.max_bytes)
            data = data[: cut if cut > 0 else self.max_bytes]
            notes.append(f"byte cap reached ({self.max_bytes}); remaining rows skipped")
        text = decode_text(data, reject_binary=True)
        if text is None:
            return self._fail(
                source_ref, ExtractionStatus.CORRUPT_SOURCE,
                "binary content (NUL bytes) is not csv text", byte_length=len(content),
            )
        text = normalize_newlines(text)
        first_line = next((ln for ln in text.split("\n") if ln.strip()), "")
        hint = kind_hint.lower().strip().lstrip(".")
        delimiter = _sniff_delimiter(first_line, hint)

        sink = UnitSink(source_ref, self.max_units)
        try:
            error = self._rows(text, delimiter, sink, notes)
        except Exception as exc:  # defensive: never let a parser bug escape
            return self._fail(
                source_ref, ExtractionStatus.ADAPTER_FAILED,
                f"csv failure: {type(exc).__name__}", byte_length=len(content),
            )
        if error and not sink.units:
            return self._fail(source_ref, ExtractionStatus.CORRUPT_SOURCE, error, byte_length=len(content))
        return build_result(
            self, sink, source_ref=source_ref, byte_length=len(content),
            notes=notes, empty_reason="no non-empty csv rows",
        )

    def _rows(self, text: str, delimiter: str, sink: UnitSink, notes: list[str]) -> Optional[str]:
        """Emit units; returns a parse-error reason (also noted) if the reader aborted."""
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
        headers: Optional[list[str]] = None
        header_id: Optional[str] = None
        data_rows = 0
        record_no = 0
        while True:
            try:
                row = next(reader)
            except StopIteration:
                return None
            except csv.Error as exc:
                reason = f"csv parse error at record {record_no + 1}: {type(exc).__name__}"
                notes.append(reason + "; remaining rows skipped")
                return reason
            record_no += 1
            cells = [c.strip() for c in row]
            if not any(cells):
                continue
            if headers is None:
                headers = self._header_names(cells)
                header_id = sink.add_heading("h", ", ".join(headers))
                continue
            if data_rows >= self.max_rows:
                notes.append(f"row cap reached ({self.max_rows}); remaining rows skipped")
                return None
            if sink.full:
                sink.truncated = True
                return None
            data_rows += 1
            pairs = []
            for k, value in enumerate(cells):
                if not value:
                    continue
                name = headers[k] if k < len(headers) else f"col{k + 1}"
                pairs.append(f"{name}={value}")
            if pairs:
                sink.add_chunks(f"r{record_no}", "table", "; ".join(pairs), parent_ref=header_id)

    @staticmethod
    def _header_names(cells: list[str]) -> list[str]:
        return [collapse_ws(c) or f"col{k}" for k, c in enumerate(cells, start=1)]


__all__ = ["CsvAdapter"]
