"""P1 — Deterministic memory benchmark: route accuracy, Recall@K, MRR,
stale-state correctness, conflict visibility, isolation, latency, token savings.

This is benchmark infrastructure ONLY. It builds a deterministic synthetic
labeled memory store through the REAL product pipeline (canonical JSONL ->
derived SQLite via ``ingest_file``/``rebuild_project_memory``), then evaluates
the REAL M7 EvidenceSet path (``route`` -> ``AuthorizedReadService`` ->
``build_evidence_set``) against gold labels.

What is measured (and honestly documented):
  * Plan route accuracy    — router decision == benchmark-plan expected route
  * Contract route accuracy— router decision == the router's OWN documented
                             precedence for the same text (freshness > global >
                             project > session > research > user > no_memory)
  * Recall@5 / Recall@8    — gold evidence present in primary / primary+supporting
  * MRR                    — reciprocal rank of first gold item in the bounded,
                              deterministically-ordered evidence sequence
  * Stale safety           — superseded ids never appear in the bounded set
  * Active recall on stale — the active (superseding) gold id is present
  * Conflict visibility    — conflicted evidence remains visible when retrieval
                             succeeds (dedicated "funding value" queries)
  * Claim non-promotion    — assistant_claim never lands in PRIMARY
  * Isolation              — a foreign profile with its own identity leaks nothing
  * Latency p50/p95        — per EvidenceSet build (after warmup)
  * Token savings          — EvidenceSet estimated_tokens vs full-history estimate

No LLM, no network, no product mutation. Read-only after store construction.
Deterministic: identical run root -> identical JSON/evidence ids (verified by
running the query set twice).

Known measurement caveats (v2):
  * PROJECT-route gold is M4-record ids only. M3 memory events (E-*) are not
    retrievable through the M4 project surface; they are exercised through
    RESEARCH / SESSION / USER / GLOBAL routes instead.
  * Multi-term RESEARCH queries whose words are absent from every indexed doc
    return ZERO under current FTS AND semantics (plan's B11/B16 wording does
    exactly that); dedicated term-present queries (C-QUANT, C-FUND) measure the
    same semantics with retrieval actually succeeding.
  * History/as-of reads (B29) are not wired into the standard EvidenceSet; a
    superseded id is expected to be absent, which is reported honestly.

Usage:
    ZERO_MEM_BENCH_ROOT=<tmp> python benchmarks/run_memory_benchmark.py [--json]
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
    MemoryRoute,
    RouterRequest,
    build_evidence_set,
    route,
)
from src.integration.m7.budget import estimate_tokens  # noqa: E402
from src.retrieval.db import open_readonly  # noqa: E402
from src.storage.ingest import ingest_file  # noqa: E402
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig  # noqa: E402
from src.project_memory import rebuild_project_memory, rebuild_all_project_memory  # noqa: E402

BENCHMARK_VERSION = "memory-recall-v2"
PROFILE = "pr1"
PROJECT = "zeromem"

TS0 = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Synthetic labeled corpus
# ---------------------------------------------------------------------------

def _env(event_id: str, **over) -> dict:
    base = dict(
        event_id=event_id,
        trace_id=f"tr-{event_id}",
        event_type="tool_observation",
        source="benchmark",
        schema_version=1,
        created_at=TS0,
        observed_at=TS0,
        sequence=0,
        lifecycle_status="observed",
        verification_status="none",
        confidence="medium",
        sensitivity="internal",
        retention="persistent",
        sanitized_content_hash=f"h-{event_id}",
        sanitized_content={"text": f"clean content for {event_id}"},
        redaction_audit=[],
    )
    base.update(over)
    return base


def _m4(event_id: str, domain: str, identity: str, op: str, **kw) -> dict:
    m4 = {"domain": domain, "identity": identity, "op": op, "project_id": PROJECT}
    m4.update(kw)
    return {
        "event_id": event_id, "event_type": "m4_x", "project_id": PROJECT,
        "trace_id": "T-" + event_id, "session_id": "S1", "profile_id": PROFILE,
        "created_at": "2026-08-05T00:00:00Z", "m4": m4,
    }


def _memory_events() -> list[dict]:
    """M3 memory events: decisions, states, user prefs, research facts, conflict pair."""
    return [
        # Project facts
        _env("E-STEP1", event_type="verified_state", project_id=PROJECT, profile_id=PROFILE,
             created_at="2026-08-10T00:00:00Z", observed_at="2026-08-10T00:00:00Z",
             lifecycle_status="active", verification_status="deterministic_verification",
             sanitized_content={"text": "current project step is M10.7 final acceptance"}),
        _env("E-CANONICAL", event_type="decision", project_id=PROJECT, profile_id=PROFILE,
             created_at="2026-08-02T00:00:00Z", observed_at="2026-08-02T00:00:00Z",
             lifecycle_status="active", verification_status="user_confirmation",
             sanitized_content={"text": "canonical store is JSONL and SQLite derived; Obsidian is projection"}),
        _env("E-OBSIDIAN", event_type="decision", project_id=PROJECT, profile_id=PROFILE,
             created_at="2026-08-03T00:00:00Z", observed_at="2026-08-03T00:00:00Z",
             lifecycle_status="active", verification_status="user_confirmation",
             sanitized_content={"text": "latest decision on Obsidian role is curated projection only"}),
        _env("E-BUDGET", event_type="decision", project_id=PROJECT, profile_id=PROFILE,
             created_at="2026-08-04T00:00:00Z", observed_at="2026-08-04T00:00:00Z",
             lifecycle_status="active", verification_status="user_confirmation",
             sanitized_content={"text": "evidence budget is five primary and three supporting and six thousand tokens"}),
        _env("E-LLMZERO", event_type="decision", project_id=PROJECT, profile_id=PROFILE,
             created_at="2026-08-05T00:00:00Z", observed_at="2026-08-05T00:00:00Z",
             lifecycle_status="active", verification_status="user_confirmation",
             sanitized_content={"text": "memory operation LLM calls are zero"}),
        # Stale-state pair: old failure superseded by fix
        _env("E-DOCKER-OLD", event_type="tool_observation", project_id=PROJECT, profile_id=PROFILE,
             created_at="2026-08-01T00:00:00Z", observed_at="2026-08-01T00:00:00Z",
             lifecycle_status="superseded", verification_status="direct_tool_output",
             sanitized_content={"text": "docker login failed unauthorized"}),
        _env("E-DOCKER-FIX", event_type="verified_state", project_id=PROJECT, profile_id=PROFILE,
             created_at="2026-08-08T00:00:00Z", observed_at="2026-08-08T00:00:00Z",
             lifecycle_status="active", verification_status="direct_tool_output",
             sanitized_content={"text": "docker login fixed after token refresh"}),
        # Session memory
        _env("E-SESS1", event_type="decision", project_id=PROJECT, profile_id=PROFILE,
             session_id="S1", created_at="2026-08-09T00:00:00Z", observed_at="2026-08-09T00:00:00Z",
             lifecycle_status="active", verification_status="user_confirmation",
             sanitized_content={"text": "we decided earlier to use FTS5 first in the pipeline"}),
        # User preference
        _env("E-PREF", event_type="user_statement", project_id=None, profile_id=PROFILE,
             created_at="2026-08-02T00:00:00Z", observed_at="2026-08-02T00:00:00Z",
             lifecycle_status="active", verification_status="user_confirmation",
             sanitized_content={"text": "my preferred writing style is analytical and concise"}),
        # Research facts across knowledge spaces
        _env("E-QUANT", event_type="external_source", project_id="Q", profile_id=PROFILE,
             knowledge_space_id="quant-trading",
             created_at="2026-08-03T00:00:00Z", observed_at="2026-08-03T00:00:00Z",
             lifecycle_status="active", verification_status="direct_tool_output",
             sanitized_content={"text": "walk-forward validation splits data by time and avoids lookahead bias"}),
        _env("E-ENG", event_type="external_source", project_id="Q", profile_id=PROFILE,
             knowledge_space_id="engineering",
             created_at="2026-08-03T00:00:00Z", observed_at="2026-08-03T00:00:00Z",
             lifecycle_status="active", verification_status="direct_tool_output",
             sanitized_content={"text": "deployment policy uses canary releases and rollback runbooks"}),
        _env("E-WEB3", event_type="external_source", project_id="Q", profile_id=PROFILE,
             knowledge_space_id="web3",
             created_at="2026-08-04T00:00:00Z", observed_at="2026-08-04T00:00:00Z",
             lifecycle_status="active", verification_status="direct_tool_output",
             sanitized_content={"text": "web3 token analysis and gas fee models"}),
        # Conflict pair (same trace family -> visible in EvidenceSet conflict grouping)
        _env("E-FUND-A", event_type="external_source", project_id=PROJECT, profile_id=PROFILE,
             trace_id="tr-funding", created_at="2026-08-04T00:00:00Z", observed_at="2026-08-04T00:00:00Z",
             lifecycle_status="conflicted", verification_status="direct_tool_output",
             sanitized_content={"text": "funding value report A is two million"}),
        _env("E-FUND-B", event_type="external_source", project_id=PROJECT, profile_id=PROFILE,
             trace_id="tr-funding", created_at="2026-08-05T00:00:00Z", observed_at="2026-08-05T00:00:00Z",
             lifecycle_status="conflicted", verification_status="direct_tool_output",
             sanitized_content={"text": "funding value report B is five million"}),
        # Assistant claim that must NOT be promoted to primary evidence
        _env("E-CLAIM", event_type="assistant_claim", project_id=PROJECT, profile_id=PROFILE,
             created_at="2026-08-06T00:00:00Z", observed_at="2026-08-06T00:00:00Z",
             lifecycle_status="candidate", verification_status="none",
             sanitized_content={"text": "index build is complete according to the assistant"}),
    ]


def _m4_corpus() -> list[dict]:
    """M4 project-memory events for project P."""
    return [
        _m4("M4-C1", "charter", "C1", "create", name="Zero-Mem charter", goal="external memory", state="confirmed", lifecycle_status="active", version=1),
        _m4("M4-R1", "requirement", "R1", "create", statement="canonical store is JSONL", state="accepted", lifecycle_status="active", verification_status="deterministic_verification"),
        _m4("M4-D1", "decision", "D1", "create", scope=f"project:{PROJECT}", decision_key="storage", statement="pick JSONL plus derived sqlite", state="accepted", lifecycle_status="active", effective_at="2026-08-05T00:00:00Z"),
        _m4("M4-D2", "decision", "D2", "supersede", scope=f"project:{PROJECT}", decision_key="storage", statement="pick FTS5 lexical before dense", state="accepted", lifecycle_status="active", supersedes_id="D1", effective_at="2026-08-09T00:00:00Z"),
        _m4("M4-D3", "decision", "D3", "create", scope=f"project:{PROJECT}", decision_key="budget", statement="primary five supporting three tokens six thousand", state="accepted", lifecycle_status="active", effective_at="2026-08-06T00:00:00Z"),
        _m4("M4-D4", "decision", "D4", "create", scope=f"project:{PROJECT}", decision_key="obsidian", statement="obsidian role is curated projection", state="accepted", lifecycle_status="active", effective_at="2026-08-07T00:00:00Z"),
        _m4("M4-D5", "decision", "D5", "create", scope=f"project:{PROJECT}", decision_key="llm", statement="memory operation llm calls are zero", state="accepted", lifecycle_status="active", effective_at="2026-08-08T00:00:00Z"),
        _m4("M4-S1", "state", "S1", "create", state_key="step", state_value="M10.7 final acceptance", lifecycle_status="active", effective_at="2026-08-10T00:00:00Z"),
        _m4("M4-S2", "state", "S2", "create", state_key="docker_login", state_value="failed", lifecycle_status="superseded", effective_at="2026-08-01T00:00:00Z"),
        _m4("M4-S3", "state", "S2", "update", state_key="docker_login", state_value="fixed", lifecycle_status="active", effective_at="2026-08-08T00:00:00Z"),
        _m4("M4-V1", "verification", "V1", "create", subject_type="requirement", subject_id="R1", method="pytest", verification_status="deterministic_verification"),
        _m4("M4-A1", "artifact", "ART1", "create", artifact_type="report", version="1", safe_reference="artifacts/report.md", linked_requirement_ids="R1", linked_decision_ids="D1", linked_state_keys="step"),
    ]


def _seed_m2_artifacts(store: SQLiteStore) -> None:
    store._conn.execute(
        "INSERT INTO zm_artifacts(artifact_id, content_hash, kind, retention, origin_event_id, stored_path, created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        ("ART1", "deadbeef", "report", "project", "M4-A1", "artifacts/report.md", "2026-08-07T00:00:00Z"),
    )
    store._conn.commit()


# ---------------------------------------------------------------------------
# Gold query table
# ---------------------------------------------------------------------------

class GoldQuery:
    __slots__ = ("id", "text", "plan_route", "contract_route", "gold_ids", "explicit",
                 "session_id", "ks", "assert_no", "not_primary", "conflict_expected", "note")

    def __init__(self, qid, text, plan_route, gold_ids=(), explicit=None, session_id=None,
                 ks=(), assert_no=(), not_primary=(), conflict_expected=False,
                 contract_route=None, note=None):
        self.id = qid
        self.text = text
        self.plan_route = plan_route
        self.contract_route = contract_route or plan_route
        self.gold_ids = tuple(gold_ids)
        self.explicit = explicit or {}
        self.session_id = session_id
        self.ks = tuple(ks)
        self.assert_no = tuple(assert_no)
        self.not_primary = tuple(not_primary)
        self.conflict_expected = conflict_expected
        self.note = note


GOLD = [
    # --- task continuation / project state ---
    GoldQuery("B01", "What is the current project step?", MemoryRoute.PROJECT,
              gold_ids=("S1",), explicit={"project": True}, note="gold = M4 state step"),
    GoldQuery("B02", "What remains unverified?", MemoryRoute.PROJECT,
              gold_ids=(), explicit={"project": True}, note="non-promotion covered by C-CLAIM"),
    GoldQuery("B03", "Continue the current task after a new session", MemoryRoute.PROJECT,
              gold_ids=("S1",), explicit={"project": True}),
    GoldQuery("B04", "Which task is blocked?", MemoryRoute.PROJECT,
              gold_ids=(), explicit={"project": True}, note="no blocked task in corpus; route-only"),
    GoldQuery("B05", "What was the next action?", MemoryRoute.PROJECT,
              gold_ids=(), explicit={"project": True}, note="route-only"),
    # --- stale state ---
    GoldQuery("B06", "Is the old docker login failure still active?", MemoryRoute.PROJECT,
              gold_ids=("S3",), explicit={"project": True}, assert_no=("S2",),
              note="active superseding state must be present; superseded must be absent"),
    GoldQuery("B07", "What decision superseded the earlier choice?", MemoryRoute.PROJECT,
              gold_ids=("D2",), explicit={"project": True}),
    GoldQuery("B08", "What is the latest verified state?", MemoryRoute.PROJECT,
              gold_ids=("S1",), explicit={"project": True}, contract_route=MemoryRoute.EXTERNAL_CURRENT,
              note="freshness precedence routes 'latest' to EXTERNAL_CURRENT (fail-safe)"),
    GoldQuery("B09", "Which error was fixed?", MemoryRoute.PROJECT,
              gold_ids=("S3",), explicit={"project": True}, assert_no=("S2",)),
    GoldQuery("B10", "When did the state become valid?", MemoryRoute.PROJECT,
              gold_ids=("S1",), explicit={"project": True}),
    # --- exact facts ---
    GoldQuery("B21", "Which store is canonical?", MemoryRoute.PROJECT,
              gold_ids=("D2", "D1"), explicit={"project": True}),
    GoldQuery("B23", "How many primary evidence units are allowed?", MemoryRoute.PROJECT,
              gold_ids=("D3",), explicit={"project": True}),
    GoldQuery("B25", "Are memory-operation LLM calls allowed?", MemoryRoute.PROJECT,
              gold_ids=("D5",), explicit={"project": True}),
    # --- temporal ---
    GoldQuery("B28", "What was the latest decision about Obsidian?", MemoryRoute.PROJECT,
              gold_ids=("D4",), explicit={"project": True}, contract_route=MemoryRoute.EXTERNAL_CURRENT,
              note="freshness precedence routes 'latest' to EXTERNAL_CURRENT (fail-safe)"),
    GoldQuery("B29", "What was true before the superseding fix?", MemoryRoute.PROJECT,
              gold_ids=("S2",), explicit={"project": True},
              note="history/as-of read not wired into standard EvidenceSet; superseded expected absent"),
    GoldQuery("B30", "Which evidence was valid at the prior session time?", MemoryRoute.SESSION,
              gold_ids=("E-SESS1",), session_id="S1", explicit={"session": True}),
    # --- user preference ---
    GoldQuery("B22", "What is my preferred writing style?", MemoryRoute.USER,
              gold_ids=("E-PREF",), explicit={"user": True}),
    # --- research / profile isolation (plan wording: FTS-AND may return zero) ---
    GoldQuery("B11", "Only use Quant knowledge: what defines walk-forward validation?", MemoryRoute.RESEARCH,
              gold_ids=("E-QUANT",), ks=("quant-trading",), explicit={"research": True},
              assert_no=("E-WEB3", "E-ENG"), note="plan wording; FTS AND may miss -> C-QUANT measures with terms present"),
    GoldQuery("B12", "Only use Engineering knowledge: what is the deployment policy?", MemoryRoute.RESEARCH,
              gold_ids=("E-ENG",), ks=("engineering",), explicit={"research": True},
              assert_no=("E-WEB3", "E-QUANT"), note="plan wording; see C-QUANT"),
    GoldQuery("B13", "Isolated Quant search must not return Web3 evidence", MemoryRoute.RESEARCH,
              gold_ids=(), ks=("quant-trading",), explicit={"research": True}, assert_no=("E-WEB3",)),
    # --- conflict (plan wording: FTS-AND may return zero; C-FUND measures with terms present) ---
    GoldQuery("B16", "Two sources report different funding values", MemoryRoute.RESEARCH,
              gold_ids=("E-FUND-A", "E-FUND-B"), explicit={"research": True}, conflict_expected=True,
              note="plan wording; FTS AND may miss -> C-FUND measures conflict with terms present"),
    GoldQuery("B18", "Return both sources without silent overwrite", MemoryRoute.RESEARCH,
              gold_ids=("E-FUND-A", "E-FUND-B"), explicit={"research": True}, conflict_expected=True,
              note="plan wording; see C-FUND"),
    # --- dedicated term-present retrieval probes ---
    GoldQuery("C-QUANT", "walk forward validation", MemoryRoute.RESEARCH,
              gold_ids=("E-QUANT",), ks=("quant-trading",), explicit={"research": True},
              assert_no=("E-WEB3", "E-ENG"),
              note="well-formed FTS expression (no hyphen); hyphenated wording is a documented failure"),
    GoldQuery("C-FUND", "funding value", MemoryRoute.RESEARCH,
              gold_ids=("E-FUND-A", "E-FUND-B"), explicit={"research": True}, conflict_expected=True,
              note="terms present in both conflicted docs"),
    GoldQuery("C-CLAIM", "index build complete", MemoryRoute.RESEARCH,
              gold_ids=("E-CLAIM",), explicit={"research": True}, not_primary=("E-CLAIM",),
              note="assistant_claim retrievable but never PRIMARY"),
    # --- multi-hop ---
    GoldQuery("B26", "Which decision led to the current project structure?", MemoryRoute.PROJECT,
              gold_ids=("D2", "D1"), explicit={"project": True}),
    GoldQuery("B27", "Connect the task, artifact, and verification evidence", MemoryRoute.PROJECT,
              gold_ids=("ART1", "V1", "R1"), explicit={"project": True}),
    # --- no memory / external current controls ---
    GoldQuery("B99-NO", "Explain what BM25 is", MemoryRoute.NO_MEMORY,
              gold_ids=(), explicit={}),
    GoldQuery("B99-FRESH", "What is the latest version of the library?", MemoryRoute.EXTERNAL_CURRENT,
              gold_ids=(), explicit={"freshness": True}),
]


def _explicit_flags(explicit: dict) -> dict:
    return {
        "explicit_project_intent": explicit.get("project", False),
        "explicit_session_intent": explicit.get("session", False),
        "explicit_research_intent": explicit.get("research", False),
        "explicit_user_intent": explicit.get("user", False),
        "explicit_global_intent": explicit.get("global", False),
        "explicit_freshness_intent": explicit.get("freshness", False),
    }


# ---------------------------------------------------------------------------
# Store construction (real pipeline)
# ---------------------------------------------------------------------------

def build_store(root: Path):
    store = SQLiteStore(SQLiteStoreConfig(path=root / "m.sqlite"))
    store.ensure_schema()
    _seed_m2_artifacts(store)

    jl = root / "memory.jsonl"
    events = _memory_events()
    jl.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    ingest_file(store, jl)

    corpus = root / "m4-corpus.jsonl"
    corpus.write_text("\n".join(json.dumps(e) for e in _m4_corpus()) + "\n")
    rebuild_project_memory(store, corpus, project_id=PROJECT)
    rebuild_all_project_memory(store, corpus, project_id=PROJECT)

    store._conn.commit()
    store.close()
    ro = open_readonly(root / "m.sqlite")
    return ro, events


def _full_history_tokens(events: list[dict]) -> int:
    """'No memory system' baseline: every event's sanitized content sent every turn."""
    total = 0
    for e in events:
        content = e.get("sanitized_content")
        if isinstance(content, dict):
            text = " ".join(str(v) for v in content.values())
        else:
            text = str(content or "")
        total += estimate_tokens(text)
    return total


def _evidence_ids(es) -> list[str]:
    return [e.evidence_id for e in es.primary_evidence] + [e.evidence_id for e in es.supporting_evidence]


def _request_for(g: GoldQuery, *, profile: str = PROFILE) -> RouterRequest:
    return RouterRequest(
        normalized_text=g.text,
        project_id=PROJECT if g.plan_route is MemoryRoute.PROJECT else None,
        session_id=g.session_id,
        requesting_profile_id=profile,
        target_profile_ids=(profile,),
        knowledge_space_ids=g.ks,
        **_explicit_flags(g.explicit),
    )


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _run_query_set(svc, events: list[dict]) -> dict:
    full_tokens = _full_history_tokens(events)
    rows = []
    latencies = []
    for g in GOLD:
        req = _request_for(g)
        dec = route(req)
        start = time.perf_counter()
        es = build_evidence_set(dec, svc, req)
        latencies.append((time.perf_counter() - start) * 1000.0)

        ids = _evidence_ids(es)
        primary_ids = {e.evidence_id for e in es.primary_evidence}
        all_ids = set(ids)

        gold_hit8 = [gid for gid in g.gold_ids if gid in all_ids]
        gold_hit5 = [gid for gid in g.gold_ids if gid in primary_ids]
        recall8 = len(gold_hit8) / len(g.gold_ids) if g.gold_ids else 1.0
        recall5 = len(gold_hit5) / len(g.gold_ids) if g.gold_ids else 1.0

        mrr = 0.0
        if g.gold_ids:
            for rank, eid in enumerate(ids, start=1):
                if eid in g.gold_ids:
                    mrr = 1.0 / rank
                    break

        leaked = [nid for nid in g.assert_no if nid in all_ids]
        stale_safe = not leaked
        active_recall = recall8 if g.assert_no else None
        promoted = [nid for nid in g.not_primary if nid in primary_ids]
        not_primary_ok = not promoted
        conflict_ok = (len(es.conflicts) > 0) if g.conflict_expected else None

        rows.append({
            "id": g.id, "text": g.text,
            "plan_route": g.plan_route.value, "contract_route": g.contract_route.value,
            "actual_route": dec.route.value,
            "plan_route_ok": dec.route is g.plan_route,
            "contract_route_ok": dec.route is g.contract_route,
            "gold_ids": list(g.gold_ids), "recall@5": round(recall5, 3), "recall@8": round(recall8, 3),
            "mrr": round(mrr, 3),
            "stale_safe": stale_safe, "leaked": leaked, "active_recall": active_recall,
            "not_primary_ok": not_primary_ok, "promoted": promoted,
            "conflict_ok": conflict_ok,
            "evidence_ids": ids,
            "estimated_tokens": es.estimated_tokens,
            "omitted_count": es.omitted_count,
            "reason_code": es.reason_code,
            "latency_ms": round(latencies[-1], 3),
        })

    def _mean(key, pred=None):
        vals = [r[key] for r in rows if (pred(r) if pred else r[key] is not None)]
        return round(statistics.mean(vals), 4) if vals else None

    plan_acc = sum(r["plan_route_ok"] for r in rows) / len(rows)
    contract_acc = sum(r["contract_route_ok"] for r in rows) / len(rows)
    stale_rows = [r for r in rows if r["active_recall"] is not None]
    stale_safe_rate = (sum(r["stale_safe"] for r in stale_rows) / len(stale_rows)) if stale_rows else None
    active_recall_on_stale = _mean("active_recall", lambda r: r["active_recall"] is not None)
    conflict_rows = [r for r in rows if r["conflict_ok"] is not None]
    conflict_visible = _mean("conflict_ok", lambda r: r["conflict_ok"] is not None)
    ev_tokens = [r["estimated_tokens"] for r in rows]
    lat = sorted(latencies)
    p50 = statistics.median(lat)
    p95 = lat[min(len(lat) - 1, int(0.95 * len(lat)))]

    return {
        "benchmark_version": BENCHMARK_VERSION,
        "queries": len(rows),
        "full_history_tokens": full_tokens,
        "avg_evidence_tokens": round(statistics.mean(ev_tokens), 1),
        "token_savings_ratio": round(statistics.mean(ev_tokens) / full_tokens, 4) if full_tokens else None,
        "plan_route_accuracy": round(plan_acc, 4),
        "contract_route_accuracy": round(contract_acc, 4),
        "mean_recall@5": _mean("recall@5", lambda r: r["gold_ids"]),
        "mean_recall@8": _mean("recall@8", lambda r: r["gold_ids"]),
        "mean_mrr": _mean("mrr", lambda r: r["gold_ids"]),
        "stale_safe_rate": round(stale_safe_rate, 4) if stale_safe_rate is not None else None,
        "active_recall_on_stale": active_recall_on_stale,
        "conflict_visible_rate": conflict_visible,
        "not_primary_rate": _mean("not_primary_ok"),
        "latency_p50_ms": round(p50, 3),
        "latency_p95_ms": round(p95, 3),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=str, default=None, help="run root (default: tempfile)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else Path(tempfile.mkdtemp(prefix="zm-bench-")).resolve()
    root.mkdir(parents=True, exist_ok=True)

    store, events = build_store(root)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id=PROFILE)
        first = _run_query_set(svc, events)
        second = _run_query_set(svc, events)
        det = [a["evidence_ids"] == b["evidence_ids"] for a, b in zip(first["rows"], second["rows"])]
        first["deterministic_repeat"] = bool(det) and all(det)

        # Isolation probe: a FOREIGN profile carries its OWN identity in the
        # RouterRequest (identity comes from the typed caller contract, not the
        # read-service instance). Profile-OWNED records of pr1 must not leak.
        # NULL-profile (unowned) records ARE globally readable by design (M5.2:
        # global read = requester profile + NULL-profile default records only).
        OWNED_M4 = {"C1", "R1", "D1", "D2", "D3", "D4", "D5", "S1", "S2", "S3"}
        foreign_req = _request_for(GOLD[0], profile="foreign")
        dec_f = route(foreign_req)
        es_f = build_evidence_set(dec_f, AuthorizedReadService(store, requesting_profile_id="foreign"), foreign_req)
        first["foreign_profile_evidence_ids"] = _evidence_ids(es_f)
        first["foreign_owned_leak"] = sorted(set(_evidence_ids(es_f)) & OWNED_M4)
        first["isolation_ok"] = len(first["foreign_owned_leak"]) == 0
    finally:
        store.close()

    if args.json:
        print(json.dumps(first, indent=2, sort_keys=True))
    else:
        s = first
        print(f"Benchmark {s['benchmark_version']} — synthetic memory store, {s['queries']} gold queries")
        print(f"  plan_route_accuracy    = {s['plan_route_accuracy']:.3f}  (benchmark-plan labels)")
        print(f"  contract_route_accuracy= {s['contract_route_accuracy']:.3f}  (router documented precedence)")
        print(f"  mean recall@5          = {s['mean_recall@5']}")
        print(f"  mean recall@8          = {s['mean_recall@8']}")
        print(f"  mean mrr               = {s['mean_mrr']}")
        print(f"  stale_safe_rate        = {s['stale_safe_rate']:.3f}  (superseded never surfaced)")
        print(f"  active_recall_on_stale = {s['active_recall_on_stale']}")
        print(f"  conflict_visible_rate  = {s['conflict_visible_rate']}  (when retrieval succeeds)")
        print(f"  not_primary_rate       = {s['not_primary_rate']}  (assistant claim never primary)")
        print(f"  isolation_ok           = {s['isolation_ok']} (foreign ids: {s['foreign_profile_evidence_ids']})")
        print(f"  latency p50/p95        = {s['latency_p50_ms']}ms / {s['latency_p95_ms']}ms")
        print(f"  full_history_tokens    = {s['full_history_tokens']}")
        print(f"  avg_evidence_tokens    = {s['avg_evidence_tokens']}  (ratio {s['token_savings_ratio']})")
        print(f"  deterministic_repeat   = {s['deterministic_repeat']}")
        print()
        hdr = f"{'id':<10} {'plan':>6} {'cont':>6} {'r@5':>6} {'r@8':>6} {'mrr':>6} {'stale':>6} {'conf':>6} {'np':>4} {'tok':>6} {'ms':>7}"
        print(hdr)
        for r in s["rows"]:
            print(f"{r['id']:<10} {str(r['plan_route_ok']):>6} {str(r['contract_route_ok']):>6} "
                  f"{r['recall@5']:>6} {r['recall@8']:>6} {r['mrr']:>6} {str(r['stale_safe']):>6} "
                  f"{('' if r['conflict_ok'] is None else str(r['conflict_ok'])):>6} {str(r['not_primary_ok']):>4} "
                  f"{r['estimated_tokens']:>6} {r['latency_ms']:>7}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
