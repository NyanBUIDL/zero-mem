#!/usr/bin/env python3
"""V130 corpus QL-2 — PDF text extraction via pymupdf (venv-local, allowed).

PDF is the AUTHORITATIVE source: original bytes are stored via blob_store by the
ingest script; this extractor produces DERIVED text with page provenance.

Quality contract (user requirement):
- verbatim text extraction, page-number provenance preserved;
- noisy/scanned files are marked SKIP explicitly with a reason — no silent junk,
  no batch-wide failure, no invented content;
- deterministic: same PDF -> same extraction output.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pdf_tooling_guard import require_pymupdf

MIN_CHARS_PER_PAGE = 200  # below this a PDF is likely scanned/image-only


def extract_pdf_text(pdf_path: Path) -> dict:
    """Extract per-page text. Returns {status, pages: [{page, text}], reason}."""
    pymupdf = require_pymupdf()

    try:
        doc = pymupdf.open(pdf_path.as_posix())
    except Exception as exc:
        return {"status": "SKIP", "reason": f"open_failed:{type(exc).__name__}", "pages": []}
    try:
        if doc.is_encrypted:
            return {"status": "SKIP", "reason": "encrypted_pdf", "pages": []}
        pages = []
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text")  # verbatim reading order
            pages.append({"page": i, "text": text})
        total = sum(len(p["text"]) for p in pages)
        if total < MIN_CHARS_PER_PAGE * max(1, len(pages)) // 2:
            return {"status": "SKIP",
                    "reason": f"low_text_layer:{total}_chars_over_{len(pages)}_pages",
                    "pages": []}
        return {"status": "OK", "pages": pages, "reason": None,
                "total_chars": total, "page_count": len(pages)}
    finally:
        doc.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--out", help="optional JSON output path")
    args = ap.parse_args()
    res = extract_pdf_text(Path(args.pdf))
    summary = {"pdf": args.pdf, "status": res["status"], "reason": res.get("reason"),
               "pages": res.get("page_count"), "total_chars": res.get("total_chars")}
    print(json.dumps(summary, indent=2))
    if args.out and res["status"] == "OK":
        Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
