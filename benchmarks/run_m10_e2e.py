"""M10.7 end-to-end acceptance over the REAL ingested corpus.

Exercises the actual product facade (M5 authorization -> M10.5 retrieval ->
M10.6 bounded graph -> M7 EvidenceSet) against a derived store built from the
real corpus, and asserts the permanent security invariants at real scale.

Run AFTER a rollout that kept its runtime dir:

    ZERO_MEM_M10_CORPUS_PATH=... .venv/bin/python3 benchmarks/run_m10_rollout.py --keep
    ZERO_MEM_M10_DB=<run_root>/derived.sqlite \
    .venv/bin/python3 benchmarks/run_m10_e2e.py

Emits PASS/FAIL per invariant plus a JSON summary. Read-only: it never writes to
the derived store, the canonical registry, the blob store, or the source folder.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

from m10_benchmark import (  # type: ignore[import-not-found]
    ROLLOUT_SCOPE,
    authorized_scope,
    build_corpus_graph_readonly,
    build_query_plan,
    retrieve_corpus,
)
from src.access import AccessRequest, AuthorizedReadService
from src.corpus.graph import DEFAULT_GRAPH_BOUNDS
from src.integration.m7 import RouterRequest, build_evidence_set, route
from src.retrieval.db import open_readonly

PROFILE = ROLLOUT_SCOPE["profile_id"]
PROJECT = ROLLOUT_SCOPE["project_id"]
SPACE = ROLLOUT_SCOPE["knowledge_space_id"]

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, bool(ok), detail))
    return bool(ok)


def db_path() -> Path:
    raw = os.environ.get("ZERO_MEM_M10_DB")
    if not raw:
        raise SystemExit("ZERO_MEM_M10_DB is not set (path to derived.sqlite)")
    path = Path(raw)
    if not path.is_file():
        raise SystemExit(f"derived db not found: {path}")
    return path


def sha_of(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def router(text: str, *, profile: str = PROFILE, project: str = PROJECT) -> RouterRequest:
    return RouterRequest(
        normalized_text=text,
        project_id=project,
        requesting_profile_id=profile,
        knowledge_space_ids=(SPACE,),
        explicit_research_intent=True,
    )


def evidence_for(ro, text: str, *, profile: str = PROFILE, project: str = PROJECT):
    svc = AuthorizedReadService(ro, requesting_profile_id=profile)
    req = router(text, profile=profile, project=project)
    return build_evidence_set(route(req), svc, req)


def main() -> int:
    path = db_path()
    out: dict = {"db": path.name, "scope": dict(ROLLOUT_SCOPE)}

    before_sha = sha_of(path)
    ro = open_readonly(path)
    try:
        conn = ro.conn
        cur = conn.cursor()
        units = cur.execute("SELECT COUNT(*) FROM zm_corpus_units").fetchone()[0]
        sources = cur.execute("SELECT COUNT(*) FROM zm_corpus_sources").fetchone()[0]
        out["units"] = units
        out["sources"] = sources
        check("derived store populated from real corpus", units > 0 and sources > 0,
              f"sources={sources} units={units}")

        # ---- retrieval sanity: classes of query over REAL content ----------
        # Probe phrases are selected by a DETERMINISTIC, pre-declared rule:
        # the first 5 purely-alphabetic tokens of length >= 4. Rationale (not
        # post-hoc tuning): real PDF text extraction splits words across layout
        # runs ("DEVIA TIONS", "P A THWISE"), and identifier-like tokens such as
        # "arXiv:1706.05291v3" are normalized by the query planner into
        # "arxiv1706.05291v3" while the FTS tokenizer splits the indexed text on
        # ":" -- so a raw leading-token slice probes tokenizer asymmetry rather
        # than retrieval. Alphabetic word tokens probe the retrieval path.
        rows = cur.execute(
            "SELECT unit_id, normalized_text FROM zm_corpus_units "
            "WHERE LENGTH(normalized_text) > 200 ORDER BY unit_id LIMIT 5"
        ).fetchall()
        scope = authorized_scope()
        sanity: list[dict] = []
        for row in rows:
            unit_id, text = row[0], row[1]
            words = [t for t in text.split() if t.isalpha() and len(t) >= 4][:5]
            if not words:
                continue
            phrase = " ".join(words)
            plan = build_query_plan(text=phrase, metadata={"project_id": PROJECT}, limit=10)
            hits = retrieve_corpus(conn, scope, plan)
            found = any(h.unit_id == unit_id for h in hits)
            sanity.append({"tokens": len(words), "hits": len(hits),
                           "self_retrieved": found})
        out["retrieval_sanity"] = sanity
        check("known real units are retrievable by their own words",
              all(s["self_retrieved"] for s in sanity) and bool(sanity),
              f"{sum(s['self_retrieved'] for s in sanity)}/{len(sanity)}")

        # no-match control
        plan = build_query_plan(text="zzzqqq nonexistent xyzzy",
                                metadata={"project_id": PROJECT}, limit=10)
        check("no-match query returns empty", retrieve_corpus(conn, scope, plan) == [])

        # ---- authorization: unauthorized scope sees nothing ----------------
        from src.corpus.retrieval import AuthorizedCorpusScope
        foreign = AuthorizedCorpusScope(allowed_scopes=(("other-profile", "other", "other"),))
        plan = build_query_plan(text=" ".join(rows[0][1].split()[:6]) if rows else "the",
                                metadata={}, limit=10)
        check("unauthorized scope retrieves ZERO real corpus units",
              retrieve_corpus(conn, foreign, plan) == [])

        # ---- EvidenceSet: corpus-only / mixed / bounds ---------------------
        query = " ".join(rows[0][1].split()[:6]) if rows else "market"
        es = evidence_for(ro, query)
        out["evidence"] = {
            "corpus": len(es.corpus_evidence),
            "primary": len(es.primary_evidence),
            "supporting": len(es.supporting_evidence),
        }
        check("corpus-only EvidenceSet built from real corpus",
              len(es.corpus_evidence) > 0, f"{len(es.corpus_evidence)} items")
        check("all corpus evidence typed corpus_unit",
              all(e.resource_type == "corpus_unit" for e in es.corpus_evidence))
        check("M7 bound: primary <= 5", len(es.primary_evidence) <= 5,
              str(len(es.primary_evidence)))
        check("M7 bound: supporting <= 3", len(es.supporting_evidence) <= 3,
              str(len(es.supporting_evidence)))
        check("M7 bound: total <= 8",
              len(es.primary_evidence) + len(es.supporting_evidence) <= 8)
        check("corpus evidence carries provenance",
              all(getattr(e, "provenance", None) for e in es.corpus_evidence))

        # memory-only path must still work (no corpus text in the query)
        es_mem = evidence_for(ro, "zzzqqq nonexistent xyzzy")
        check("memory-only EvidenceSet remains functional (no corpus hits)",
              len(es_mem.corpus_evidence) == 0)

        # unauthorized profile gets no corpus evidence
        es_foreign = evidence_for(ro, query, profile="intruder", project="other")
        check("foreign profile receives ZERO corpus evidence",
              len(es_foreign.corpus_evidence) == 0,
              f"{len(es_foreign.corpus_evidence)} items")

        # ---- corpus content is DATA (injection cannot gain authority) ------
        injected = [
            r[0] for r in cur.execute(
                "SELECT normalized_text FROM zm_corpus_units WHERE "
                "LOWER(normalized_text) LIKE '%ignore previous instructions%' "
                "OR LOWER(normalized_text) LIKE '%system prompt%' LIMIT 5"
            ).fetchall()
        ]
        out["injection_like_units"] = len(injected)
        es_inj = evidence_for(ro, "ignore previous instructions system prompt")
        check("instruction-like corpus text stays DATA (corpus_unit only)",
              all(e.resource_type == "corpus_unit" for e in es_inj.corpus_evidence))
        check("injection cannot raise EvidenceSet bounds",
              len(es_inj.primary_evidence) <= 5
              and len(es_inj.supporting_evidence) <= 3
              and len(es_inj.primary_evidence) + len(es_inj.supporting_evidence) <= 8)

        # ---- secrets never surface -----------------------------------------
        # GLOB, not LIKE: SQLite LIKE is case-INSENSITIVE by default, so
        # '%AKIA%' matches ordinary prose such as "Slo-vakia" split across a
        # PDF line break. Secret markers are case-SENSITIVE by definition.
        secret_hits = cur.execute(
            "SELECT COUNT(*) FROM zm_corpus_units WHERE "
            "normalized_text GLOB '*BEGIN RSA PRIVATE KEY*' "
            "OR normalized_text GLOB '*BEGIN OPENSSH PRIVATE KEY*' "
            "OR normalized_text GLOB '*AKIA*' "
            "OR normalized_text GLOB 'sk-*'"
        ).fetchone()[0]
        out["secret_bearing_units_in_store"] = secret_hits
        check("no secret-bearing unit is searchable", secret_hits == 0, str(secret_hits))

        # ---- graph: bounded reads over the real corpus ---------------------
        graph = build_corpus_graph_readonly(path)
        seed = rows[0][0] if rows else None
        if seed:
            def graph_request(profile: str, project: str, space: str) -> AccessRequest:
                return AccessRequest(
                    operation="READ",
                    requesting_profile_id=profile,
                    target_profile_ids=[profile],
                    project_ids=[project],
                    knowledge_space_ids=[space],
                    resource_type="corpus_unit",
                    include_global=True,
                )

            t0 = time.perf_counter()
            res = graph.read_neighbourhood(
                graph_request(PROFILE, PROJECT, SPACE),
                seed,
                bounds=DEFAULT_GRAPH_BOUNDS,
            )
            graph_ms = (time.perf_counter() - t0) * 1000.0
            nodes, edges = len(res.nodes), len(res.edges)
            out["graph_read"] = {
                "ms": round(graph_ms, 3),
                "nodes": nodes,
                "edges": edges,
                "bound_reached": list(res.bound_reached),
            }
            check("graph node bound <= 40", nodes <= 40, str(nodes))
            check("graph edge bound <= 80", edges <= 80, str(edges))
            check("graph depth bound <= 2", DEFAULT_GRAPH_BOUNDS.max_depth <= 2,
                  str(DEFAULT_GRAPH_BOUNDS.max_depth))
            check("graph fan-out bound <= 20", DEFAULT_GRAPH_BOUNDS.max_fan_out <= 20,
                  str(DEFAULT_GRAPH_BOUNDS.max_fan_out))
            check("authorized graph read reaches the seed",
                  res.unauthorized_hidden is False and nodes >= 1)

            # Unauthorized seed must be denied WITHOUT leaking adjacency.
            denied = graph.read_neighbourhood(
                graph_request("intruder", "other-project", "other-space"),
                seed,
                bounds=DEFAULT_GRAPH_BOUNDS,
            )
            check("unauthorized graph seed leaks no nodes", len(denied.nodes) == 0,
                  str(len(denied.nodes)))
            check("unauthorized graph seed leaks no edges", len(denied.edges) == 0,
                  str(len(denied.edges)))
            check("unauthorized graph read flags hidden",
                  denied.unauthorized_hidden is True)

            # Bounds cannot be widened past the M8 ceiling (fail closed).
            from src.corpus.graph import GraphReadBounds
            try:
                GraphReadBounds(max_nodes=41)
                check("graph bounds cannot exceed M8 ceiling", False, "41 accepted")
            except ValueError as exc:
                check("graph bounds cannot exceed M8 ceiling", True, str(exc)[:44])
    finally:
        ro.close()

    # ---- reads mutated nothing -----------------------------------------
    check("derived store byte-identical after all reads", sha_of(path) == before_sha)

    width = max(len(n) for n, _, _ in results)
    passed = sum(ok for _, ok, _ in results)
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name:<{width}} {detail}")
    print(f"\n{passed}/{len(results)} E2E invariants passed")
    out["passed"] = passed
    out["total"] = len(results)
    out["checks"] = [{"name": n, "ok": o, "detail": d} for n, o, d in results]
    target = os.environ.get("ZERO_MEM_M10_E2E_JSON")
    if target:
        Path(target).write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"[json] wrote {target}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
