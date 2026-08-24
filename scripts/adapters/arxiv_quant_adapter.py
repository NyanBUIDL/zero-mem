"""V140-01 — arxiv-quant adapter instance (GATE-0-ADDENDUM).

This is the FIRST concrete FormatAdapter instance for the generic corpus
pipeline, NOT the tool's default shape. It parses the quant_lab directory
convention `<date> - <arxiv-id> - <title>` and classifies each paper into
the three source kinds, but does NOT hardcode any quant_lab-only behavior
into the core ingest tool.

Adding another corpus = register another adapter; the ingest script stays
generic (see corpus_generic_ingest.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# <date> - <arxiv-id> - <title>
_DIR_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) - ([A-Za-z0-9_.-]+?) - (.+)$")


@dataclass
class PaperDir:
    path: Path
    date: str
    arxiv_id: str
    title: str
    md_file: Optional[Path]
    pdf_name: Optional[str]  # filename in papers/ if a matching PDF exists

    @property
    def source_kind(self) -> str:
        if self.pdf_name:
            return "derived-md" if self.md_file else "primary-pdf"
        return "orphan-md"


def parse_corpus(source_dir: Path, papers_subdir: str = "papers") -> list[PaperDir]:
    """Map a corpus tree (arxiv-quant convention) into PaperDir records.

    Generic enough to be reused: callers pass the root and the pdf subdir
    name. Returns one PaperDir per article directory plus one per
    PDF-only file in the papers subdir.
    """
    dirs: list[PaperDir] = []
    papers_dir = source_dir / papers_subdir
    for d in sorted(p for p in source_dir.iterdir()
                    if p.is_dir() and p.name != papers_subdir):
        m = _DIR_RE.match(d.name)
        md = next((f for f in d.glob("*.md") if f.stem == d.name), None)
        if md is None:
            md = next((f for f in d.glob("*.md")), None)
        dirs.append(PaperDir(
            path=d,
            date=m.group(1) if m else "",
            arxiv_id=m.group(2) if m else "",
            title=m.group(3) if m else d.name,
            md_file=md,
            pdf_name=None,
        ))
    assigned: set[str] = set()
    if papers_dir.exists():
        for pdf in sorted(papers_dir.glob("*.pdf")):
            m = _DIR_RE.match(pdf.stem)
            key = (m.group(1), m.group(2)) if m else None
            cand = next((p for p in dirs
                         if key and p.date == key[0] and p.arxiv_id == key[1]),
                        None)
            if cand is not None:
                cand.pdf_name = pdf.name
                assigned.add(pdf.name)
        for pdf in sorted(papers_dir.glob("*.pdf")):
            if pdf.name in assigned:
                continue
            m = _DIR_RE.match(pdf.stem)
            dirs.append(PaperDir(
                path=pdf,
                date=m.group(1) if m else "",
                arxiv_id=m.group(2) if m else "",
                title=m.group(3) if m else pdf.stem,
                md_file=None,
                pdf_name=pdf.name,
            ))
    return dirs
