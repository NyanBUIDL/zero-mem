"""P1 scale harness — deterministic synthetic corpus at N events through the REAL pipeline.

Complements ``run_memory_benchmark.py`` (small functional corpus). This module scales the
same canonical-JSONL -> derived-SQLite -> M7 EvidenceSet path to N events with
auto-generated gold labels, to estimate production-scale Recall@K / MRR / token savings /
latency / runtime / storage. Deterministic (fixed seed, fixed order). No LLM, no network.

Usage:
    ZERO_MEM_BENCH_ROOT=<tmp> .venv-v124/bin/python benchmarks/scale_memory_benchmark.py --scale 500 --queries 40 --json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.access.authorized_read import AuthorizedReadService  # noqa: E402
from src.integration.m7 import (  # noqa: E402
    MemoryRoute, RouterRequest, build_evidence_set, route,
)
from src.integration.m7.budget import estimate_tokens  # noqa: E402
from src.retrieval.db import open_readonly  # noqa: E402
from src.storage.ingest import ingest_file  # noqa: E402
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig  # noqa: E402
from src.project_memory import rebuild_project_memory  # noqa: E402

PROFILE = "pr1"
PROJECT = "zeromem"
KS = ("quant-trading", "engineering", "web3")


def _env(eid, event_type, text, *, project_id=None, profile_id=PROFILE,
         session_id=None, ks=None, lifecycle="active", verification="direct_tool_output",
         created=None):
    return {
        "event_id": eid, "trace_id": f"tr-{eid}", "event_type": event_type,
        "source": "scale", "schema_version": 1,
        "created_at": created or "2026-08-01T00:00:00Z",
        "observed_at": created or "2026-08-01T00:00:00Z", "sequence": 0,
        "lifecycle_status": lifecycle, "verification_status": verification,
        "confidence": "medium", "sensitivity": "internal", "retention": "persistent",
        "sanitized_content_hash": f"h-{eid}",
        "sanitized_content": {"text": text}, "redaction_audit": [],
        "project_id": project_id, "profile_id": profile_id,
        "session_id": session_id, "knowledge_space_id": ks,
    }


def _m4(eid, domain, identity, op, **kw):
    m4 = {"domain": domain, "identity": identity, "op": op, "project_id": PROJECT}
    m4.update(kw)
    return {
        "event_id": eid, "event_type": "m4_x", "project_id": PROJECT,
        "trace_id": "T-" + eid, "session_id": "S1", "profile_id": PROFILE,
        "created_at": "2026-08-05T00:00:00Z", "m4": m4,
    }


def _generate(n: int) -> tuple[list[dict], dict]:
    """Deterministic corpus (~n events) + an auto-generated gold map.

    ``n`` is a distribution budget, not an exact event count: events are sized from it as
    rounded fractions (research 50%, decisions 15%, foreign 10%, user/session/claims 5%
    each) plus stale-supersession pairs and 3 fixed project-state rows. The ACTUAL number
    of generated events is reported as ``total_events`` (never asserted == n).

    Gold maps a query id to (text, plan_route, gold_evidence_ids, assert_no, [ks]). Gold ids
    are the STABLE surface evidence_id: M3 event_id for events, decision_id for decisions.
    State rowids are discovered post-build (not guessed), so state gold is patched later.
    """
    events: list[dict] = []
    gold: dict = {}

    # --- research facts (the bulk; stable event_id gold) ---
    n_research = max(10, int(n * 0.5))
    for i in range(n_research):
        ks = KS[i % 3]
        term = f"scale-research-{i}"
        eid = f"R-{i}"
        events.append(_env(eid, "external_source", f"{term} finding about {ks} knowledge",
                           project_id="Q", ks=ks, created=f"2026-08-{i % 28 + 1:02d}T00:00:00Z"))
        # Every 8th research fact gets a stale supersession pair.
        if i % 8 == 0 and i + 1 < n_research:
            old = f"R-{i}-old"
            events.append(_env(old, "external_source", f"{term} stale value",
                               project_id="Q", ks=ks, lifecycle="superseded",
                               created="2026-08-01T00:00:00Z"))

    # --- decisions (M4; stable decision_id gold) ---
    n_dec = max(5, int(n * 0.15))
    for i in range(n_dec):
        events.append(_m4(f"M4-D{i}", "decision", f"D{i}", "create",
                          decision_key=f"key-{i}", statement=f"decision number {i}",
                          state="accepted", lifecycle_status="active",
                          effective_at=f"2026-08-{i % 28 + 1:02d}T00:00:00Z"))

    # --- user preferences ---
    n_user = max(3, int(n * 0.05))
    for i in range(n_user):
        events.append(_env(f"U-{i}", "user_statement", f"user preference {i}",
                           project_id=None, profile_id=PROFILE,
                           created="2026-08-02T00:00:00Z"))

    # --- session decisions ---
    n_sess = max(3, int(n * 0.05))
    for i in range(n_sess):
        events.append(_env(f"S-{i}", "decision", f"session decision {i}",
                           project_id=PROJECT, session_id="S1",
                           created="2026-08-09T00:00:00Z"))

    # --- assistant claims (must never be primary) ---
    n_claim = max(3, int(n * 0.05))
    for i in range(n_claim):
        events.append(_env(f"C-{i}", "assistant_claim", f"claim {i}",
                           project_id=PROJECT, lifecycle="candidate",
                           verification="none", created="2026-08-06T00:00:00Z"))

    # --- foreign-profile noise (isolation) ---
    n_foreign = max(3, int(n * 0.1))
    for i in range(n_foreign):
        events.append(_env(f"F-{i}", "decision", f"foreign decision {i}",
                           project_id=PROJECT, profile_id="foreign",
                           created="2026-08-03T00:00:00Z"))

    # --- project state (one active step + docker stale pair) ---
    events.append(_m4("M4-STATE-1", "state", "S1", "create", state_key="step",
                      state_value="M10.7 final acceptance", lifecycle_status="active",
                      effective_at="2026-08-10T00:00:00Z"))
    events.append(_m4("M4-STATE-DOCK-OLD", "state", "S2", "create", state_key="docker",
                      state_value="failed", lifecycle_status="superseded",
                      effective_at="2026-08-01T00:00:00Z"))
    events.append(_m4("M4-STATE-DOCK", "state", "S2", "update", state_key="docker",
                      state_value="fixed", lifecycle_status="active",
                      effective_at="2026-08-08T00:00:00Z"))

    # --- auto-generated gold queries (stable ids only; state patched post-build) ---
    for i in range(min(20, n_dec)):
        gold[f"SC-D{i}"] = (f"decision number {i}", MemoryRoute.PROJECT, (f"D{i}",), ())
    for i in range(min(20, n_research)):
        ks = KS[i % 3]
        gold[f"SC-R{i}"] = (f"scale-research-{i} finding", MemoryRoute.RESEARCH,
                            (f"R-{i}",), (), ks)
    for i in range(min(5, n_user)):
        gold[f"SC-U{i}"] = (f"user preference {i}", MemoryRoute.USER, (f"U-{i}",), ())
    for i in range(min(5, n_sess)):
        gold[f"SC-S{i}"] = (f"session decision {i}", MemoryRoute.SESSION, (f"S-{i}",), ())
    # state queries (gold patched post-build with discovered rowids)
    gold["SC-STEP"] = ("What is the current project step?", MemoryRoute.PROJECT, None, ())
    gold["SC-DOCKER"] = ("Is the docker login fixed?", MemoryRoute.PROJECT, None, ())

    return events, gold


def _build_store(root: Path, events: list[dict]):
    store = SQLiteStore(SQLiteStoreConfig(path=root / "m.sqlite"))
    store.ensure_schema()
    jl = root / "memory.jsonl"
    jl.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    ingest_file(store, jl)
    m4jl = root / "m4.jsonl"
    m4events = [e for e in events if e.get("event_type") == "m4_x"]
    m4jl.write_text("\n".join(json.dumps(e) for e in m4events) + "\n")
    rebuild_project_memory(store, m4jl, project_id=PROJECT)
    store._conn.commit()
    state_rows = store._conn.execute(
        "SELECT id, state_key, lifecycle_status FROM zm_project_state ORDER BY id"
    ).fetchall()
    state_map = {r["state_key"]: r["id"] for r in state_rows if r["lifecycle_status"] == "active"}
    store.close()
    ro = open_readonly(root / "m.sqlite")
    return ro, state_map


def _run(ro, events, gold, state_map):
    svc = AuthorizedReadService(ro, requesting_profile_id=PROFILE)
    rows = []
    lat = []
    for qid, (text, plan_route, gold_ids, assert_no, *rest) in gold.items():
        ks = rest[0] if rest else ()
        # patch state gold with discovered rowids
        if gold_ids is None:
            if qid == "SC-STEP":
                gold_ids = (str(state_map.get("step", -1)),)
            elif qid == "SC-DOCKER":
                gold_ids = (str(state_map.get("docker", -1)),)
        req = RouterRequest(
            normalized_text=text, project_id=PROJECT if plan_route is MemoryRoute.PROJECT else None,
            session_id="S1" if plan_route is MemoryRoute.SESSION else None,
            requesting_profile_id=PROFILE, target_profile_ids=(PROFILE,),
            knowledge_space_ids=ks, explicit_project_intent=(plan_route is MemoryRoute.PROJECT),
            explicit_research_intent=(plan_route is MemoryRoute.RESEARCH),
            explicit_user_intent=(plan_route is MemoryRoute.USER),
            explicit_session_intent=(plan_route is MemoryRoute.SESSION),
        )
        dec = route(req)
        t0 = time.perf_counter()
        es = build_evidence_set(dec, svc, req)
        lat.append((time.perf_counter() - t0) * 1000.0)
        ids = [e.evidence_id for e in es.primary_evidence + es.supporting_evidence]
        hit = [g for g in gold_ids if g in ids]
        leaked = [a for a in assert_no if a in ids]
        rows.append({
            "id": qid, "actual_route": dec.route.value,
            "gold_ids": list(gold_ids), "recall@8": (len(hit) / len(gold_ids)) if gold_ids else 1.0,
            "leaked": leaked, "stale_safe": not leaked,
            "evidence_ids": ids, "estimated_tokens": es.estimated_tokens,
        })
    recalls = [r["recall@8"] for r in rows if r["gold_ids"]]
    mrr = 0.0
    for r in rows:
        if not r["gold_ids"]:
            continue
        for rank, eid in enumerate(r["evidence_ids"], start=1):
            if eid in r["gold_ids"]:
                mrr += 1.0 / rank
                break
    mrr /= max(1, sum(1 for r in rows if r["gold_ids"]))
    p = sorted(lat)
    return {
        "queries": len(rows),
        "mean_recall@8": round(statistics.mean(recalls), 4) if recalls else None,
        "mean_mrr": round(mrr, 4),
        "stale_safe_rate": round(sum(r["stale_safe"] for r in rows) / len(rows), 4),
        "avg_evidence_tokens": round(statistics.mean(r["estimated_tokens"] for r in rows), 1),
        "latency_p50_ms": round(statistics.median(p), 3),
        "latency_p95_ms": round(p[min(len(p) - 1, int(0.95 * len(p)))], 3),
        "rows": rows,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scale", type=int, default=500)
    ap.add_argument("--root", type=str, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else Path(tempfile.mkdtemp(prefix="zm-scale-")).resolve()
    root.mkdir(parents=True, exist_ok=True)

    events, gold = _generate(args.scale)
    t0 = time.perf_counter()
    ro, state_map = _build_store(root, events)
    build_s = time.perf_counter() - t0
    stats = _run(ro, events, gold, state_map)
    stats.update({
        "scale": args.scale,
        "total_events": len(events),
        "build_seconds": round(build_s, 2),
        "db_bytes": (root / "m.sqlite").stat().st_size,
    })
    # determinism: run twice and compare row evidence ids
    stats2 = _run(ro, events, gold, state_map)
    stats["deterministic_repeat"] = (
        [r["evidence_ids"] for r in stats["rows"]]
        == [r["evidence_ids"] for r in stats2["rows"]]
    )
    ro.close()
    if args.json:
        print(json.dumps(stats, indent=2, sort_keys=True))
    else:
        print(f"scale={stats['scale']} events={stats['total_events']} queries={stats['queries']}")
        print(f"  build={stats['build_seconds']}s db={stats['db_bytes']}B")
        print(f"  mean_recall@8={stats['mean_recall@8']} mean_mrr={stats['mean_mrr']} stale_safe={stats['stale_safe_rate']}")
        print(f"  avg_tokens={stats['avg_evidence_tokens']} p50={stats['latency_p50_ms']}ms p95={stats['latency_p95_ms']}ms")
        print(f"  deterministic_repeat={stats['deterministic_repeat']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())