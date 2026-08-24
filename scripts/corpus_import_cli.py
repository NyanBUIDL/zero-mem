#!/usr/bin/env python3
"""V140-03 — Import CLI entry point (offline corpus import into Zero-Mem).

Thin, stable command-line front-end for the generic corpus ingest pipeline
(V140-01 GATE-0-ADDENDUM). It does NOT re-implement ingest logic: it delegates
to scripts.corpus_generic_ingest (which uses the public CorpusSourceRegistry /
CorpusBlobStore / project_corpus). This keeps the import surface parameterized
and repo-local (no hard-coded corpus paths) while giving a single, documented
command operators can run offline.

Default adapter is the arxiv-quant instance; any other corpus only needs a new
adapter module registered — no core change.

Examples
--------
  # quant_lab import (the bundled sample)
  venv-python scripts/corpus_import_cli.py \
      --source-dir "/home/lenovo/Hermes Workspace/quant_lab" \
      --root "/home/lenovo/Hermes Workspace/zero-mem-dev-data/corpus-quant-lab" \
      --apply --project

  # arbitrary corpus with a custom adapter
  venv-python scripts/corpus_import_cli.py \
      --source-dir /path/to/corpus --ks-name my-space \
      --adapter scripts.adapters.my_adapter:parse_corpus \
      --root /path/to/dev-data/corpus-my-space --apply --project
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

_DEFAULT_ADAPTER = "scripts.adapters.arxiv_quant_adapter:parse_corpus"
_DEFAULT_KS = "quant-theory"
_DEFAULT_PAPERS_SUBDIR = "papers"


def _build_argv(args) -> list:
    from scripts.corpus_generic_ingest import main as ingest_main
    argv = [
        "--source-dir", str(args.source_dir),
        "--ks-name", args.ks_name,
        "--adapter", args.adapter,
        "--root", str(args.root),
        "--papers-subdir", args.papers_subdir,
        "--skip-list", str(args.skip_list),
    ]
    if args.apply:
        argv.append("--apply")
    if args.project:
        argv.append("--project")
    return argv


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--source-dir", required=True,
                    help="Corpus root directory (read-only source).")
    ap.add_argument("--root", required=True,
                    help="Corpus derived-store root (dev-data, outside git).")
    ap.add_argument("--ks-name", default=_DEFAULT_KS,
                    help=f"Knowledge space name (default: {_DEFAULT_KS}).")
    ap.add_argument("--adapter", default=_DEFAULT_ADAPTER,
                    help=f"Adapter module:func (default: {_DEFAULT_ADAPTER}).")
    ap.add_argument("--papers-subdir", default=_DEFAULT_PAPERS_SUBDIR,
                    help=f"PDF subdir (default: {_DEFAULT_PAPERS_SUBDIR}).")
    ap.add_argument("--skip-list",
                    default=str(REPO / "scripts" / "corpus_skip_list.json"),
                    help="Optional skip-list JSON.")
    ap.add_argument("--apply", action="store_true",
                    help="Actually register sources (default: dry-run stats).")
    ap.add_argument("--project", action="store_true",
                    help="Also run project_corpus after register.")
    args = ap.parse_args()

    from scripts.corpus_generic_ingest import main as ingest_main
    return ingest_main(_build_argv(args))


if __name__ == "__main__":
    raise SystemExit(main())
