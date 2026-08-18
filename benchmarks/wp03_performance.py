"""WP-03 bounded performance harness over the real M10 rollout pipeline.

This wrapper deliberately delegates to ``run_m10_rollout.py`` rather than
reimplementing capture, ingest, projection, retrieval, or rebuild paths.
100k/1M estimates are not fabricated; use ``--limit`` with an operator corpus
and record actual runs.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--json", required=True)
    args = parser.parse_args()
    if not os.environ.get("ZERO_MEM_M10_CORPUS_PATH"):
        parser.error("ZERO_MEM_M10_CORPUS_PATH is required")
    script = Path(__file__).with_name("run_m10_rollout.py")
    result = subprocess.run(
        [sys.executable, str(script), "--limit", str(args.limit), "--json", args.json],
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
