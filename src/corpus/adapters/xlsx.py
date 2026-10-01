"""T4 — XLSX adapter (``zipfile`` + streaming ``ElementTree``; no dependencies).

Units (``n`` = 1-based sheet position in ``xl/workbook.xml``, ``row`` = the sheet row number):

- ``s<n>``            sheet name -> ``heading`` (only for sheets with content)
- ``s<n>r<row>``      one ``table`` unit per non-empty row -> ``"a | b | c"`` (non-empty cells
                      in column order; ``.k`` suffix when a very long row is chunked);
                      ``parent_ref`` = the sheet heading

Cell values are shown as stored: shared / inline strings resolved, numbers raw (dates
therefore stay serial numbers or ISO ``t="d"`` text), booleans ``TRUE``/``FALSE``, errors
as their code, formulas as their cached value (no cached value -> cell skipped). Sheets
are streamed; a malformed sheet is skipped and the result becomes ``partial``. Zip-bomb
and DTD guards live in :mod:`._ooxml`.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Optional

from .base import FormatAdapter, FormatKind
from ._common import DEFAULT_MAX_UNITS, UnitSink, build_result
from ._ooxml import (
    DEFAULT_MAX_ENTRIES,
    DEFAULT_MAX_MEMBER_BYTES,
    DEFAULT_MAX_TOTAL_UNCOMPRESSED,
    OoxmlError,
    attr,
    has_member,
    iterparse_xml,
    local,
    natural_key,
    open_package,
    parse_xml,
    read_member,
    read_relationships,
)
from ..extract import ExtractionResult, ExtractionStatus

DEFAULT_MAX_ROWS_PER_SHEET = 10_000
DEFAULT_MAX_TOTAL_ROWS = 50_000
#: Excel's own limit on characters in one cell.
MAX_CELL_CHARS = 32_767

_SHEET_FILE = re.compile(r"^xl/worksheets/sheet\d+\.xml$")


def _si_text(si: ET.Element) -> str:
    """Text of a shared-string / inline-string item; phonetic runs (``rPh``) excluded."""
    out: list[str] = []
    for child in si:
        name = local(child.tag)
        if name == "t":
            out.append(child.text or "")
        elif name == "r":
            for rc in child:
                if local(rc.tag) == "t":
                    out.append(rc.text or "")
    return "".join(out)


class XlsxAdapter(FormatAdapter):
    format = FormatKind.XLSX
    parser_name = "builtin:xlsx"

    def __init__(
        self,
        max_rows_per_sheet: int = DEFAULT_MAX_ROWS_PER_SHEET,
        max_total_rows: int = DEFAULT_MAX_TOTAL_ROWS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_total_uncompressed: int = DEFAULT_MAX_TOTAL_UNCOMPRESSED,
        max_member_bytes: int = DEFAULT_MAX_MEMBER_BYTES,
        max_units: int = DEFAULT_MAX_UNITS,
    ) -> None:
        self.max_rows_per_sheet = max_rows_per_sheet
        self.max_total_rows = max_total_rows
        self.max_entries = max_entries
        self.max_total_uncompressed = max_total_uncompressed
        self.max_member_bytes = max_member_bytes
        self.max_units = max_units

    def is_available(self) -> bool:
        return True

    def supports(self, kind_hint: str) -> bool:
        return FormatKind.detect(kind_hint) == FormatKind.XLSX

    def extract(self, *, source_ref: str, content: bytes, kind_hint: str) -> ExtractionResult:
        if not content:
            return self._fail(source_ref, ExtractionStatus.EMPTY_SOURCE, "empty source bytes", byte_length=0)
        try:
            return self._extract(source_ref, content)
        except OoxmlError as exc:
            return self._fail(source_ref, ExtractionStatus.CORRUPT_SOURCE, str(exc), byte_length=len(content))
        except Exception as exc:  # defensive: untrusted input must never raise
            return self._fail(
                source_ref, ExtractionStatus.CORRUPT_SOURCE,
                f"xlsx parse failure: {type(exc).__name__}", byte_length=len(content),
            )

    # -- extraction ------------------------------------------------------

    def _extract(self, source_ref: str, content: bytes) -> ExtractionResult:
        zf = open_package(content, max_entries=self.max_entries,
                          max_total_uncompressed=self.max_total_uncompressed)
        if not has_member(zf, "xl/workbook.xml"):
            raise OoxmlError("missing xl/workbook.xml (not an xlsx package)")
        sheets = self._sheet_list(zf)
        shared = self._shared_strings(zf)
        sink = UnitSink(source_ref, self.max_units)
        notes: list[str] = []
        errors: list[str] = []
        total_rows = 0
        for n, (name, part) in enumerate(sheets, start=1):
            if total_rows >= self.max_total_rows:
                notes.append(f"row cap reached ({self.max_total_rows} total); remaining sheets skipped")
                break
            if sink.full:
                sink.truncated = True
                break
            try:
                total_rows += self._sheet(zf, part, n, name, shared, sink, notes, self.max_total_rows - total_rows)
            except OoxmlError as exc:
                errors.append(f"sheet {n} skipped: {exc}")
        if errors and not sink.units:
            raise OoxmlError("; ".join(errors))
        notes.extend(errors)
        return build_result(
            self, sink, source_ref=source_ref, byte_length=len(content),
            notes=notes, empty_reason="xlsx contains no non-empty cells",
        )

    def _sheet_list(self, zf) -> list[tuple[str, str]]:
        """``[(sheet name, part name)]`` in workbook order; falls back to file order."""
        root = parse_xml(read_member(zf, "xl/workbook.xml", max_bytes=self.max_member_bytes), "xl/workbook.xml")
        rels = read_relationships(zf, "xl/_rels/workbook.xml.rels", "xl", max_bytes=self.max_member_bytes)
        sheets: list[tuple[str, str]] = []
        for el in root.iter():
            if local(el.tag) != "sheet":
                continue
            rid = attr(el, "id", namespaced=True)
            part = rels.get(rid or "")
            if part and has_member(zf, part):
                sheets.append((attr(el, "name") or f"Sheet{len(sheets) + 1}", part))
        if sheets:
            return sheets
        files = sorted((n for n in zf.namelist() if _SHEET_FILE.match(n)), key=natural_key)
        return [(f"Sheet{k}", part) for k, part in enumerate(files, start=1)]

    def _shared_strings(self, zf) -> list[str]:
        part = "xl/sharedStrings.xml"
        if not has_member(zf, part):
            return []
        data = read_member(zf, part, max_bytes=self.max_member_bytes)
        out: list[str] = []
        for _event, elem in iterparse_xml(data, part):
            if local(elem.tag) == "si":
                out.append(_si_text(elem)[:MAX_CELL_CHARS])
                elem.clear()
        return out

    def _sheet(self, zf, part, n, name, shared, sink: UnitSink, notes: list[str], rows_left: int) -> int:
        """Emit one sheet's rows; returns the number of rows emitted."""
        data = read_member(zf, part, max_bytes=self.max_member_bytes)
        head_id: Optional[str] = None
        emitted = 0
        prev_row = 0
        for _event, elem in iterparse_xml(data, part):
            if local(elem.tag) != "row":
                continue
            row_no = prev_row + 1
            declared = attr(elem, "r")
            if declared is not None and declared.isdigit():
                row_no = int(declared)
            prev_row = row_no
            values = self._row_values(elem, shared)
            elem.clear()
            if not values:
                continue
            if emitted >= self.max_rows_per_sheet or emitted >= rows_left:
                notes.append(f"row cap reached (sheet {n}: {emitted} rows); remaining rows skipped")
                break
            if sink.full:
                sink.truncated = True
                break
            if head_id is None:
                head_id = sink.add_heading(f"s{n}", name or f"Sheet{n}") or sink.add(f"s{n}", "heading", f"Sheet{n}")
                if head_id is None:
                    break
            sink.add_chunks(f"s{n}r{row_no}", "table", " | ".join(values), parent_ref=head_id)
            emitted += 1
        return emitted

    @staticmethod
    def _row_values(row: ET.Element, shared: list[str]) -> list[str]:
        values: list[str] = []
        for cell in row:
            if local(cell.tag) != "c":
                continue
            ctype = attr(cell, "t") or "n"
            v_text: Optional[str] = None
            inline: Optional[str] = None
            for child in cell:
                cname = local(child.tag)
                if cname == "v":
                    v_text = child.text
                elif cname == "is":
                    inline = _si_text(child)
            value: Optional[str]
            if ctype == "s":
                try:
                    value = shared[int((v_text or "").strip())]
                except (ValueError, IndexError):
                    value = None
            elif ctype == "inlineStr":
                value = inline
            elif ctype == "b":
                value = "TRUE" if (v_text or "").strip().lower() in ("1", "true") else "FALSE"
            else:  # n, str, e, d: shown exactly as stored
                value = v_text
            if value is None:
                continue
            value = value.strip()
            if value:
                values.append(value[:MAX_CELL_CHARS])
        return values


__all__ = ["XlsxAdapter"]
