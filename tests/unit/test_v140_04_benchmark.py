"""V140-04 — retrieval-quality benchmark harness tests.

Verifies the precision@k benchmark is deterministic and reproducible (>=2 runs
identical on the deterministic part), uses the real retrieval path, and the
held-out query set has >=30 items. Does NOT re-implement retrieval.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
QUERY_FILE = REPO / "benchmarks" / "qa_quant_lab_heldout.jsonl"
CORPUS_DB = Path(
    "/home/lenovo/Hermes Workspace/zero-mem-dev-data/corpus-quant-lab/corpus-derived.sqlite"
)


def test_heldout_set_has_at_least_30_queries():
    assert QUERY_FILE.exists()
    n = sum(1 for _ in QUERY_FILE.read_text(encoding="utf-8").splitlines() if _.strip())
    assert n >= 30, f"held-out set must have >=30 queries, got {n}"


def test_benchmark_runs_and_is_reproducible():
    if not CORPUS_DB.exists():
        pytest.skip("corpus-derived.sqlite not present in dev-data")
    from benchmarks.v140_04_retrieval_bench import main as bench_main

    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = bench_main([
            "--store-path", str(CORPUS_DB),
            "--query-file", str(QUERY_FILE),
            "--runs", "3",
        ])
    assert rc == 0
    report = __import__("json").loads(buf.getvalue())
    assert report["reproducible"] is True
    assert report["n_queries"] >= 30
    # precision@k present and within [0,1]
    for k in report["k_vals"]:
        p = report["runs"][0][f"precision@{k}"]
        assert 0.0 <= p <= 1.0
    # determinism: all runs identical on the precision-bearing keys
    first = {k: v for k, v in report["runs"][0].items() if not k.endswith("_ms")}
    for r in report["runs"][1:]:
        assert {k: v for k, v in r.items() if not k.endswith("_ms")} == first


def test_benchmark_rejects_too_few_queries(tmp_path):
    from benchmarks.v140_04_retrieval_bench import main as bench_main
    import io, contextlib
    qf = tmp_path / "few.jsonl"
    qf.write_text('{"query":"x","ground_truth_unit_id":"u1","source_ref":"s","ks":"quant-theory"}\n')
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = bench_main([
            "--store-path", str(CORPUS_DB), "--query-file", str(qf), "--runs", "1",
        ])
    assert rc == 2  # <30 queries -> error
