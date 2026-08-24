#!/usr/bin/env python3
"""V140-04 — retrieval-quality benchmark (precision@k) for the quant_lab corpus.

Stdlib-only, deterministic, zero-LLM. Reuses the EXACT product retrieval path
(src.corpus.retrieval.retrieve_corpus + AuthorizedCorpusScope + build_query_plan)
so the numbers reflect real retrieval behaviour, not a re-implementation.

What it measures
----------------
For each held-out query (benchmarks/qa_quant_lab_heldout.jsonl), the ground-truth
unit is the unit the query snippet was drawn from. We ask: does the authorized
top-K retrieval return that unit? precision@k = fraction of queries whose
ground-truth unit appears in the top-K results.

This is a SELF-RETRIEVAL precision probe (the standard way to baseline a
knowledge-base retriever when no external relevance judgement exists). It is an
INPUT to the v1.5 semantic decision — it does NOT recommend v1.5.

Determinism
-----------
No sampling, no random order. Query order is file order. Retrieval ordering is
deterministic (lexical score, then unit_id tiebreak). Two runs MUST produce
identical aggregate numbers — the harness prints a run fingerprint so the caller
can confirm reproducibility.

Baseline comparison
-------------------
The legacy synthetic-corpus baseline (docs/v1.4/EVIDENCE.md) reported
recall@8 = 0.519 (N=500, different corpus, different metric). precision@k and
recall@k are different lenses; we report both side by side but do not claim one
subsumes the other.

Usage
-----
  python3 benchmarks/v140_04_retrieval_bench.py \
      --store-path <corpus-derived.sqlite> \
      --query-file benchmarks/qa_quant_lab_heldout.jsonl \
      [--ks quant-theory] [--k 1 3 5 8 10] [--limit 10]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


@dataclass
class QueryItem:
    query: str
    ground_truth_unit_id: str
    source_ref: str
    ks: str


def _load_queries(path: Path) -> List[QueryItem]:
    items: List[QueryItem] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        items.append(QueryItem(
            query=d["query"],
            ground_truth_unit_id=d["ground_truth_unit_id"],
            source_ref=d.get("source_ref", ""),
            ks=d.get("ks", "quant-theory"),
        ))
    return items


def _run_once(store_path: Path, queries: List[QueryItem], ks: str,
             ks_allowed: bool, k_vals: List[int], limit: int) -> Dict[str, float]:
    """Single deterministic benchmark pass. Returns per-k precision + timing."""
    from src.corpus.query_planner import build_query_plan
    from src.corpus.retrieval import AuthorizedCorpusScope, retrieve_corpus
    from src.retrieval.db import open_readonly

    store = open_readonly(store_path)
    conn = store.conn  # retrieve_corpus expects a raw sqlite3 connection
    try:
        # Authorized scope: caller-supplied knowledge space only (fail-closed if
        # the unit is outside it). We do NOT grant global/unowned read.
        scope = AuthorizedCorpusScope(allowed_scopes=(
            (None, None, ks) if ks_allowed else (None, None, None),
        ))
        hits_at_k: Dict[int, int] = {k: 0 for k in k_vals}
        latencies: List[float] = []
        for q in queries:
            plan = build_query_plan(q.query, limit=limit)
            t0 = time.perf_counter()
            results = retrieve_corpus(conn, scope, plan)
            dt = time.perf_counter() - t0
            latencies.append(dt)
            top_ids = [h.unit_id for h in results[: max(k_vals)]]
            for k in k_vals:
                if q.ground_truth_unit_id in top_ids[:k]:
                    hits_at_k[k] += 1
        n = len(queries)
        precision: Dict[str, float] = {
            f"precision@{k}": round(hits_at_k[k] / n, 4) for k in k_vals
        }
        precision["n_queries"] = n
        precision["mean_latency_ms"] = round(1000.0 * sum(latencies) / n, 3)
        precision["p95_latency_ms"] = round(
            1000.0 * sorted(latencies)[min(int(n * 0.95), n - 1)], 3)
        return precision
    finally:
        conn.close()
        store.close()


def _fingerprint(store_path: Path, queries: List[QueryItem], k_vals, limit) -> str:
    h = hashlib.sha256()
    h.update(str(store_path).encode())
    h.update(str(len(queries)).encode())
    h.update(",".join(str(k) for k in k_vals).encode())
    h.update(str(limit).encode())
    for q in queries:
        h.update(q.ground_truth_unit_id.encode())
    return h.hexdigest()[:16]


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store-path", required=True)
    ap.add_argument("--query-file",
                     default=str(REPO / "benchmarks" / "qa_quant_lab_heldout.jsonl"))
    ap.add_argument("--ks", default="quant-theory")
    ap.add_argument("--k", nargs="+", type=int, default=[1, 3, 5, 8, 10])
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--runs", type=int, default=2,
                    help="Number of identical reproducibility runs (default 2).")
    args = ap.parse_args(argv)

    queries = _load_queries(Path(args.query_file))
    if len(queries) < 30:
        sys.stderr.write(f"ERROR: need >=30 held-out queries, got {len(queries)}\n")
        return 2

    fp = _fingerprint(Path(args.store_path), queries, args.k, args.limit)
    runs = []
    for _ in range(max(1, args.runs)):
        runs.append(_run_once(Path(args.store_path), queries, args.ks, True,
                               args.k, args.limit))

    # Reproducibility proof: deterministic retrieval ordering must be identical.
    # Latency is excluded from the equivalence check (timing noise is expected).
    def _deterministic_part(r):
        return {k: v for k, v in r.items() if not k.endswith("_ms")}
    reproducible = all(_deterministic_part(r) == _deterministic_part(runs[0]) for r in runs)

    report = {
        "fingerprint": fp,
        "store_path": str(Path(args.store_path)),
        "ks": args.ks,
        "n_queries": len(queries),
        "k_vals": args.k,
        "limit": args.limit,
        "runs": runs,
        "reproducible": reproducible,
        # Legacy baseline for context only (different corpus + metric).
        "legacy_baseline_ref": {"metric": "recall@8", "value": 0.519, "N": 500,
                                 "note": "synthetic corpus, not directly comparable"},
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if reproducible else 3


if __name__ == "__main__":
    raise SystemExit(main())
