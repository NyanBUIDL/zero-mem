#!/usr/bin/env python3
"""V140-01 — GENERIC corpus ingest/extract/project tool (GATE-0-ADDENDUM).

Replaces the quant_lab-specific hardcoding with a parameterized pipeline:

    corpus_generic_ingest.py \
        --source-dir <any corpus root> \
        --ks-name <knowledge space> \
        --adapter <adapter module:func> \
        --skip-list <optional json> \
        --root <corpus derived store root (dev-data, outside git)> \
        [--apply]

The quant_lab sample is only the FIRST adapter instance
(scripts/adapters/arxiv_quant_adapter.py). To import a different corpus,
register another adapter — no core change here.

Behavior (tooling-only, no src/ edits):
- uses the public CorpusSourceRegistry / CorpusBlobStore (dedup-safe);
- registers primary-pdf via register_source_with_blob (keeps blob_ref);
- registers derived-md / orphan-md via register_source (rebound blob
  through the same path so projection can extract them — fixes the
  V140-00 root cause for md units);
- optionally projects to the derived SQLite store via project_corpus
  (pass --project).

Usage for quant_lab:
    venv-python scripts/corpus_generic_ingest.py \
        --source-dir "/home/lenovo/Hermes Workspace/quant_lab" \
        --ks-name quant-theory \
        --adapter scripts.adapters.arxiv_quant_adapter:parse_corpus \
        --root "/home/lenovo/Hermes Workspace/zero-mem-dev-data/corpus-quant-lab" \
        --apply --project
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))


def _load_adapter(spec: str):
    """spec = module:attr, e.g. scripts.adapters.arxiv_quant_adapter:parse_corpus"""
    module_name, attr = spec.split(":")
    module = importlib.import_module(module_name)
    return getattr(module, attr)


def main(argv: list | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-dir", required=True)
    ap.add_argument("--ks-name", required=True)
    ap.add_argument("--adapter", required=True, help="module:func returning list[PaperDir]")
    ap.add_argument("--root", required=True)
    ap.add_argument("--skip-list", default=str(REPO / "scripts" / "corpus_skip_list.json"))
    ap.add_argument("--papers-subdir", default="papers")
    ap.add_argument("--project", action="store_true", help="also run project_corpus")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    from src.corpus.registry import CorpusSourceRegistry
    from src.corpus.blob_store import CorpusBlobStore

    registry = CorpusSourceRegistry(root=Path(args.root))
    blobs = CorpusBlobStore(root=Path(args.root))
    skip = json.loads(Path(args.skip_list).read_text())
    skip_paths = {e["path"] for e in skip.get("entries", [])}

    parse = _load_adapter(args.adapter)
    papers = parse(Path(args.source_dir), args.papers_subdir)

    before = len(registry.all_records())
    stats = {"dirs": 0, "primary_pdf": 0, "derived_md": 0, "orphan_md": 0,
             "skipped": [], "new_sources": 0, "dedup_hits": 0}
    if not args.apply:
        for pd in papers:
            stats["dirs"] += 1
            if pd.pdf_name and pd.md_file is None:
                stats["primary_pdf"] += 1
            elif pd.md_file and pd.pdf_name:
                stats["derived_md"] += 1
            elif pd.md_file:
                stats["orphan_md"] += 1
            else:
                stats["skipped"].append(pd.path.name)
        print(json.dumps(stats, indent=2))
        return

    for pd in papers:
        stats["dirs"] += 1
        ext = str(pd.path.relative_to(Path(args.source_dir))) if pd.pdf_name else \
            str(pd.md_file.relative_to(Path(args.source_dir)))
        if ext in skip_paths:
            stats["skipped"].append({"ref": ext, "reason": "skip-list"})
            continue
        meta = {"arxiv_id": pd.arxiv_id, "published": pd.date, "title": pd.title}
        if pd.pdf_name:
            pdf_path = (Path(args.source_dir) / args.papers_subdir / pd.pdf_name)
            content = pdf_path.read_bytes()
            registry.register_source_with_blob(
                content=content, external_ref=ext, kind="primary-pdf",
                profile_id="quant-lab-profile", project_id="quant-lab-corpus",
                knowledge_space_id=args.ks_name,
                custom_meta={**meta, "source_kind": "primary-pdf",
                             "original_filename": pd.pdf_name},
                provenance={"source_path": str(pdf_path), "bytes": len(content)},
                blob_store=blobs)
            stats["primary_pdf"] += 1
        if pd.md_file is not None:
            kind = "derived-md" if pd.pdf_name else "orphan-md"
            content = pd.md_file.read_bytes()
            prov = {"source_path": str(pd.md_file), "source_kind": kind}
            if kind == "orphan-md":
                prov["note"] = "original-pdf-unavailable"
            registry.register_source_with_blob(
                content=content, external_ref=ext, kind=kind,
                profile_id="quant-lab-profile", project_id="quant-lab-corpus",
                knowledge_space_id=args.ks_name,
                custom_meta={**meta, "source_kind": kind},
                provenance=prov, blob_store=blobs)
            stats["derived_md" if kind == "derived-md" else "orphan_md"] += 1

    after = len(registry.all_records())
    stats["new_sources"] = after - before

    if args.project:
        from src.corpus.derived_store import project_corpus
        import sqlite3
        conn = sqlite3.connect(str(Path(args.root) / "corpus-derived.sqlite"))
        try:
            proj = project_corpus(conn, registry, blobs)
            conn.commit()
        finally:
            conn.close()
        stats["projection"] = {k: v for k, v in proj.__dict__.items()
                               if not k.startswith("_")}

    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
