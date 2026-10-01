#!/usr/bin/env python3
"""Offline retrieval benchmark for LongMemEval- and LoCoMo-format datasets.

Each question gets a fresh in-memory-per-run NotesStore (temp dir) filled with
its haystack; we report recall@k / hit@k against gold evidence. Zero LLM calls.

  python benchmarks/memory_qa_benchmark.py longmemeval data.json -k 5 10
  python benchmarks/memory_qa_benchmark.py locomo locomo10.json -k 5 10

LongMemEval: gold = answer_session_ids (session-level). One chunk per turn,
  tagged with its session id.
LoCoMo: gold = qa[].evidence dia_ids (turn-level). One chunk per dialogue turn.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from zero_mem.notes import NotesStore  # noqa: E402


def _store(tmp: str) -> NotesStore:
    return NotesStore(Path(tmp) / "n.jsonl", Path(tmp) / "n.sqlite3")


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


def run(items, ks: list[int]) -> dict:
    kmax = max(ks)
    totals = {k: [0.0, 0] for k in ks}  # recall sum, hit sum
    hits = {k: 0 for k in ks}
    n = 0
    by_type: dict[str, list[int]] = {}
    last_key = None
    store = tmp = None
    for question, chunks, gold, qtype in items:
        key = id(chunks)
        if key != last_key:  # LoCoMo reuses the same haystack across questions
            if tmp is not None:
                tmp.cleanup()
            tmp = tempfile.TemporaryDirectory()
            store = _store(tmp.name)
            tag = {}
            for text, src in chunks:
                store.add_chunks([text], source=src)
                tag[store.chunk_id(text.strip())] = src
            last_key = key
        res = store.search(question, kmax)
        n += 1
        for k in ks:
            got = {h.source for h in res[:k]}
            found = len(got & gold)
            totals[k][0] += found / len(gold)
            hits[k] += 1 if found else 0
        by_type.setdefault(qtype, [0, 0])
        by_type[qtype][0] += 1
        by_type[qtype][1] += 1 if {h.source for h in res[: ks[0]]} & gold else 0
    if tmp is not None:
        tmp.cleanup()
    return {
        "questions": n,
        **{f"recall@{k}": round(totals[k][0] / n, 4) if n else 0.0 for k in ks},
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
