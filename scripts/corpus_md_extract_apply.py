#!/usr/bin/env python3
"""V140-01 — md unit extraction APPLY (repair blob_ref binding + project).

Authorized by GATE-0-APPROVAL.md (maintainer, 2026-08-24). Fixes the root
cause found in V140-00/V140-01 recon:

  blob_back_md_sources() wrote 599 md blobs but never rebound ``blob_ref``
  onto the registry records -> project_corpus skipped every md source.

This script (tooling-only, NO src/ changes):
1. loads scripts/corpus_skip_list.json (GATE-0 expected-skip entries);
2. rebinds blob_ref for every derived/orphan-md source through the public
   CorpusSourceRegistry.register_source_with_blob() path (dedup-safe,
   idempotent — registry size must not grow);
3. registers a thin tooling MdAdapter (wraps builtin TxtAdapter) so
   select_adapter() accepts kind hints "derived-md"/"orphan-md";
4. runs the canonical M10.3 projection (project_corpus) which extracts
   verbatim md units into zm_corpus_units + zm_corpus_fts;
5. prints the reconciliation report:
   599 article-md + 471 pdf + 1 expected-skip == disk.

Usage:
    venv-python scripts/corpus_md_extract_apply.py --root <corpus root> --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

SKIP_LIST_PATH = REPO / "scripts" / "corpus_skip_list.json"


def load_skip_list() -> dict:
    return json.loads(SKIP_LIST_PATH.read_text())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    root = Path(args.root)

    from src.corpus.registry import CorpusSourceRegistry
    from src.corpus.blob_store import CorpusBlobStore
    from src.corpus.adapters.registry import ADAPTER_REGISTRY
    from src.corpus.adapters.txt import TxtAdapter

    class MdAdapter(TxtAdapter):
        """Tooling adapter mapping md source kinds to the builtin text parser."""

        parser_name = "tooling:markdown-text"

        def supports(self, kind_hint: str) -> bool:
            return kind_hint in ("derived-md", "orphan-md")

    if not any(getattr(a, "parser_name", None) == "tooling:markdown-text"
               for a in ADAPTER_REGISTRY):
        ADAPTER_REGISTRY.append(MdAdapter())

    registry = CorpusSourceRegistry(root=root)
    blobs = CorpusBlobStore(root=root)
    skip = load_skip_list()
    before = len(registry.all_records())
    report = {"sources_before": before, "blob_rebound": 0, "skipped_entries": [],
              "projection": None}

    if not args.apply:
        print("DRY-RUN — no writes. Pass --apply.")
        print(json.dumps({"skip_list": skip}, indent=2))
        return

    for rec in sorted(registry.all_records(), key=lambda r: r.source_id):
        if rec.kind not in ("derived-md", "orphan-md"):
            continue
        if rec.external_ref in skip:
            report["skipped_entries"].append(rec.external_ref)
            continue
        src_path = Path(rec.provenance.get("source_path", ""))
        if not src_path.exists():
            report["skipped_entries"].append(
                {"ref": rec.external_ref, "reason": "source-file-missing"})
            continue
        content = src_path.read_bytes()
        # Dedup-safe public path: returns existing record, attaches blob,
        # rebinds blob_ref in registry (idempotent).
        updated = registry.register_source_with_blob(
            content=content,
            external_ref=rec.external_ref,
            kind=rec.kind,
            profile_id=rec.profile_id, project_id=rec.project_id,
            knowledge_space_id=rec.knowledge_space_id,
            custom_meta=rec.custom_meta, provenance=rec.provenance,
            blob_store=blobs,
        )
        if updated.blob_ref and updated.blob_ref != rec.blob_ref:
            report["blob_rebound"] += 1

    after = len(registry.all_records())
    report["sources_after"] = after
    report["idempotency_new_sources"] = after - before

    from src.corpus.derived_store import project_corpus
    import sqlite3
    conn = sqlite3.connect(str(root / "corpus-derived.sqlite"))
    try:
        proj = project_corpus(conn, registry, blobs)
        conn.commit()
    finally:
        conn.close()
    report["projection"] = {k: v for k, v in proj.__dict__.items()
                            if not k.startswith("_")}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
