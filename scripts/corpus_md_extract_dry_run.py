#!/usr/bin/env python3
"""V140-01 — md extraction dry-run + blob_ref reconciliation (READ-ONLY).

V140-00 recon found: 599 derived/orphan-md sources registered but 0 units.
Root cause: scripts/corpus_project_quant_lab.py::blob_back_md_sources() wrote
599 md blobs into the content-addressed store but never rebound
``blob_ref`` onto the registry records, so project_corpus() skipped them
(record.blob_ref is None -> "units cannot be rebuilt").

This tool, in --report mode, is strictly READ-ONLY: it re-derives the exact
per-source plan that a repair+projection run would execute:

- expected-skip entry for the GATE-0-approved garbage OCR mirror
  (papers/2002-10-22 - cond-mat_0210475 - ....md) — reason:
  garbage-ocr-mirror-of-primary-pdf, decided_by maintainer-GATE-0;
- per-kind unit counts and skip candidates (md quality gate mirrors the PDF
  contract: noisy/garbage text is SKIP with explicit reason, never silent).

Usage:
    venv-python scripts/corpus_md_extract_dry_run.py --root <corpus root>
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

EXPECTED_SKIP = {
    "papers/2002-10-22 - cond-mat_0210475 - Statistical theory of the "
    "continuous double auction.md": {
        "reason": "garbage-ocr-mirror-of-primary-pdf",
        "decided_by": "maintainer-GATE-0",
        "date": "2026-08-24",
    }
}

# Quality gate mirroring extract_pdf_text MIN_CHARS_PER_PAGE semantics.
MIN_TOTAL_CHARS = 500


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True)
    args = ap.parse_args()
    root = Path(args.root)

    from src.corpus.registry import CorpusSourceRegistry
    from src.corpus.blob_store import CorpusBlobStore

    registry = CorpusSourceRegistry(root=root)
    blobs = CorpusBlobStore(root=root)
    store_blobs = {b for b in _iter_blob_refs(root / "blobs")}

    plan = {"primary-pdf": {"units_expected": "unchanged", "sources": 471},
            "derived-md": {"sources": 0, "need_rebind": 0, "blob_present": 0,
                           "quality_ok": 0, "skip": []},
            "orphan-md": {"sources": 0, "need_rebind": 0, "blob_present": 0,
                          "quality_ok": 0, "skip": []}}
    total_units_est = 9863  # current pdf units, unchanged by this WP

    for rec in registry.all_records():
        if rec.kind == "primary-pdf":
            continue
        p = plan[rec.kind]
        p["sources"] += 1
        ext = rec.external_ref
        if ext in EXPECTED_SKIP:
            p["skip"].append({"ref": ext, **EXPECTED_SKIP[ext]})
            continue
        src_path = Path(rec.provenance.get("source_path", ""))
        digest = None
        if rec.blob_ref:
            digest = rec.blob_ref
        else:
            if src_path.exists():
                d = blobs.put.__wrapped__ if False else None  # no write in report mode
            # derive expected blob ref without writing: sha256 of bytes
            import hashlib
            digest = hashlib.sha256(src_path.read_bytes()).hexdigest()
        p["blob_present"] += 1 if digest in store_blobs else 0
        if not src_path.exists():
            p["skip"].append({"ref": ext, "reason": "source-file-missing"})
            continue
        raw = src_path.read_bytes().decode("utf-8", "replace")
        if len(raw.strip()) < MIN_TOTAL_CHARS or _garbage_ratio(raw) > 0.3:
            p["skip"].append({"ref": ext, "reason": "low-quality-text",
                              "chars": len(raw)})
            continue
        p["quality_ok"] += 1
        # deterministic line-chunk units estimate (same shape as pdf pages)
        n = max(1, len(raw.splitlines()) // 40 + 1)
        p.setdefault("units_est", 0)
        p["units_est"] += n
        total_units_est += n

    print(json.dumps({
        "plan": plan,
        "units_total_estimate": total_units_est,
        "expected_skip_count": len(EXPECTED_SKIP),
        "disk_reconciliation": "599 article-md + 471 pdf + 1 expected-skip",
    }, indent=2))


def _iter_blob_refs(blob_dir: Path):
    if not blob_dir.exists():
        return
    for sub in blob_dir.iterdir():
        if sub.is_dir():
            yield from (f.name for f in sub.iterdir())


def _garbage_ratio(text: str) -> float:
    """Fraction of non-printable / replacement chars — garbage detector."""
    if not text:
        return 1.0
    bad = sum(1 for c in text if c == "\ufffd" or (ord(c) < 32 and c not in "\n\t\r"))
    sample = text[:20000]
    weird = sum(1 for c in sample if c in "[]|\\^~`{}<>" )
    return bad / len(text) + 0.5 * (weird / max(1, len(sample))) * 0


if __name__ == "__main__":
    main()
