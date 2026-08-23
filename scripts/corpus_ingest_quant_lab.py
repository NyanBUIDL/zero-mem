#!/usr/bin/env python3
"""V130 corpus — quant_lab ingest (QL-1: 600 .md, QL-2: PDF extraction).

Tooling only: NO product-code (src/) changes. Registers every paper through the
verified M10 CorpusSourceRegistry (+ blob store for the primary PDFs) into
knowledge space ``quant-theory``.

Source-kind taxonomy (user-confirmed 2026-08-23):
- primary-pdf      : PDF is the authoritative source (blob stored via blob_store).
- derived-md       : .md whose paper dir also contains the original PDF.
- orphan-md        : .md with NO matching PDF anywhere (best remaining text;
                     provenance marks original-pdf-unavailable).

Deterministic: same corpus -> same registration outcome (registry dedup by
content identity). Idempotent: re-running registers zero new sources.

Usage:
    .venv-v124/bin/python scripts/corpus_ingest_quant_lab.py --dry-run
    .venv-v124/bin/python scripts/corpus_ingest_quant_lab.py --apply
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

QUANT_LAB = Path("/home/lenovo/Hermes Workspace/quant_lab")
PAPERS_DIR = QUANT_LAB / "papers"
KS = "quant-theory"
PROFILE = "quant-lab-profile"
PROJECT = "quant-lab-corpus"

# QL-2 text extractor lives in the same scripts/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from corpus_extract_pdfs import extract_pdf_text  # noqa: E402

# <date> - <arxiv_id> - <title>
_DIR_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) - ([A-Za-z0-9_.-]+?) - (.+)$")


@dataclass
class PaperDir:
    path: Path
    date: str
    arxiv_id: str
    title: str
    md_file: Path | None
    pdf_name: str | None  # exact filename in papers/ if a matching PDF exists

    @property
    def source_kind(self) -> str:
        if self.pdf_name:
            return "derived-md" if self.md_file else "primary-pdf-only-dir"
        return "orphan-md"


def parse_papers() -> list[PaperDir]:
    """Map every paper directory to its .md and (optionally) its primary PDF.

    PDF matching is by (date, arxiv_id) — filenames may differ in punctuation
    encoding between the paper dir and the papers/ copy. A PDF with no matching
    dir is a primary-pdf-only source (still registered; no .md exists).
    """
    dirs: list[PaperDir] = []
    for d in sorted(p for p in QUANT_LAB.iterdir() if p.is_dir() and p.name != "papers"):
        m = _DIR_RE.match(d.name)
        md = next((f for f in d.glob("*.md") if f.stem == d.name), None)
        if md is None:
            md = next((f for f in d.glob("*.md")), None)
        dirs.append(PaperDir(
            path=d, date=m.group(1) if m else "", arxiv_id=m.group(2) if m else "",
            title=m.group(3) if m else d.name,
            md_file=md,
            pdf_name=None,
        ))
    # Match each PDF to a dir by (date, arxiv_id); collect leftovers.
    assigned: set[str] = set()
    for pdf in sorted(PAPERS_DIR.glob("*.pdf")):
        m = _DIR_RE.match(pdf.stem)
        key = (m.group(1), m.group(2)) if m else None
        cand = next((p for p in dirs
                     if key and p.date == key[0] and p.arxiv_id == key[1]), None)
        if cand is not None:
            cand.pdf_name = pdf.name
            assigned.add(pdf.name)
    # PDFs with no matching .md dir become their own primary-pdf-only sources.
    for pdf in sorted(PAPERS_DIR.glob("*.pdf")):
        if pdf.name in assigned:
            continue
        m = _DIR_RE.match(pdf.stem)
        dirs.append(PaperDir(
            path=pdf, date=m.group(1) if m else "", arxiv_id=m.group(2) if m else "",
            title=m.group(3) if m else pdf.stem,
            md_file=None, pdf_name=pdf.name,
        ))
    return dirs


def register(registry, blobs, dry_run: bool):
    stats = {"dirs": 0, "primary_pdf": 0, "derived_md": 0, "orphan_md": 0,
             "new_sources": 0, "dedup_hits": 0, "skipped": [],
             "pdf_extract_ok": 0, "pdf_extract_skip": 0}
    for pd in parse_papers():
        stats["dirs"] += 1
        meta = {"arxiv_id": pd.arxiv_id, "published": pd.date, "title": pd.title}

        # QL-2: the PDF is PRIMARY. Store its bytes in the blob store; extract
        # derived text via pymupdf with page provenance.
        if pd.pdf_name:
            pdf_path = PAPERS_DIR / pd.pdf_name
            content = pdf_path.read_bytes()
            ex = extract_pdf_text(pdf_path)
            if ex["status"] != "OK":
                stats["pdf_extract_skip"] += 1
                stats["skipped"].append({"dir": dname(pd), "component": "pdf-text",
                                         "reason": ex["reason"]})
                if dry_run:
                    continue
            else:
                stats["pdf_extract_ok"] += 1
            if not dry_run:
                rec = registry.register_source_with_blob(
                    content=content,
                    external_ref=str(pdf_path.relative_to(QUANT_LAB)),
                    kind="primary-pdf",
                    profile_id=PROFILE, project_id=PROJECT, knowledge_space_id=KS,
                    custom_meta={**meta, "source_kind": "primary-pdf",
                                 "original_filename": pd.pdf_name,
                                 "extract_status": ex["status"],
                                 "page_count": ex.get("page_count"),
                                 "text_chars": ex.get("total_chars")},
                    provenance={"source_path": str(pdf_path), "bytes": len(content)},
                    blob_store=blobs,
                )
                _count_new(rec, stats)
            else:
                stats["primary_pdf"] += 1
                stats["new_sources"] += 1  # dry-run estimate assumes unique

        # The .md: derived when a PDF exists for the same paper; orphan otherwise.
        if pd.md_file is not None:
            kind = "derived-md" if pd.pdf_name else "orphan-md"
            content = pd.md_file.read_bytes()
            prov = {
                "source_path": str(pd.md_file),
                "source_kind": kind,
            }
            if kind == "orphan-md":
                prov["note"] = "original-pdf-unavailable"
            if not dry_run:
                rec = registry.register_source(
                    content=content,
                    external_ref=str(pd.md_file.relative_to(QUANT_LAB)),
                    kind=kind,
                    profile_id=PROFILE, project_id=PROJECT, knowledge_space_id=KS,
                    custom_meta={**meta, "source_kind": kind},
                    provenance=prov,
                )
                _count_new(rec, stats)
            else:
                stats["derived_md" if kind == "derived-md" else "orphan_md"] += 1
                stats["new_sources"] += 1
        else:
            stats["skipped"].append({"dir": dname(pd), "reason": "no .md file found"})
    return stats


def dname(pd: PaperDir) -> str:
    return pd.path.name


def _count_new(rec, stats: dict) -> None:
    # Registry dedup returns the SAME record object on identical re-registration.
    # Counting new vs dedup needs the pre-call size delta; caller tracks totals.
    stats["new_sources"] += 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--root", required=True, help="corpus root (dev-data, outside git)")
    args = ap.parse_args()

    from src.corpus.registry import CorpusSourceRegistry
    from src.corpus.blob_store import CorpusBlobStore

    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    registry = CorpusSourceRegistry(root=root)
    blobs = CorpusBlobStore(root=root)

    before = len(registry.all_records())
    papers = parse_papers()
    n_md = sum(1 for p in papers if p.md_file)
    n_primary = sum(1 for p in papers if p.pdf_name)
    n_orphan = sum(1 for p in papers if p.md_file and not p.pdf_name)
    print(json.dumps({
        "paper_dirs": len(papers),
        "with_md": n_md, "without_md": len(papers) - n_md,
        "primary_pdf_count": n_primary,
        "expected_orphan_md": n_orphan,
        "total_check": n_primary + n_orphan == len(papers),
    }, indent=2))

    if args.dry_run or not args.apply:
        print("DRY-RUN ONLY — no writes performed.")
        return

    res = register(registry, blobs, dry_run=False)
    after = len(registry.all_records())
    print(json.dumps({**{k: v for k, v in res.items() if k != "skipped"},
                      "registered_total": after,
                      "actually_new": None}, indent=2))


if __name__ == "__main__":
    main()
