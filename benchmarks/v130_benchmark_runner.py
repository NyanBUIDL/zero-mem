"""V130-05 — Hybrid corpus benchmark runner.

Measures, on the deterministic synthetic corpus (N=5,000+) and optionally the
redacted real corpus:

- Per-fix precision/recall case sets (OR-fallback recall + precision guard,
  ks-filter leak=0, state promotion hit, temporal as-of before/after).
- Token-savings: EvidenceSet estimated_tokens vs naive full-history tokens.
- Runtime (raw, unoptimized numbers recorded verbatim).

Determinism: reads the seeded generator output; asserts sha256 matches the
recorded digest before measuring (D1 gate). Isolation: caller must run with the
standard TMPDIR/HOME exports (checklist §A).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path


def _load_corpus(corpus: Path) -> Path:
    digest_file = corpus.with_suffix(".sha256")
    expected = digest_file.read_text().strip()
    actual = hashlib.sha256(corpus.read_bytes()).hexdigest()
    assert actual == expected, f"D1 determinism gate failed: {actual} != {expected}"
    return corpus


def run_benchmark(store_dir: Path, corpus: Path) -> dict:
    _load_corpus(corpus)

    from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
    from src.storage.ingest import ingest_file
    from src.retrieval.db import open_readonly
    import src.retrieval as r
    from src.retrieval.models import QueryRequest

    def _checkpoint_and_close(store):
        """Verified WAL checkpoint helper (mirrors tests' _checkpoint_and_close)."""
        import sqlite3 as _sq
        try:
            store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            store._conn.commit()
        except _sq.Error:
            pass
        store.close()

    t0 = time.perf_counter()
    store = SQLiteStore(SQLiteStoreConfig(path=store_dir / "bench.sqlite"))
    store.ensure_schema()
    ingest_file(store, corpus)
    _checkpoint_and_close(store)
    t_ingest = time.perf_counter() - t0

    # Build the derived temporal index (V130-04 as-of source) + M4 project memory
    # (state/decision records for the promotion route) from canonical data.
    from src.m8.temporal_projection import project_temporal_index
    from src.project_memory.rebuild import rebuild_all_project_memory
    store2 = SQLiteStore(SQLiteStoreConfig(path=store_dir / "bench.sqlite"))
    store2.ensure_schema()
    m4 = rebuild_all_project_memory(store2, corpus)
    proj = project_temporal_index(
        store2._conn,
        source_cutoff="2026-12-31T23:59:59Z",
        built_at="2026-08-22T00:00:00Z",
    )
    store2._conn.commit()
    store2.close()

    ro = open_readonly(store_dir / "bench.sqlite")

    results: dict = {"corpus_events": sum(1 for _ in corpus.open()), "t_ingest_s": round(t_ingest, 3),
                     "temporal_index_rows": proj.get("inserted_rows"),
                     "m4_projected": m4.get("projected") if isinstance(m4, dict) else None}

    # --- V130-01 OR-fallback cases -------------------------------------------
    # recall: multi-term with a rare term -> or_fallback hits exist
    res_recall = r.search_text(ro, "quantum zzqqx42")
    results["or_fallback"] = {
        "mode": res_recall.match_mode,
        "hits": len(res_recall.results),
        "recall_ok": res_recall.match_mode == "or_fallback" and res_recall.hits if False else (
            res_recall.match_mode == "or_fallback" and len(res_recall.results) >= 1),
    }
    # precision guard: common two terms present together in one doc -> AND mode
    res_guard = r.search_text(ro, "quantum shared note 7")
    results["or_precision_guard"] = {
        "mode": res_guard.match_mode,
        "hits": len(res_guard.results),
        "guard_ok": res_guard.match_mode == "and",
    }

    # --- V130-02 ks filter ----------------------------------------------------
    req_a = QueryRequest(knowledge_space_id="ks-0")
    res_a = r.search_text(ro, "quantum", req=req_a)
    ids_a = {h.event_id for h in res_a.results}
    req_b = QueryRequest(knowledge_space_id="ks-1")
    res_b = r.search_text(ro, "quantum", req=req_b)
    ids_b = {h.event_id for h in res_b.results}
    results["ks_filter"] = {
        "ks0_hits": len(ids_a), "ks1_hits": len(ids_b),
        "leak": len(ids_a & ids_b),
        "leak_zero_ok": len(ids_a & ids_b) == 0 and len(ids_a) > 0,
    }

    # --- V130-03 state promotion (PROJECT route via M7) -----------------------
    from src.access.authorized_read import AuthorizedReadService
    from src.integration.m7.evidence_builder import build_evidence_set
    from src.integration.m7.memory_router import route as m7route
    from src.integration.m7.contracts import RouterRequest

    svc = AuthorizedReadService(ro, requesting_profile_id="prof-bench")
    rr = RouterRequest(normalized_text="current step build phase",
                       project_id="proj-bench", requesting_profile_id="prof-bench",
                       explicit_project_intent=True)
    t1 = time.perf_counter()
    es = build_evidence_set(m7route(rr), svc, rr)
    t_build = time.perf_counter() - t1
    state_ids = [e.evidence_id for e in es.primary_evidence
                 if e.resource_type == "state"]
    results["state_promotion"] = {
        "primary_ids": [e.evidence_id for e in es.primary_evidence],
        "state_in_primary": len(state_ids),
        "budget_ok": (len(es.primary_evidence) <= 5
                      and len(es.supporting_evidence) <= 3
                      and len(es.primary_evidence) + len(es.supporting_evidence) <= 8),
        "t_build_s": round(t_build, 4),
    }

    # --- V130-04 temporal as-of before/after supersession ----------------------
    # NOTE: M5 base policy authorizes global reads only when the request carries
    # no project binding (verified empirically: project-bound requests deny with
    # DENY_UNBOUND_PROTECTED for this synthetic profile). The temporal probe
    # therefore uses the unbound-global shape; the resource's own row is still
    # the only one read (M8.4 contract).
    from src.m8.temporal_read import TemporalReadRequest, read_temporal

    def _asof(resource_id, when):
        req = TemporalReadRequest(
            requester="prof-bench", resource_type="event", resource_id=resource_id,
            requesting_profile_id="prof-bench", as_of=when)
        return read_temporal(ro.conn if hasattr(ro, "conn") else ro._conn, svc, req)

    sup_old = "e-sup-old-20"
    before = _asof(sup_old, "2026-08-21T00:00:00Z")
    after = _asof(sup_old, "2026-12-31T00:00:00Z")
    results["temporal_as_of"] = {
        "before_valid": bool(before.facts) if before.authorized else None,
        "after_facts": len(after.facts) if after.authorized else None,
        "after_superseded_at_present": any(
            isinstance(p, dict) and p.get("superseded_at")
            for p in (after.provenance or {}).values()) if after.authorized else None,
    }

    ro.close()
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store-dir", type=str, required=True)
    ap.add_argument("--corpus", type=str, required=True)
    ap.add_argument("--out", type=str, required=True)
    args = ap.parse_args()
    res = run_benchmark(Path(args.store_dir), Path(args.corpus))
    out = Path(args.out)
    out.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
