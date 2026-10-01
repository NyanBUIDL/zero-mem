"""T4 — PPTX adapter: basic slide text (``zipfile`` + ``ElementTree``; no dependencies).

Slides are read in presentation order (``ppt/presentation.xml`` ``sldIdLst`` resolved through
its relationships; numeric file order is the fallback). For slide ``n`` (``page`` = ``n``):

- ``sl<n>s<k>``      shape ``k``: title placeholders -> ``heading``, other text shapes -> ``text``
                     (paragraphs joined by newlines, chunked to ~800 chars)
- ``sl<n>t<j>r<i>``  table ``j`` row ``i`` -> ``table`` (``"cell | cell"``)

Non-title units have the slide's first title as ``parent_ref``. Speaker notes and images are
not read. Same zip-bomb / DTD guards as the other OOXML adapters.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Optional

from .base import FormatAdapter, FormatKind
from ._common import DEFAULT_MAX_UNITS, UnitSink, build_result, collapse_ws
from ._ooxml import (
    DEFAULT_MAX_ENTRIES,
    DEFAULT_MAX_MEMBER_BYTES,
    DEFAULT_MAX_TOTAL_UNCOMPRESSED,
    OoxmlError,
    attr,
    has_member,
    local,
    natural_key,
    open_package,
    parse_xml,
    read_member,
    read_relationships,
)
from ..extract import ExtractionResult, ExtractionStatus

DEFAULT_MAX_SLIDES = 2_000
_SLIDE_FILE = re.compile(r"^ppt/slides/slide\d+\.xml$")
_TITLE_TYPES = {"title", "ctrTitle"}


def _a_para_text(p: ET.Element) -> str:
    out: list[str] = []
    for el in p.iter():
        name = local(el.tag)
        if name == "t":
            out.append(el.text or "")
        elif name == "br":
            out.append("\n")
    return "".join(out)


def _body_text(txbody: ET.Element) -> str:
    paras = [_a_para_text(p) for p in txbody if local(p.tag) == "p"]
    return "\n".join(p for p in paras if p.strip())


def _is_title(shape: ET.Element) -> bool:
    for el in shape.iter():
        if local(el.tag) == "ph":
            return (attr(el, "type") or "") in _TITLE_TYPES
    return False


class PptxAdapter(FormatAdapter):
    format = FormatKind.PPTX
    parser_name = "builtin:pptx"

    def __init__(
        self,
        max_slides: int = DEFAULT_MAX_SLIDES,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_total_uncompressed: int = DEFAULT_MAX_TOTAL_UNCOMPRESSED,
        max_member_bytes: int = DEFAULT_MAX_MEMBER_BYTES,
        max_units: int = DEFAULT_MAX_UNITS,
    ) -> None:
        self.max_slides = max_slides
        self.max_entries = max_entries
        self.max_total_uncompressed = max_total_uncompressed
        self.max_member_bytes = max_member_bytes
        self.max_units = max_units

    def is_available(self) -> bool:
        return True

    def supports(self, kind_hint: str) -> bool:
        return FormatKind.detect(kind_hint) == FormatKind.PPTX

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
                f"pptx parse failure: {type(exc).__name__}", byte_length=len(content),
            )

    # -- extraction ------------------------------------------------------

    def _extract(self, source_ref: str, content: bytes) -> ExtractionResult:
        zf = open_package(content, max_entries=self.max_entries,
                          max_total_uncompressed=self.max_total_uncompressed)
        if not has_member(zf, "ppt/presentation.xml"):
            raise OoxmlError("missing ppt/presentation.xml (not a pptx package)")
        slides = self._slide_parts(zf)
        sink = UnitSink(source_ref, self.max_units)
        notes: list[str] = []
        errors: list[str] = []
        for page, part in enumerate(slides, start=1):
            if page > self.max_slides:
                notes.append(f"slide cap reached ({self.max_slides}); remaining slides skipped")
                break
            if sink.full:
                sink.truncated = True
                break
            try:
                root = parse_xml(read_member(zf, part, max_bytes=self.max_member_bytes), part)
            except OoxmlError as exc:
                errors.append(f"slide {page} skipped: {exc}")
                continue
            self._slide(root, page, sink)
        if errors and not sink.units:
            raise OoxmlError("; ".join(errors[:3]))
        notes.extend(errors)
        return build_result(
            self, sink, source_ref=source_ref, byte_length=len(content),
            notes=notes, empty_reason="pptx contains no extractable text",
        )

    def _slide_parts(self, zf) -> list[str]:
        pres = parse_xml(read_member(zf, "ppt/presentation.xml", max_bytes=self.max_member_bytes),
                         "ppt/presentation.xml")
        rels = read_relationships(zf, "ppt/_rels/presentation.xml.rels", "ppt", max_bytes=self.max_member_bytes)
        ordered: list[str] = []
        for el in pres.iter():
            if local(el.tag) == "sldId":
                part = rels.get(attr(el, "id", namespaced=True) or "")
                if part and has_member(zf, part):
                    ordered.append(part)
        if ordered:
            return ordered
        return sorted((n for n in zf.namelist() if _SLIDE_FILE.match(n)), key=natural_key)

    def _slide(self, root: ET.Element, page: int, sink: UnitSink) -> None:
        title_id: Optional[str] = None
        shape_no = 0
        table_no = 0

        def walk(container: ET.Element) -> None:
            nonlocal title_id, shape_no, table_no
            for el in container:
                name = local(el.tag)
                if name == "sp":
                    shape_no += 1
                    txbody = next((c for c in el if local(c.tag) == "txBody"), None)
                    if txbody is None:
                        continue
                    text = _body_text(txbody)
                    if not text.strip():
                        continue
                    if _is_title(el):
                        uid = sink.add_heading(f"sl{page}s{shape_no}", text, page=page)
                        if title_id is None:
                            title_id = uid
                    else:
                        sink.add_chunks(f"sl{page}s{shape_no}", "text", text, page=page, parent_ref=title_id)
                elif name == "graphicFrame":
                    for tbl in (t for t in el.iter() if local(t.tag) == "tbl"):
                        table_no += 1
                        row_no = 0
                        for tr in tbl:
                            if local(tr.tag) != "tr":
                                continue
                            row_no += 1
                            cells = [
                                collapse_ws(" ".join(_a_para_text(p) for p in tc.iter() if local(p.tag) == "p"))
                                for tc in tr if local(tc.tag) == "tc"
                            ]
                            cells = [c for c in cells if c]
                            if cells:
                                sink.add_chunks(f"sl{page}t{table_no}r{row_no}", "table", " | ".join(cells),
                                                page=page, parent_ref=title_id)
                elif name in ("grpSp", "spTree"):
                    walk(el)

        for el in root.iter():
            if local(el.tag) == "spTree":
                walk(el)
                break


__all__ = ["PptxAdapter"]
