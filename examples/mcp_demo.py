#!/usr/bin/env python3
"""V140-03 — reproducible POC demo: NON-Hermes MCP client queries Zero-Mem KB.

Runs the stdlib MCP client (examples/mcp_client_poc.py) against the real
quant_lab derived store, proving a client outside Hermes can read authorized
memory over MCP. Requires only CPython stdlib + the repo (no Hermes).

Reproduce from a clean machine:
  git clone <repo> && cd zero-mem-v123-engineering
  python3 -m venv .venv && ./.venv/bin/pip install -e .   # or use existing venv
  python3 examples/mcp_demo.py --store-path <corpus-derived.sqlite>

Expected: memory_search returns sanitized event items (no file paths, no SQL).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp_client_poc import run_poc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store-path", required=True,
                    help="Path to corpus-derived.sqlite (read-only).")
    args = ap.parse_args()

    queries = [
        ("memory_search", {"search_text": "kelly criterion", "limit": 2}),
        ("memory_search", {"search_text": "rough volatility", "limit": 2}),
        ("memory_query", {"limit": 2}),
    ]
    for tool, arguments in queries:
        print(f"\n=== tools/call {tool} {json.dumps(arguments, ensure_ascii=False)} ===")
        result = run_poc(Path(args.store_path), tool, arguments)
        # Print only the sanitized structured content (proves READ-only surface).
        env = result.get("structuredContent", result)
        print(json.dumps(env, ensure_ascii=False, indent=2)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
