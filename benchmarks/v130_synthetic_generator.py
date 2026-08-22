"""V130-05 — Deterministic synthetic memory-event corpus generator (seeded).

Generates N >= 5,000 canonical JSONL events engineered so each v1.3.0 fix has
dedicated measurable cases:

- OR-fallback (V130-01): rare-term multi-term queries (recall) vs common-term
  queries (precision guard — AND hits must NOT fall back).
- ks filter (V130-02): events spread across K knowledge spaces; cross-space
  leak must be zero; NULL-ks unscoped events visible unfiltered only.
- state promotion (V130-03): PROJECT-route active states competing with
  same-timestamp decisions.
- temporal annotation (V130-04): supersession chains for as-of before/after.

Determinism: every timestamp derives from the fixed SEED base; no wall-clock,
no random module without a seeded instance. Two runs are byte-identical.

Usage:
    .venv-v124/bin/python -m benchmarks.v130_synthetic_generator --n 5000 --out <dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SEED = "v130-synthetic-2026-08-22"
BASE_TS = 1755800000  # fixed epoch seconds (2026-08-21-ish); NEVER time.time()

KS_SPACES = [f"ks-{i}" for i in range(8)]
RARE_TOKENS = [f"zzqqx{i}" for i in range(200)]
COMMON_TERMS = ["quantum", "lattice", "deploy", "docker", "cache", "index", "report"]


def _ts(offset_seconds: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(BASE_TS + offset_seconds, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _env(event_id: str, text: str, *, ks=None, project="proj-bench", profile="prof-bench",
         seq=0, lifecycle="observed", verification="none", offset=0):
    return {
        "event_id": event_id,
        "trace_id": f"tr-{event_id}",
        "event_type": "tool_observation",
        "source": "pre_tool_call",
        "schema_version": 1,
        "created_at": _ts(offset),
        "observed_at": _ts(offset),
        "sequence": seq,
        "session_id": None,
        "profile_id": profile,
        "project_id": project,
        "task_id": None,
        "turn_id": None,
        "parent_trace_id": None,
        "lifecycle_status": lifecycle,
        "verification_status": verification,
        "confidence": "medium",
        "sensitivity": "internal",
        "retention": "persistent",
        "sanitized_content_hash": hashlib.sha256(text.encode()).hexdigest(),
        "sanitized_content": {"text": text},
        "redaction_audit": [],
        **({"knowledge_space_id": ks} if ks else {}),
    }


def generate(n: int = 5000):
    """Yield deterministic envelope dicts. Composition per 10-event block:
    2 ks-tagged common-term events (different spaces), 1 rare-term event,
    1 unscoped event, 1 supersession chain pair (every other block), plus fillers."""
    events = []
    i = 0
    while len(events) < n:
        block = len(events) // 10
        # OR-fallback recall case: rare term lives in its OWN doc (never with a
        # common term), so multi-term "common + rare" queries have AND=0 hits.
        events.append(_env(f"e-rare-{i}", f"{RARE_TOKENS[i % len(RARE_TOKENS)]} isolated doc", offset=i))
        # ks-filter cases: same text in different knowledge spaces.
        events.append(_env(f"e-ks-a-{i}", f"quantum shared note {i}", ks=KS_SPACES[i % len(KS_SPACES)], offset=i + 1))
        events.append(_env(f"e-ks-b-{i}", f"quantum private note {i}", ks=KS_SPACES[(i + 1) % len(KS_SPACES)], offset=i + 2))
        # NULL-ks unscoped case.
        events.append(_env(f"e-null-{i}", f"unscoped quantum note {i}", offset=i + 3))
        if block % 2 == 0 and i > 0:
            # Supersession chain pair (temporal as-of before/after). M4 state
            # domain events with explicit m4 supersession so the temporal index
            # carries a chain: old (superseded) vs new (active).
            sup_old = {
                "event_id": f"e-sup-old-{i}",
                "trace_id": f"tr-sup-old-{i}",
                "m4": {"domain": "state", "identity": f"SUP{i}", "op": "create",
                        "project_id": "proj-bench",
                        "state_key": f"sup-key-{block}", "state_value": "v1"},
            }
            old = _env(f"e-sup-old-{i}", f"step state version one {i}",
                       lifecycle="observed", offset=i + 4)
            old["m4"] = sup_old["m4"]
            events.append(old)
            new = _env(f"e-sup-new-{i}", f"step state version two {i}",
                       lifecycle="observed", verification="direct_tool_output",
                       offset=i + 5)
            new["m4"] = {"domain": "state", "identity": f"SUP{i}", "op": "update",
                          "project_id": "proj-bench",
                          "state_key": f"sup-key-{block}", "state_value": "v2",
                          "supersedes": f"e-sup-old-{i}"}
            events.append(new)
        else:
            # State-promotion competitors: active state + same-timestamp decisions.
            events.append(_env(f"e-state-{i}", f"current step is build phase {i}", lifecycle="active", offset=i + 4))
            events.append(_env(f"e-dec-{i}", f"decided to use docker compose {i}",
                               lifecycle="active",
                               verification="user_confirmation", offset=i + 4))
        i += 1
    return events[:n]


def write_corpus(out_dir: Path, n: int) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"synthetic-{n}.jsonl"
    lines = [json.dumps(e, sort_keys=True, separators=(",", ":")) for e in generate(n)]
    body = "\n".join(lines) + "\n"
    path.write_text(body)
    digest = hashlib.sha256(body.encode()).hexdigest()
    (out_dir / f"synthetic-{n}.sha256").write_text(digest + "\n")
    print(f"wrote {path} ({n} events) sha256={digest}")
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=5000)
    ap.add_argument("--out", type=str, required=True)
    args = ap.parse_args()
    write_corpus(Path(args.out), args.n)


if __name__ == "__main__":
    main()
