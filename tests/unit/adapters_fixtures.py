"""Programmatic fixtures for the T4 format-adapter tests (no binary files committed).

Everything here is built from stdlib only: ``zipfile`` for the OOXML containers,
``struct``/``zlib`` for tiny valid images. Builders are deliberately minimal but
structurally faithful to what Word / Excel / PowerPoint emit (namespaces, shared
strings, relationships), so the adapters are exercised against the real shape.
"""
from __future__ import annotations

import io
import struct
import zipfile
import zlib
from typing import Any, Iterable, Optional, Sequence
from xml.sax.saxutils import escape

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
S_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"

_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def _zip(parts: dict[str, bytes | str], *, compression=zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=compression) as zf:
        for name, data in parts.items():
            zf.writestr(name, data if isinstance(data, bytes) else data.encode("utf-8"))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------

def _w_run(text: str) -> str:
    return f'<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def _w_para(text: str, style: Optional[str] = None, *, outline: Optional[int] = None) -> str:
    ppr = ""
    if style or outline is not None:
        inner = f'<w:pStyle w:val="{style}"/>' if style else ""
        if outline is not None:
            inner += f'<w:outlineLvl w:val="{outline}"/>'
        ppr = f"<w:pPr>{inner}</w:pPr>"
    return f"<w:p>{ppr}{_w_run(text)}</w:p>" if text != "" else f"<w:p>{ppr}</w:p>"


def _w_table(rows: Sequence[Sequence[str]]) -> str:
    out = ["<w:tbl>"]
    for row in rows:
        out.append("<w:tr>")
        for cell in row:
            out.append(f"<w:tc>{_w_para(cell)}</w:tc>")
        out.append("</w:tr>")
    out.append("</w:tbl>")
    return "".join(out)


def make_docx(
    blocks: Iterable[tuple],
    *,
    footnotes: Optional[Sequence[str]] = None,
    headers: Optional[Sequence[str]] = None,
    styles_xml: Optional[str] = None,
    extra_parts: Optional[dict[str, bytes | str]] = None,
    document_xml_override: Optional[str] = None,
) -> bytes:
    """Build a docx. ``blocks``: ("h", level, text) | ("p", text) | ("table", rows) |
    ("styled", styleId, text) | ("outline", level0, text) | ("raw", xml)."""
    body: list[str] = []
    for blk in blocks:
        tag = blk[0]
        if tag == "h":
            body.append(_w_para(blk[2], f"Heading{blk[1]}"))
        elif tag == "title":
            body.append(_w_para(blk[1], "Title"))
        elif tag == "p":
            body.append(_w_para(blk[1]))
        elif tag == "styled":
            body.append(_w_para(blk[2], blk[1]))
        elif tag == "outline":
            body.append(_w_para(blk[2], None, outline=blk[1]))
        elif tag == "table":
            body.append(_w_table(blk[1]))
        elif tag == "raw":
            body.append(blk[1])
        else:  # pragma: no cover - fixture misuse
            raise ValueError(tag)
    document = document_xml_override or (
        _XML + f'<w:document xmlns:w="{W_NS}"><w:body>{"".join(body)}</w:body></w:document>'
    )
    parts: dict[str, bytes | str] = {
        "[Content_Types].xml": _XML + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/></Types>',
        "_rels/.rels": _XML + f'<Relationships xmlns="{PKG_REL_NS}"></Relationships>',
        "word/document.xml": document,
    }
    if styles_xml:
        parts["word/styles.xml"] = styles_xml
    if footnotes:
        notes = ['<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>']
        for i, t in enumerate(footnotes, start=1):
            notes.append(f'<w:footnote w:id="{i}">{_w_para(t)}</w:footnote>')
        parts["word/footnotes.xml"] = _XML + f'<w:footnotes xmlns:w="{W_NS}">{"".join(notes)}</w:footnotes>'
    for i, t in enumerate(headers or (), start=1):
        parts[f"word/header{i}.xml"] = _XML + f'<w:hdr xmlns:w="{W_NS}">{_w_para(t)}</w:hdr>'
    parts.update(extra_parts or {})
    return _zip(parts)


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------

def col_letters(index0: int) -> str:
    n = index0 + 1
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def make_xlsx(
    sheets: Sequence[tuple[str, Sequence[Optional[Sequence[Any]]]]],
    *,
    inline_strings: bool = False,
    absolute_targets: bool = False,
    extra_parts: Optional[dict[str, bytes | str]] = None,
) -> bytes:
    """Build an xlsx. ``sheets``: [(name, rows)], rows[i] is a list of cells or None
    (blank row, row number skipped). Cell: str | int | float | bool | None |
    ("f", formula, cached) | ("e", "#DIV/0!") | ("d", "2024-01-31T00:00:00")."""
    shared: list[str] = []

    def sst(text: str) -> int:
        if text not in shared:
            shared.append(text)
        return shared.index(text)

    sheet_parts: dict[str, str] = {}
    wb_sheets: list[str] = []
    wb_rels: list[str] = []
    for n, (name, rows) in enumerate(sheets, start=1):
        row_xml: list[str] = []
        for r_idx, row in enumerate(rows, start=1):
            if row is None:
                continue
            cells: list[str] = []
            for c_idx, v in enumerate(row):
                if v is None:
                    continue
                ref = f"{col_letters(c_idx)}{r_idx}"
                if isinstance(v, bool):
                    cells.append(f'<c r="{ref}" t="b"><v>{int(v)}</v></c>')
                elif isinstance(v, (int, float)):
                    cells.append(f'<c r="{ref}"><v>{v!r}</v></c>')
                elif isinstance(v, str):
                    if inline_strings:
                        cells.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(v)}</t></is></c>')
                    else:
                        cells.append(f'<c r="{ref}" t="s"><v>{sst(v)}</v></c>')
                elif isinstance(v, tuple) and v[0] == "f":
                    cached = v[2]
                    if cached is None:
                        cells.append(f'<c r="{ref}"><f>{escape(v[1])}</f></c>')
                    elif isinstance(cached, str):
                        cells.append(f'<c r="{ref}" t="str"><f>{escape(v[1])}</f><v>{escape(cached)}</v></c>')
                    else:
                        cells.append(f'<c r="{ref}"><f>{escape(v[1])}</f><v>{cached!r}</v></c>')
                elif isinstance(v, tuple) and v[0] == "e":
                    cells.append(f'<c r="{ref}" t="e"><v>{escape(v[1])}</v></c>')
                elif isinstance(v, tuple) and v[0] == "d":
                    cells.append(f'<c r="{ref}" t="d"><v>{escape(v[1])}</v></c>')
                else:  # pragma: no cover
                    raise ValueError(v)
            row_xml.append(f'<row r="{r_idx}">{"".join(cells)}</row>')
        sheet_parts[f"xl/worksheets/sheet{n}.xml"] = (
            _XML + f'<worksheet xmlns="{S_NS}"><sheetData>{"".join(row_xml)}</sheetData></worksheet>'
        )
        wb_sheets.append(f'<sheet name="{escape(name)}" sheetId="{n}" r:id="rId{n}"/>')
        target = f"/xl/worksheets/sheet{n}.xml" if absolute_targets else f"worksheets/sheet{n}.xml"
        wb_rels.append(
            f'<Relationship Id="rId{n}" Type="{R_NS}/worksheet" Target="{target}"/>'
        )
    parts: dict[str, bytes | str] = {
        "[Content_Types].xml": _XML + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
        "_rels/.rels": _XML + f'<Relationships xmlns="{PKG_REL_NS}"></Relationships>',
        "xl/workbook.xml": _XML
        + f'<workbook xmlns="{S_NS}" xmlns:r="{R_NS}"><sheets>{"".join(wb_sheets)}</sheets></workbook>',
        "xl/_rels/workbook.xml.rels": _XML + f'<Relationships xmlns="{PKG_REL_NS}">{"".join(wb_rels)}</Relationships>',
    }
    if shared and not inline_strings:
        si = "".join(f'<si><t xml:space="preserve">{escape(s)}</t></si>' for s in shared)
        parts["xl/sharedStrings.xml"] = _XML + f'<sst xmlns="{S_NS}" count="{len(shared)}" uniqueCount="{len(shared)}">{si}</sst>'
    parts.update(sheet_parts)
    parts.update(extra_parts or {})
    return _zip(parts)


# ---------------------------------------------------------------------------
# PPTX
# ---------------------------------------------------------------------------

def _a_para(text: str) -> str:
    return f'<a:p><a:r><a:t>{escape(text)}</a:t></a:r></a:p>'


def _p_shape(paras: Sequence[str], *, title: bool = False, shape_id: int = 2) -> str:
    ph = '<p:nvPr><p:ph type="title"/></p:nvPr>' if title else "<p:nvPr/>"
    body = "".join(_a_para(t) for t in paras)
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="s{shape_id}"/><p:cNvSpPr/>{ph}</p:nvSpPr>'
        f"<p:spPr/><p:txBody><a:bodyPr/>{body}</p:txBody></p:sp>"
    )


def _a_table(rows: Sequence[Sequence[str]]) -> str:
    trs = "".join(
        "<a:tr>" + "".join(f"<a:tc><a:txBody><a:bodyPr/>{_a_para(c)}</a:txBody></a:tc>" for c in row) + "</a:tr>"
        for row in rows
    )
    return (
        '<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="9" name="tbl"/></p:nvGraphicFramePr>'
        f"<a:graphic><a:graphicData><a:tbl>{trs}</a:tbl></a:graphicData></a:graphic></p:graphicFrame>"
    )


def make_pptx(slides: Sequence[dict[str, Any]], *, reverse_order: bool = False) -> bytes:
    """slides: [{"title": str, "body": [str], "table": rows}]. ``reverse_order`` lists
    slide files 1..N but orders them N..1 in presentation.xml (tests rels-based ordering)."""
    parts: dict[str, bytes | str] = {
        "[Content_Types].xml": _XML + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
        "_rels/.rels": _XML + f'<Relationships xmlns="{PKG_REL_NS}"></Relationships>',
    }
    rels: list[str] = []
    ids: list[str] = []
    for n, sl in enumerate(slides, start=1):
        shapes: list[str] = []
        if sl.get("title"):
            shapes.append(_p_shape([sl["title"]], title=True, shape_id=2))
        if sl.get("body"):
            shapes.append(_p_shape(sl["body"], shape_id=3))
        if sl.get("table"):
            shapes.append(_a_table(sl["table"]))
        parts[f"ppt/slides/slide{n}.xml"] = (
            _XML + f'<p:sld xmlns:a="{A_NS}" xmlns:p="{P_NS}" xmlns:r="{R_NS}"><p:cSld><p:spTree>'
            f'{"".join(shapes)}</p:spTree></p:cSld></p:sld>'
        )
        rels.append(f'<Relationship Id="rId{n}" Type="{R_NS}/slide" Target="slides/slide{n}.xml"/>')
        ids.append(f'<p:sldId id="{255 + n}" r:id="rId{n}"/>')
    if reverse_order:
        ids.reverse()
    parts["ppt/_rels/presentation.xml.rels"] = _XML + f'<Relationships xmlns="{PKG_REL_NS}">{"".join(rels)}</Relationships>'
    parts["ppt/presentation.xml"] = (
        _XML + f'<p:presentation xmlns:p="{P_NS}" xmlns:r="{R_NS}"><p:sldIdLst>{"".join(ids)}</p:sldIdLst></p:presentation>'
    )
    return _zip(parts)


# ---------------------------------------------------------------------------
# Images (tiny, structurally valid headers)
# ---------------------------------------------------------------------------

def make_png(width: int = 3, height: int = 2) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def make_jpeg(width: int = 17, height: int = 9) -> bytes:
    """Header-only JPEG (SOI, APP0, DQT, SOF0, EOI): enough for dimension parsing."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    dqt = b"\xff\xdb" + struct.pack(">H", 67) + b"\x00" + bytes(range(1, 65))
    sof0 = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app0 + dqt + sof0 + b"\xff\xd9"


def make_gif(width: int = 5, height: int = 4) -> bytes:
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00\x00\x00" + b";"


def make_bmp(width: int = 6, height: int = 5) -> bytes:
    row = ((width * 3 + 3) // 4) * 4
    pixels = b"\x00" * (row * height)
    dib = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(pixels), 2835, 2835, 0, 0)
    header = b"BM" + struct.pack("<IHHI", 14 + len(dib) + len(pixels), 0, 0, 14 + len(dib))
    return header + dib + pixels


def make_webp(width: int = 11, height: int = 7) -> bytes:
    """Minimal VP8X (extended) WebP header."""
    vp8x = struct.pack("<I", 10) + b"\x00\x00\x00\x00" + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    payload = b"WEBP" + b"VP8X" + vp8x
    return b"RIFF" + struct.pack("<I", len(payload)) + payload


def make_tiff(width: int = 13, height: int = 8, *, big_endian: bool = False) -> bytes:
    end = ">" if big_endian else "<"
    head = (b"MM\x00*" if big_endian else b"II*\x00") + struct.pack(end + "I", 8)
    entries = struct.pack(end + "H", 2)
    entries += struct.pack(end + "HHI", 256, 4, 1) + struct.pack(end + "I", width)
    entries += struct.pack(end + "HHI", 257, 4, 1) + struct.pack(end + "I", height)
    return head + entries + struct.pack(end + "I", 0)


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def zip_bytes(parts: dict[str, bytes | str], *, compression=zipfile.ZIP_DEFLATED) -> bytes:
    return _zip(parts, compression=compression)
