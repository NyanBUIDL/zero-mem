#!/usr/bin/env python3
"""Regenerate docs/MASTER-SPEC.md from the authoritative master DOCX spec.

The master specification is the single authoritative document:
``Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`` at the repository root.

``docs/MASTER-SPEC.md`` is a read-only Markdown *projection* of that DOCX, kept
for fast browsing/diffing. The DOCX always wins on any conflict. This script is
the deterministic generator for that projection: given the same DOCX bytes it
must reproduce ``docs/MASTER-SPEC.md`` byte-for-byte.

Usage::

    .venv-v124/bin/python scripts/convert_master_spec_to_md.py

Stdlib only (zipfile + xml.etree). No third-party dependency.
"""

from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCX_PATH = REPO_ROOT / "Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx"
OUT_PATH = REPO_ROOT / "docs" / "MASTER-SPEC.md"

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Fixed for deterministic, byte-identical reproduction: the date this
# projection was first generated and its asserted provenance.
PROJECTION_DATE = "2026-08-22"

BANNER = (
    f"> **Nguồn:** Bản chuyển đổi (Markdown) từ `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`.\n"
    f"> DOCX là bản authoritative duy nhất. File này là bản đọc/projection để tra cứu và diff nhanh;\n"
    f"> khi mâu thuẫn, luôn ưu tiên DOCX. Tự sinh {PROJECTION_DATE}; không chỉnh tay nội dung.\n"
    f"\n"
)


def _para_text(p: ET.Element) -> str:
    """Concatenate run text; preserve tab and line-break markers."""
    parts: list[str] = []
    for node in p.iter():
        tag = node.tag
        if tag == W + "t" and node.text:
            parts.append(node.text)
        elif tag == W + "tab":
            parts.append("\t")
        elif tag == W + "br":
            parts.append("\n")
    return "".join(parts)


def _para_style(p: ET.Element) -> str:
    pPr = p.find(W + "pPr")
    if pPr is not None:
        ps = pPr.find(W + "pStyle")
        if ps is not None:
            return ps.get(W + "val", "")
    return ""


def _cell_text(tc: ET.Element) -> str:
    return "\n".join(_para_text(p) for p in tc.findall(W + "p"))


def _table_to_md(tbl: ET.Element) -> str:
    rows = tbl.findall(W + "tr")
    if not rows:
        return ""
    grid: list[list[str]] = []
    for tr in rows:
        grid.append([_cell_text(tc) for tc in tr.findall(W + "tc")])
    ncol = max(len(r) for r in grid)
    for r in grid:
        while len(r) < ncol:
            r.append("")
    # Single-cell tables are callout boxes or ASCII diagrams in the DOCX.
    if ncol == 1 and len(rows) == 1:
        txt = grid[0][0].strip()
        if not txt:
            return ""
        if "\n" in txt:
            return "```text\n" + txt + "\n```"
        return "> " + txt
    lines = [
        "| "
        + " | ".join(c.replace("\n", " ").replace("|", "\\|").strip() for c in grid[0])
        + " |",
        "| " + " | ".join(["---"] * ncol) + " |",
    ]
    for r in grid[1:]:
        esc = [c.replace("|", "\\|").replace("\n", "<br>").strip() for c in r]
        lines.append("| " + " | ".join(esc) + " |")
    return "\n".join(lines)


def convert(docx_path: Path) -> str:
    with zipfile.ZipFile(docx_path) as z:
        tree = ET.fromstring(z.read("word/document.xml"))

    body = tree.find(W + "body")
    if body is None:
        raise ValueError("docx document.xml has no <w:body> element")
    md: list[str] = []
    for child in body:
        tag = child.tag
        if tag == W + "p":
            style = _para_style(child)
            txt = _para_text(child).strip()
            if not txt:
                md.append("")
                continue
            if style == "Heading1":
                md.append("# " + txt)
            elif style == "Heading2":
                md.append("## " + txt)
            elif style == "ListBullet":
                md.append("- " + txt)
            elif style == "Caption":
                md.append("> " + txt)
            else:
                md.append(txt)
        elif tag == W + "tbl":
            md.append("")
            md.append(_table_to_md(child))
            md.append("")

    content = "\n\n".join(md)
    content = re.sub(r"\n{3,}", "\n\n", content).rstrip() + "\n"
    return BANNER + content


def main() -> int:
    if not DOCX_PATH.is_file():
        raise SystemExit(f"authoritative DOCX not found: {DOCX_PATH}")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(convert(DOCX_PATH), encoding="utf-8")
    print(f"wrote {OUT_PATH.relative_to(REPO_ROOT)} ({OUT_PATH.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())