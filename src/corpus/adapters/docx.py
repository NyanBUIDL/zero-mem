"""T4 — DOCX adapter (``zipfile`` + ``ElementTree`` over ``word/document.xml``; no dependencies).

Body blocks are processed in document order and streamed (``iterparse``), so a large
document never needs a full in-memory tree. Units (ids use the 1-based index ``i`` of
the body block, a stable pointer into the document; ``.k`` suffix for chunked prose):

- ``h<i>``        ``Heading N`` / ``Title`` styles or an ``outlineLvl`` -> ``heading``;
                  ``parent_ref`` = enclosing (lower level) heading
- ``p<i>``        other non-empty paragraphs -> ``text`` (chunked to ~800 chars)
- ``t<i>r<j>``    table rows -> ``table`` (``"cell | cell"``; nested tables flattened into the cell)
- ``fn<id>`` / ``en<id>`` footnotes / endnotes, ``hd<n>`` / ``ft<n>`` headers / footers -> ``text``

Localised style ids are resolved through ``word/styles.xml`` names. Tracked deletions are
skipped, tracked insertions kept. Corrupt / hostile containers return ``corrupt_source``.
"""
from __future__ import annotations

import re
from typing import Iterator, Optional
import xml.etree.ElementTree as ET

from .base import FormatAdapter, FormatKind
from ._common import (
    DEFAULT_MAX_UNITS,
    HeadingTracker,
    UnitSink,
    build_result,
    collapse_ws,
)
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
)
from ..extract import ExtractionResult, ExtractionStatus

_HEADING_STYLE = re.compile(r"^heading\s*([1-9])$")
_PART_NAME = re.compile(r"^word/(header|footer)(\d*)\.xml$")
_RECURSE_INLINE = {"hyperlink", "ins", "smartTag", "fldSimple", "sdt", "sdtContent", "customXml", "moveTo"}
_SKIP_INLINE = {"del", "moveFrom"}
_BLOCK_CONTAINERS = {"sdt", "sdtContent", "customXml", "ins", "moveTo"}


def _style_level(name: str) -> Optional[int]:
    lowered = name.strip().lower()
    if lowered == "title":
        return 0
    m = _HEADING_STYLE.match(lowered)
    return int(m.group(1)) if m else None


def _para_text(p: ET.Element) -> str:
    parts: list[str] = []

    def walk(node: ET.Element) -> None:
        for child in node:
            name = local(child.tag)
            if name == "r":
                for rc in child:
                    rname = local(rc.tag)
                    if rname == "t":
                        parts.append(rc.text or "")
                    elif rname == "tab":
                        parts.append("\t")
                    elif rname in ("br", "cr"):
                        parts.append("\n")
                    elif rname == "noBreakHyphen":
                        parts.append("-")
            elif name in _SKIP_INLINE:
                continue
            elif name in _RECURSE_INLINE:
                walk(child)

    walk(p)
    return "".join(parts)


def _iter_paragraphs(node: ET.Element) -> Iterator[ET.Element]:
    for el in node.iter():
        if local(el.tag) == "p":
            yield el


def _iter_blocks(node: ET.Element) -> Iterator[ET.Element]:
    """Yield ``p`` / ``tbl`` blocks, looking through content controls and similar wrappers."""
    name = local(node.tag)
    if name in ("p", "tbl"):
        yield node
    elif name in _BLOCK_CONTAINERS:
        for child in node:
            yield from _iter_blocks(child)


class DocxAdapter(FormatAdapter):
    format = FormatKind.DOCX
    parser_name = "builtin:docx"

    def __init__(
        self,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_total_uncompressed: int = DEFAULT_MAX_TOTAL_UNCOMPRESSED,
        max_member_bytes: int = DEFAULT_MAX_MEMBER_BYTES,
        max_units: int = DEFAULT_MAX_UNITS,
    ) -> None:
        self.max_entries = max_entries
        self.max_total_uncompressed = max_total_uncompressed
        self.max_member_bytes = max_member_bytes
        self.max_units = max_units

    def is_available(self) -> bool:
        return True

    def supports(self, kind_hint: str) -> bool:
        return FormatKind.detect(kind_hint) == FormatKind.DOCX

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
                f"docx parse failure: {type(exc).__name__}", byte_length=len(content),
            )

    # -- extraction ------------------------------------------------------

    def _extract(self, source_ref: str, content: bytes) -> ExtractionResult:
        zf = open_package(content, max_entries=self.max_entries,
                          max_total_uncompressed=self.max_total_uncompressed)
        if not has_member(zf, "word/document.xml"):
            raise OoxmlError("missing word/document.xml (not a docx package)")
        document = read_member(zf, "word/document.xml", max_bytes=self.max_member_bytes)
        style_levels = self._style_levels(zf)
        sink = UnitSink(source_ref, self.max_units)
        self._body(document, style_levels, sink)
        self._notes(zf, sink)
        return build_result(
            self, sink, source_ref=source_ref, byte_length=len(content),
            empty_reason="docx contains no extractable text",
        )

    def _style_levels(self, zf) -> dict[str, int]:
        """``styleId -> heading level`` from ``word/styles.xml`` (best effort)."""
        levels: dict[str, int] = {}
        if not has_member(zf, "word/styles.xml"):
            return levels
        try:
            root = parse_xml(read_member(zf, "word/styles.xml", max_bytes=self.max_member_bytes), "word/styles.xml")
        except OoxmlError:
            return levels
        for style in root:
            if local(style.tag) != "style":
                continue
            sid = attr(style, "styleId")
            if not sid:
                continue
            level: Optional[int] = None
            for child in style:
                cname = local(child.tag)
                if cname == "name":
                    level = _style_level(attr(child, "val") or "")
                elif cname == "pPr" and level is None:
                    for ppr_child in child:
                        if local(ppr_child.tag) == "outlineLvl":
                            val = attr(ppr_child, "val")
                            if val is not None and val.isdigit() and int(val) < 9:
                                level = int(val) + 1
            if level is not None:
                levels[sid] = level
        return levels

    @staticmethod
    def _heading_level(p: ET.Element, style_levels: dict[str, int]) -> Optional[int]:
        for child in p:
            if local(child.tag) != "pPr":
                continue
            style_id = None
            outline = None
            for pc in child:
                pname = local(pc.tag)
                if pname == "pStyle":
                    style_id = attr(pc, "val")
                elif pname == "outlineLvl":
                    val = attr(pc, "val")
                    if val is not None and val.isdigit() and int(val) < 9:
                        outline = int(val) + 1
            if style_id:
                if style_id in style_levels:
                    return style_levels[style_id]
                by_id = _style_level(style_id)
                if by_id is not None:
                    return by_id
            return outline
        return None

    def _body(self, document: bytes, style_levels: dict[str, int], sink: UnitSink) -> None:
        tracker = HeadingTracker()
        stack: list[str] = []
        block_no = 0
        for event, elem in iterparse_xml(document, "word/document.xml", events=("start", "end")):
            if event == "start":
                stack.append(local(elem.tag))
                continue
            stack.pop()
            # a direct child of <w:body> just closed: one block (p / tbl / sdt ...)
            if len(stack) != 2 or stack[1] != "body":
                continue
            for block in _iter_blocks(elem):
                block_no += 1
                if sink.full:
                    sink.truncated = True
                    return
                if local(block.tag) == "p":
                    self._paragraph(block, block_no, style_levels, tracker, sink)
                else:
                    self._table(block, block_no, tracker, sink)
            elem.clear()

    def _paragraph(self, p, i, style_levels, tracker: HeadingTracker, sink: UnitSink) -> None:
        text = _para_text(p)
        if not text.strip():
            return
        level = self._heading_level(p, style_levels)
        if level is not None:
            parent = tracker.parent_for(level)
            uid = sink.add_heading(f"h{i}", text, parent_ref=parent)
            if uid is not None:
                tracker.enter(level, uid)
            return
        sink.add_chunks(f"p{i}", "text", text, parent_ref=tracker.current)

    @staticmethod
    def _table(tbl: ET.Element, i: int, tracker: HeadingTracker, sink: UnitSink) -> None:
        row_no = 0
        for row in tbl:
            if local(row.tag) != "tr":
                continue
            row_no += 1
            cells: list[str] = []
            for cell in row:
                if local(cell.tag) != "tc":
                    continue
                text = collapse_ws(" ".join(_para_text(p) for p in _iter_paragraphs(cell)))
                if text:
                    cells.append(text)
            if cells:
                sink.add_chunks(f"t{i}r{row_no}", "table", " | ".join(cells), parent_ref=tracker.current)

    # -- footnotes / endnotes / headers / footers -------------------------

    def _notes(self, zf, sink: UnitSink) -> None:
        """Best effort: unreadable optional parts are skipped, never fatal."""
        for part, tag, prefix in (("word/footnotes.xml", "footnote", "fn"), ("word/endnotes.xml", "endnote", "en")):
            if not has_member(zf, part):
                continue
            try:
                root = parse_xml(read_member(zf, part, max_bytes=self.max_member_bytes), part)
            except OoxmlError:
                continue
            for note in root:
                if local(note.tag) != tag:
                    continue
                note_type = attr(note, "type")
                if note_type and note_type != "normal":
                    continue  # separators
                text = " ".join(_para_text(p) for p in _iter_paragraphs(note))
                note_id = attr(note, "id") or "0"
                if text.strip():
                    sink.add_chunks(f"{prefix}{note_id}", "text", text)
        seen: set[str] = set()
        parts = sorted((n for n in zf.namelist() if _PART_NAME.match(n)), key=natural_key)
        for n, part in enumerate(parts, start=1):
            m = _PART_NAME.match(part)
            kind_prefix = "hd" if m and m.group(1) == "header" else "ft"
            try:
                root = parse_xml(read_member(zf, part, max_bytes=self.max_member_bytes), part)
            except OoxmlError:
                continue
            text = collapse_ws(" ".join(_para_text(p) for p in _iter_paragraphs(root)))
            if not text or text in seen:
                continue
            seen.add(text)
            suffix = (m.group(2) if m and m.group(2) else str(n))
            sink.add_chunks(f"{kind_prefix}{suffix}", "text", text)


__all__ = ["DocxAdapter"]
