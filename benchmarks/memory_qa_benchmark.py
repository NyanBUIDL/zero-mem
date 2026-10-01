#!/usr/bin/env python3
"""Offline retrieval benchmark for LongMemEval- and LoCoMo-format datasets.

Each haystack gets a fresh private ``Memory`` (temp data root, one profile) filled through the real write path
(validate -> authorize -> secret pre-scan -> register -> project) and queried through the real authorized read
path (``Memory.recall``); we report recall@k / hit@k against gold evidence. Zero LLM calls.

  python benchmarks/memory_qa_benchmark.py longmemeval data.json -k 5 10
  python benchmarks/memory_qa_benchmark.py locomo locomo10.json -k 5 10

LongMemEval: gold = answer_session_ids (session-level). One memory per turn, tagged with its session id.
LoCoMo: gold = qa[].evidence dia_ids (turn-level). One memory per dialogue turn.

Turns with identical text are one memory (content-hash identity) tagged with the FIRST id that carried it; hits are
collapsed to distinct memories in rank order before cutting at k.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from zero_mem.memory import Memory  # noqa: E402

PROFILE = "bench"


def _open_store(tmp: str) -> Memory:
    return Memory.open(PROFILE, data_root=Path(tmp) / "zm", channel="benchmark")


def longmemeval_items(data: list[dict]):
    for q in data:
        chunks = []
        for sid, sess in zip(q["haystack_session_ids"], q["haystack_sessions"]):
            for turn in sess:
                chunks.append((f"{turn['role']}: {turn['content']}", sid))
        yield q["question"], chunks, set(q["answer_session_ids"]), q.get("question_type", "all")


def locomo_items(data: list[dict]):
    for conv in data:
        c = conv["conversation"]
        chunks = []
        for key, sess in c.items():
            if key.startswith("session_") and isinstance(sess, list):
                for turn in sess:
                    chunks.append((f"{turn['speaker']}: {turn['text']}", turn["dia_id"]))
        for qa in conv["qa"]:
            if qa.get("evidence"):
                yield qa["question"], chunks, set(qa["evidence"]), f"cat{qa.get('category', 'all')}"


def _build(tmp: str, chunks) -> tuple[Memory, dict[str, str]]:
    """Fill a fresh store; returns it with the ``external_ref -> gold id`` tag map (first id wins)."""
    memory = _open_store(tmp)
    tag: dict[str, str] = {}
    for text, src in chunks:
        res = memory.add(text, "fact")
        if res.external_ref:  # secret-looking turns are rejected by design and simply not retrievable
            tag.setdefault(res.external_ref, src)
    return memory, tag


def _ranked_sources(memory: Memory, tag: dict[str, str], question: str, kmax: int) -> list[str]:
    """Gold ids of the distinct memories hit, best first (several units of one turn count once)."""
    result = memory.recall(question, limit=min(200, max(kmax * 4, 20)))
    seen: set[str] = set()
    out: list[str] = []
    for hit in result.hits:
        if hit.external_ref in seen:
            continue
        seen.add(hit.external_ref)
        out.append(tag.get(hit.external_ref, hit.external_ref))
    return out


def run(items, ks: list[int]) -> dict:
    kmax = max(ks)
    totals = {k: 0.0 for k in ks}  # recall sums
    hits = {k: 0 for k in ks}
    n = 0
    by_type: dict[str, list[int]] = {}
    last_key = None
    store = tmp = None
    tag: dict[str, str] = {}
    for question, chunks, gold, qtype in items:
        key = id(chunks)
        if key != last_key:  # LoCoMo reuses the same haystack across questions
            if store is not None:
                store.close()
            if tmp is not None:
                tmp.cleanup()
            tmp = tempfile.TemporaryDirectory(prefix="zm-bench-")
            store, tag = _build(tmp.name, chunks)
            last_key = key
        ranked = _ranked_sources(store, tag, question, kmax)
        n += 1
        for k in ks:
            found = len(set(ranked[:k]) & gold)
            totals[k] += found / len(gold)
            hits[k] += 1 if found else 0
        by_type.setdefault(qtype, [0, 0])
        by_type[qtype][0] += 1
        by_type[qtype][1] += 1 if set(ranked[: ks[0]]) & gold else 0
    if store is not None:
        store.close()
    if tmp is not None:
        tmp.cleanup()
    return {
        "questions": n,
        **{f"recall@{k}": round(totals[k] / n, 4) if n else 0.0 for k in ks},
        **{f"hit@{k}": round(hits[k] / n, 4) if n else 0.0 for k in ks},
        f"hit@{ks[0]}_by_type": {t: round(v[1] / v[0], 4) for t, v in sorted(by_type.items())},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dataset", choices=["longmemeval", "locomo"])
    ap.add_argument("path")
    ap.add_argument("-k", type=int, nargs="+", default=[5, 10])
    ap.add_argument("--limit", type=int, help="only the first N questions/conversations")
    args = ap.parse_args(argv)
    data = json.loads(Path(args.path).read_text(encoding="utf-8"))
    if args.limit:
        data = data[: args.limit]
    items = longmemeval_items(data) if args.dataset == "longmemeval" else locomo_items(data)
    print(json.dumps(run(items, args.k), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
