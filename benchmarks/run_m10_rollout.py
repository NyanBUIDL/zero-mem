"""M10.7 rollout runner — executes the real pipeline and emits sanitized metrics.

Usage (operator input only; nothing here is product configuration):

    ZERO_MEM_M10_CORPUS_PATH=/path/to/papers \
    .venv/bin/python3 benchmarks/run_m10_rollout.py [--limit N] [--json OUT]

Stages: discover -> register -> extraction census -> project (first ingest)
-> second unchanged sync (idempotence) -> retrieval benchmark -> graph
-> rebuild equivalence. Read-only against the source folder throughout.
"""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from pathlib import Path

from m10_benchmark import (  # type: ignore[import-not-found]
    ROLLOUT_SCOPE,
    SOURCE_LABEL,
    CorpusBlobStore,
    CorpusSourceRegistry,
    IngestMetrics,
    bench_queries,
    build_corpus_graph,
    corpus_path,
    dir_size,
    discover,
    extraction_census,
    hash_digest,
    logical_digest,
    open_writer,
    peak_rss_bytes,
    project_corpus,
    rebuild_from_corpus,
    register_all,
    repeat_consistency,
    report_dict,
    writer_conn,
)
from src.corpus.versioning import build_version_chain
from src.retrieval.db import open_readonly

#: Deterministic benchmark query set. Constructed BEFORE seeing any results,
#: from generic academic/quant vocabulary plus structural terms that any arXiv
#: paper corpus contains. Includes deliberate no-match controls. No LLM used,
#: no post-hoc selection of queries that happened to succeed.
BENCH_QUERIES: list[str] = [
    # distinctive multi-term lexical
    "limit order book price impact",
    "stochastic volatility model calibration",
    "empirical distribution of returns",
    "market microstructure liquidity",
    "portfolio optimization mean variance",
    "time series autocorrelation function",
    "brownian motion diffusion process",
    "power law scaling exponent",
    "monte carlo simulation estimator",
    "hidden markov regime switching",
    # single distinctive terms
    "arbitrage",
    "entropy",
    "eigenvalue",
    "correlation matrix",
    "heavy tails",
    # structural / metadata-ish terms
    "abstract introduction conclusion",
    "references bibliography",
    "theorem proof lemma",
    "figure table caption",
    "appendix derivation",
    # deliberate no-match controls (nonsense tokens)
    "zzzqqqxxx nonexistent token",
    "unlikelywordzzz banana helicopter",
]


def human(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0  # type: ignore[assignment]
    return str(n)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="cap files (0 = all)")
    ap.add_argument("--json", type=str, default="", help="write metrics JSON here")
    ap.add_argument("--keep", action="store_true", help="keep runtime dir")
    args = ap.parse_args()

    root = corpus_path()
    out: dict = {"source_label": SOURCE_LABEL, "scope": dict(ROLLOUT_SCOPE)}

    # ---------------- discovery (read-only) ----------------
    t0 = time.perf_counter()
    files, inv = discover(root)
    inv["discovery_s"] = round(time.perf_counter() - t0, 3)
    if args.limit:
        files = files[: args.limit]
    inv["selected_for_rollout"] = len(files)
    out["inventory"] = inv
    print(f"[discover] {inv['regular_files']} files, "
          f"{len(files)} selected, {human(inv['total_bytes'])}")

    run_root = Path(tempfile.mkdtemp(prefix="hermes-verify-m107-run-"))
    corpus_state = run_root / "corpus"
    corpus_state.mkdir(parents=True, exist_ok=True)
    db_path = run_root / "derived.sqlite"

    try:
        blob = CorpusBlobStore(root=corpus_state)
        registry = CorpusSourceRegistry(root=corpus_state)

        # ---------------- first ingest ----------------
        t0 = time.perf_counter()
        metrics, hashes = register_all(files, registry, blob)
        reg_s = time.perf_counter() - t0
        print(f"[register] {metrics.registered}/{metrics.discovered} in {reg_s:.1f}s")

        t0 = time.perf_counter()
        extraction_census(files, metrics)
        census_s = time.perf_counter() - t0
        print(f"[extract-census] complete={metrics.extract_complete} "
              f"image_only={metrics.extract_image_only} "
              f"corrupt={metrics.extract_corrupt} in {census_s:.1f}s")

        t0 = time.perf_counter()
        writer = open_writer(db_path)
        conn = writer_conn(writer)
        report = project_corpus(conn, registry, blob_store=blob)
        conn.commit()
        writer.close()
        proj_s = time.perf_counter() - t0
        metrics.units_projected = report.units_projected
        metrics.sources_projected = report.sources_projected
        metrics.units_rejected_secret = report.units_rejected_secret
        metrics.elapsed_s = round(reg_s + census_s + proj_s, 3)
        chain = build_version_chain(registry.all_records())
        metrics.versions = sum(
            len(v) for v in getattr(chain, "versions_by_scope", {}).values()
        ) or len(registry.all_records())
        print(f"[project] sources={report.sources_projected} "
              f"units={report.units_projected} "
              f"secret_rejected={report.units_rejected_secret} in {proj_s:.1f}s")

        out["first_ingest"] = metrics.as_dict()
        out["first_ingest"]["register_s"] = round(reg_s, 3)
        out["first_ingest"]["census_s"] = round(census_s, 3)
        out["first_ingest"]["projection_s"] = round(proj_s, 3)
        out["first_ingest"]["projection_report"] = report_dict(report)
        out["first_ingest"]["failures_sample"] = metrics.failures[:10]
        out["storage"] = {
            "blob_bytes": dir_size(corpus_state),
            "derived_db_bytes": db_path.stat().st_size,
            "peak_rss_bytes": peak_rss_bytes(),
        }
        print(f"[storage] blobs={human(out['storage']['blob_bytes'])} "
              f"db={human(out['storage']['derived_db_bytes'])} "
              f"peak_rss={human(out['storage']['peak_rss_bytes'])}")

        # ---------------- graph ----------------
        t0 = time.perf_counter()
        writer = open_writer(db_path)
        conn = writer_conn(writer)
        graph_report = build_corpus_graph(conn)
        conn.commit()
        writer.close()
        graph_s = time.perf_counter() - t0
        out["graph"] = {
            "build_s": round(graph_s, 3),
            "report": report_dict(graph_report),
        }
        print(f"[graph] {out['graph']['report']} in {graph_s:.1f}s")

        # Baseline logical digest is captured AFTER graph projection so the
        # second-sync comparison is like-for-like (graph relations included).
        digest_before = logical_digest(db_path)
        out["logical_digest_first"] = digest_before
        out["logical_digest_first_sha"] = hash_digest(digest_before)

        # ---------------- second unchanged sync ----------------
        t0 = time.perf_counter()
        registry2 = CorpusSourceRegistry(root=corpus_state)
        metrics2, hashes2 = register_all(files, registry2, blob)
        writer = open_writer(db_path)
        conn = writer_conn(writer)
        report2 = project_corpus(conn, registry2, blob_store=blob)
        conn.commit()
        writer.close()
        sync_s = time.perf_counter() - t0
        digest_after_sync = logical_digest(db_path)
        out["second_sync"] = {
            "elapsed_s": round(sync_s, 3),
            "registered": metrics2.registered,
            "distinct_source_ids": metrics2.distinct_source_ids,
            "projection_report": report_dict(report2),
            "logical_digest": digest_after_sync,
            "digest_unchanged": digest_after_sync == digest_before,
            "digest_diff": {
                k: {"first": digest_before[k], "second": digest_after_sync[k]}
                for k in digest_before
                if digest_before[k] != digest_after_sync.get(k)
            },
            "new_sources": digest_after_sync["sources"] - digest_before["sources"],
            "new_units": digest_after_sync["units"] - digest_before["units"],
        }
        print(f"[second-sync] {sync_s:.1f}s new_sources="
              f"{out['second_sync']['new_sources']} "
              f"new_units={out['second_sync']['new_units']} "
              f"digest_unchanged={out['second_sync']['digest_unchanged']}")

        # ---------------- retrieval benchmark ----------------
        ro = open_readonly(db_path)
        try:
            out["retrieval"] = bench_queries(ro.conn, BENCH_QUERIES)
            out["retrieval"]["deterministic_repeat"] = repeat_consistency(
                ro.conn, BENCH_QUERIES[:8]
            )
        finally:
            ro.close()
        r = out["retrieval"]
        print(f"[retrieval] q={r['queries']} hits={r['hits']} no_hits={r['no_hits']} "
              f"median={r['median_ms']}ms max={r['max_ms']}ms "
              f"p95={r.get('p95_ms')}ms repeat={r['deterministic_repeat']}")

        # ---------------- rebuild equivalence ----------------
        # A full DERIVED rebuild re-runs BOTH derived stages: M10.4 projection
        # and the M10.6 graph. rebuild_from_corpus drops zm_corpus_relations by
        # design, so the graph must be re-projected for a like-for-like digest.
        t0 = time.perf_counter()
        writer = open_writer(db_path)
        conn = writer_conn(writer)
        rebuild_report = rebuild_from_corpus(conn, registry, blob_store=blob)
        conn.commit()
        writer.close()
        writer = open_writer(db_path)
        conn = writer_conn(writer)
        regraph_report = build_corpus_graph(conn)
        conn.commit()
        writer.close()
        rebuild_s = time.perf_counter() - t0
        digest_rebuilt = logical_digest(db_path)
        out["rebuild"] = {
            "elapsed_s": round(rebuild_s, 3),
            "report": report_dict(rebuild_report),
            "regraph_report": report_dict(regraph_report),
            "logical_digest": digest_rebuilt,
            "digest_sha": hash_digest(digest_rebuilt),
            "equivalent_to_first": digest_rebuilt == digest_before,
            "digest_diff": {
                k: {"first": digest_before[k], "rebuilt": digest_rebuilt.get(k)}
                for k in digest_before
                if digest_before[k] != digest_rebuilt.get(k)
            },
        }
        print(f"[rebuild] {rebuild_s:.1f}s equivalent="
              f"{out['rebuild']['equivalent_to_first']}")

        if args.json:
            Path(args.json).write_text(json.dumps(out, indent=2), encoding="utf-8")
            print(f"[json] wrote {args.json}")
        return 0
    finally:
        if not args.keep:
            shutil.rmtree(run_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
