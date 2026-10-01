#!/usr/bin/env python3
"""Offline retrieval benchmark for LongMemEval- and LoCoMo-format datasets, over the REAL memory pipeline.

Each haystack gets a fresh private ``Memory`` (temp data root, one pinned profile) filled through the real write path
(validate -> authorize -> secret pre-scan -> register -> project) and is queried through the real authorized read
path (``Memory.recall``). Nothing here touches the index directly. Zero LLM calls, deterministic.

  python benchmarks/memory_qa_benchmark.py locomo locomo10.json -k 1 5 10
  python benchmarks/memory_qa_benchmark.py locomo locomo10.json --level session -k 1 5 10
  python benchmarks/memory_qa_benchmark.py longmemeval longmemeval_s_cleaned.json -k 5 10 --limit 50 --seed 7
  python benchmarks/memory_qa_benchmark.py locomo locomo10.json --check-determinism --json out.json

Datasets and gold:
  LongMemEval: gold = ``answer_session_ids`` (session level; ranked items are distinct sessions).
  LoCoMo: gold = ``qa[].evidence`` dia ids (``--level turn``, the default) or the sessions of those turns
          (``--level session``; ``Dn:m`` -> ``session_n``).

Ingest modes (what one memory is): ``--ingest turn`` stores one memory per dialogue turn; ``--ingest session`` stores one
memory per session (one blank-line separated paragraph, hence one unit, per turn). The default is ``turn`` for turn-level
gold and ``session`` for session-level gold. Turns with identical text are one memory (content-hash identity) tagged with
the FIRST id that carried it; hits are collapsed to distinct gold ids in rank order before cutting at k.

Reported: hit@k, recall@k, MRR (over the retrieved list, at most --recall-limit units), the same by question type,
per-query ``Memory.recall`` latency (p50/p95/mean/max, ms), ingest throughput (adds/s through the write path) and a
``fingerprint`` of every ranking, so two runs can be compared byte for byte. ``--check-determinism`` re-queries every
question a second time and exits with status 3 when any ranking differs. ``--seed`` makes ``--limit N`` draw a stable
random sample instead of the first N. ``--cache-dir`` keeps the filled stores between runs (ranking experiments only:
delete it after touching the write/projection path; ingest throughput is then not measured).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from zero_mem.memory import Memory  # noqa: E402

PROFILE = "bench"
MAX_RECALL_LIMIT = 200
_DIA_RE = re.compile(r"D(\d+):(\d+)")
LEVELS = ("turn", "session")
INGEST_MODES = ("turn", "session")


# ----------------------------------------------------------------------------- datasets
def longmemeval_items(data: list[dict], level: str = "session"):
    """``(question, chunks, gold, type)`` per question; chunks are ``(text, tag, group)`` with tag = group = session id."""
    for q in data:
        chunks = []
        for sid, sess in zip(q["haystack_session_ids"], q["haystack_sessions"]):
            for turn in sess:
                chunks.append((f"{turn['role']}: {turn['content']}", sid, sid))
        yield q["question"], chunks, set(q["answer_session_ids"]), q.get("question_type", "all")


def locomo_items(data: list[dict], level: str = "turn"):
    """LoCoMo QA; ``level="turn"`` gold = dia ids, ``level="session"`` gold = the sessions holding those turns."""
    for conv in data:
        c = conv["conversation"]
        chunks = []
        for key, sess in c.items():
            if key.startswith("session_") and isinstance(sess, list):
                for turn in sess:
                    tag = turn["dia_id"] if level == "turn" else key
                    chunks.append((f"{turn['speaker']}: {turn['text']}", tag, key))
        for qa in conv["qa"]:
            if not qa.get("evidence"):
                continue
            if level == "turn":
                gold = set(qa["evidence"])
            else:
                gold = {f"session_{m.group(1)}" for ev in qa["evidence"] for m in _DIA_RE.finditer(str(ev))}
                if not gold:
                    continue
            yield qa["question"], chunks, gold, f"cat{qa.get('category', 'all')}"


def select(data: list, limit: Optional[int], seed: Optional[int]) -> list:
    """First ``limit`` entries, or (with a seed) a stable random sample of ``limit`` entries in original order."""
    if not limit or limit >= len(data):
        return list(data)
    if seed is None:
        return list(data[:limit])
    picked = sorted(random.Random(seed).sample(range(len(data)), limit))
    return [data[i] for i in picked]


# ----------------------------------------------------------------------------- metrics
def score_ranking(ranked: list[str], gold: set[str], ks: list[int]) -> dict:
    """hit@k, recall@k and the reciprocal rank of the first gold item for ONE ranked list of distinct ids."""
    first = next((i for i, tag in enumerate(ranked, 1) if tag in gold), None)
    out: dict[str, float] = {"mrr": 1.0 / first if first else 0.0}
    for k in ks:
        found = len(set(ranked[:k]) & gold)
        out[f"hit@{k}"] = 1.0 if found else 0.0
        out[f"recall@{k}"] = found / len(gold)
    return out


def percentile(values: Iterable[float], p: float) -> float:
    """Nearest-rank percentile (deterministic, no interpolation); 0.0 for an empty list."""
    ordered = sorted(values)
    if not ordered:
        return 0.0
    rank = max(1, math.ceil(p / 100.0 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


class _Totals:
    def __init__(self, ks: list[int]) -> None:
        self.ks = ks
        self.n = 0
        self.sums: dict[str, float] = {}

    def add(self, scores: dict) -> None:
        self.n += 1
        for key, value in scores.items():
            self.sums[key] = self.sums.get(key, 0.0) + value

    def mean(self, key: str) -> float:
        return round(self.sums.get(key, 0.0) / self.n, 4) if self.n else 0.0

    def report(self) -> dict:
        out: dict[str, Any] = {"questions": self.n}
        for k in self.ks:
            out[f"hit@{k}"] = self.mean(f"hit@{k}")
            out[f"recall@{k}"] = self.mean(f"recall@{k}")
        out["mrr"] = self.mean("mrr")
        return out


# ----------------------------------------------------------------------------- engine (the real pipeline)
class MemoryEngine:
    """One pinned-profile ``Memory`` in its own data root: ``add`` = write path, ``search`` = authorized recall."""

    def __init__(self, root: Path) -> None:
        self.memory = Memory.open(PROFILE, data_root=Path(root) / "zm", channel="benchmark")

    def add(self, text: str, name: Optional[str] = None):
        return self.memory.add(text, "fact", name=name)

    def search(self, question: str, limit: int) -> list[tuple[str, str]]:
        result = self.memory.recall(question, limit=limit)
        return [(hit.external_ref or "", hit.text) for hit in result.hits]

    def close(self) -> None:
        self.memory.close()


def _norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


class _Haystack:
    """A filled store plus the maps that turn a recalled unit back into a gold id."""

    def __init__(self, engine, ref_tag: dict, text_tag: dict, adds: int, rejected: int, seconds: float,
                 cached: bool) -> None:
        self.engine = engine
        self.ref_tag = ref_tag
        self.text_tag = text_tag
        self.adds = adds
        self.rejected = rejected
        self.seconds = seconds
        self.cached = cached

    def tag(self, ref: str, text: str) -> str:
        if ref in self.ref_tag:
            return self.ref_tag[ref]
        return self.text_tag.get(_norm(text), ref)

    def ranked(self, hits: list[tuple[str, str]]) -> list[str]:
        """Distinct gold ids of the hit memories, best first (several units of one memory count once)."""
        seen: set[str] = set()
        out: list[str] = []
        for ref, text in hits:
            tag = self.tag(ref, text)
            if tag not in seen:
                seen.add(tag)
                out.append(tag)
        return out

    def close(self) -> None:
        self.engine.close()


def _groups(chunks) -> list[tuple[str, list[tuple[str, str]]]]:
    """Chunks as ordered ``(group, [(text, tag)])``; a 2-tuple chunk is its own group."""
    order: dict[str, list[tuple[str, str]]] = {}
    for chunk in chunks:
        text, tag, *rest = chunk
        order.setdefault(rest[0] if rest else tag, []).append((text, tag))
    return list(order.items())


def _fill(engine, chunks, ingest: str) -> tuple[dict, dict, int, int, float]:
    ref_tag: dict[str, str] = {}
    text_tag: dict[str, str] = {}
    adds = rejected = 0
    started = time.perf_counter()
    if ingest == "turn":
        for chunk in chunks:
            text, tag = chunk[0], chunk[1]
            res = engine.add(text)
            adds += 1
            if res.ok and res.external_ref:  # secret-looking turns are rejected by design: simply not retrievable
                ref_tag.setdefault(res.external_ref, tag)
            else:
                rejected += 1
    else:
        for index, (_group, members) in enumerate(_groups(chunks)):
            res = engine.add("\n\n".join(text for text, _tag in members), name=f"g{index:05d}")
            adds += 1
            if res.ok and res.external_ref:
                tags = {tag for _text, tag in members}
                if len(tags) == 1:
                    ref_tag[res.external_ref] = next(iter(tags))
                else:  # turn-level gold inside a session memory: a hit resolves by its unit text
                    for text, tag in members:
                        text_tag.setdefault(_norm(text), tag)
                continue
            rejected += 1
            for text, tag in members:  # one credential must not hide a whole session: fall back to its turns
                single = engine.add(text)
                adds += 1
                if single.ok and single.external_ref:
                    ref_tag.setdefault(single.external_ref, tag)
                else:
                    rejected += 1
    seconds = time.perf_counter() - started
    return ref_tag, text_tag, adds, rejected, seconds


def _cache_key(chunks, ingest: str) -> str:
    digest = hashlib.sha256(f"{ingest}\x00{PROFILE}".encode())
    for chunk in chunks:
        text, tag, *rest = chunk
        digest.update(f"\x1f{text}\x1e{tag}\x1e{rest[0] if rest else tag}".encode("utf-8", "surrogatepass"))
    return digest.hexdigest()[:24]


def _open_haystack(chunks, ingest: str, engine_factory: Callable, cache_dir: Optional[Path]):
    """Returns ``(haystack, cleanup)``; the temp root (or, with a cache, nothing) is removed by ``cleanup``."""
    if cache_dir is None:
        tmp = tempfile.TemporaryDirectory(prefix="zm-bench-")
        engine = engine_factory(Path(tmp.name))
        ref_tag, text_tag, adds, rejected, seconds = _fill(engine, chunks, ingest)
        return _Haystack(engine, ref_tag, text_tag, adds, rejected, seconds, False), tmp.cleanup
    root = Path(cache_dir) / _cache_key(chunks, ingest)
    marker = root / "READY.json"
    if marker.exists():
        saved = json.loads(marker.read_text(encoding="utf-8"))
        engine = engine_factory(root)
        return _Haystack(engine, saved["ref_tag"], saved["text_tag"], 0, saved["rejected"], 0.0, True), lambda: None
    root.mkdir(parents=True, exist_ok=True)
    engine = engine_factory(root)
    ref_tag, text_tag, adds, rejected, seconds = _fill(engine, chunks, ingest)
    marker.write_text(json.dumps({"ref_tag": ref_tag, "text_tag": text_tag, "rejected": rejected}), encoding="utf-8")
    return _Haystack(engine, ref_tag, text_tag, adds, rejected, seconds, False), lambda: None


# ----------------------------------------------------------------------------- the run
def run(
    items,
    ks: list[int],
    *,
    ingest: str = "turn",
    recall_limit: Optional[int] = None,
    engine_factory: Optional[Callable] = None,
    cache_dir: Optional[Path] = None,
    check_determinism: bool = False,
) -> dict:
    """Evaluate ``(question, chunks, gold, type)`` items; consecutive items sharing one ``chunks`` list share one store."""
    if ingest not in INGEST_MODES:
        raise ValueError(f"ingest must be one of {INGEST_MODES}")
    ks = sorted(set(ks))
    factory = engine_factory or MemoryEngine
    limit = recall_limit or (min(MAX_RECALL_LIMIT, max(max(ks) * 4, 20)) if ingest == "turn" else MAX_RECALL_LIMIT)
    overall = _Totals(ks)
    by_type: dict[str, _Totals] = {}
    latencies: list[float] = []
    fingerprint = hashlib.sha256()
    det_checked = det_bad = 0
    adds = rejected = 0
    ingest_seconds = 0.0
    cached = False
    haystack: Optional[_Haystack] = None
    cleanup: Callable = lambda: None  # noqa: E731
    last_chunks = None

    def release() -> None:
        nonlocal haystack, cleanup
        if haystack is not None:
            haystack.close()
            cleanup()
        haystack = None

    try:
        for question, chunks, gold, qtype in items:
            if haystack is None or chunks is not last_chunks:
                release()  # LoCoMo reuses one haystack across its questions
                haystack, cleanup = _open_haystack(chunks, ingest, factory, cache_dir)
                last_chunks = chunks
                adds += haystack.adds
                rejected += haystack.rejected
                ingest_seconds += haystack.seconds
                cached = cached or haystack.cached
            started = time.perf_counter()
            hits = haystack.engine.search(question, limit)
            latencies.append((time.perf_counter() - started) * 1000.0)
            ranked = haystack.ranked(hits)
            fingerprint.update(("|".join(ranked) + "\n").encode("utf-8", "surrogatepass"))
            if check_determinism:
                det_checked += 1
                if haystack.engine.search(question, limit) != hits:
                    det_bad += 1
            scores = score_ranking(ranked, gold, ks)
            overall.add(scores)
            by_type.setdefault(qtype, _Totals(ks)).add(scores)
    finally:
        release()
    k0 = ks[0]
    report: dict[str, Any] = {
        **{key: value for key, value in overall.report().items()},
        f"hit@{k0}_by_type": {t: by_type[t].mean(f"hit@{k0}") for t in sorted(by_type)},
        "by_type": {t: by_type[t].report() for t in sorted(by_type)},
        "latency_ms": {
            "queries": len(latencies),
            "p50": round(percentile(latencies, 50), 3), "p95": round(percentile(latencies, 95), 3),
            "mean": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
            "max": round(max(latencies), 3) if latencies else 0.0,
        },
        "ingest": {
            "adds": adds, "rejected": rejected, "seconds": round(ingest_seconds, 3),
            "adds_per_second": round(adds / ingest_seconds, 1) if ingest_seconds > 0 else 0.0,
            "cached": cached,
        },
        "fingerprint": fingerprint.hexdigest()[:16],
        "config": {"ks": ks, "ingest": ingest, "recall_limit": limit, "engine": getattr(factory, "__name__", "engine"),
                   "profile": PROFILE},
    }
    if check_determinism:
        report["determinism"] = {"checked": det_checked, "mismatches": det_bad, "ok": det_bad == 0}
    return report


# ----------------------------------------------------------------------------- command line
def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dataset", choices=["longmemeval", "locomo"])
    ap.add_argument("path")
    ap.add_argument("-k", type=int, nargs="+", default=[5, 10])
    ap.add_argument("--limit", type=int, help="only N questions (longmemeval) / conversations (locomo)")
    ap.add_argument("--seed", type=int, help="with --limit: a stable random sample of N instead of the first N")
    ap.add_argument("--level", choices=LEVELS, help="gold granularity (default: turn for locomo, session for longmemeval)")
    ap.add_argument("--ingest", choices=INGEST_MODES, help="one memory per turn or per session (default: by level)")
    ap.add_argument("--recall-limit", type=int, help="units requested per query (default: by ingest mode)")
    ap.add_argument("--cache-dir", type=Path, help="keep filled stores here and reuse them (ranking experiments only)")
    ap.add_argument("--check-determinism", action="store_true",
                    help="query every question twice; exit 3 when any ranking differs")
    ap.add_argument("--json", type=Path, dest="json_out", help="also write the report to this file")
    args = ap.parse_args(argv)
    level = args.level or ("session" if args.dataset == "longmemeval" else "turn")
    ingest = args.ingest or ("session" if level == "session" else "turn")
    if args.recall_limit is not None and not 1 <= args.recall_limit <= MAX_RECALL_LIMIT:
        ap.error(f"--recall-limit must be 1..{MAX_RECALL_LIMIT}")
    data = select(json.loads(Path(args.path).read_text(encoding="utf-8")), args.limit, args.seed)
    items = longmemeval_items(data, level) if args.dataset == "longmemeval" else locomo_items(data, level)
    report = run(
        items, args.k, ingest=ingest, recall_limit=args.recall_limit or (MAX_RECALL_LIMIT if level == "session" else None),
        engine_factory=MemoryEngine, cache_dir=args.cache_dir, check_determinism=args.check_determinism)
    report["config"].update({
        "dataset": args.dataset, "path": Path(args.path).name, "level": level, "limit": args.limit,
        "seed": args.seed, "cache": args.cache_dir is not None})
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.json_out:
        args.json_out.write_text(text + "\n", encoding="utf-8")
    det = report.get("determinism")
    return 3 if det is not None and not det["ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
