#!/usr/bin/env python3
"""Reproducible SQLite point-lookup benchmark for the v1.6 Multi-KS junction."""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import tempfile
import time
from pathlib import Path


def benchmark(size: int, repeats: int) -> dict[str, float | int | str]:
    with tempfile.TemporaryDirectory(prefix="zero-mem-v160-bench-") as temporary:
        db_path = Path(temporary) / "junction.sqlite"
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE zm_event_spaces ("
            "event_id TEXT NOT NULL, knowledge_space_id TEXT NOT NULL, "
            "PRIMARY KEY (event_id, knowledge_space_id))"
        )
        rows = [
            (f"event-{index:09d}", space)
            for index in range(size)
            for space in (f"ks-{index % 101:03d}", f"ks-{(index + 17) % 101:03d}")
        ]
        conn.executemany(
            "INSERT INTO zm_event_spaces(event_id, knowledge_space_id) VALUES (?, ?)",
            rows,
        )
        conn.commit()
        query = (
            "SELECT 1 FROM zm_event_spaces "
            "WHERE event_id = ? AND knowledge_space_id = ? LIMIT 1"
        )
        plan = conn.execute(
            "EXPLAIN QUERY PLAN " + query,
            ("event-000000000", "ks-000"),
        ).fetchone()[3]
        samples: list[float] = []
        for index in range(repeats):
            event_index = (index * 7919) % size
            params = (f"event-{event_index:09d}", f"ks-{event_index % 101:03d}")
            started = time.perf_counter_ns()
            assert conn.execute(query, params).fetchone() == (1,)
            samples.append((time.perf_counter_ns() - started) / 1_000)
        conn.close()
        return {
            "events": size,
            "junction_rows": len(rows),
            "repeats": repeats,
            "median_us": round(statistics.median(samples), 3),
            "p95_us": round(sorted(samples)[int(len(samples) * 0.95) - 1], 3),
            "db_bytes": db_path.stat().st_size,
            "query_plan": plan,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=[1_000, 10_000, 100_000])
    parser.add_argument("--repeats", type=int, default=1_000)
    args = parser.parse_args()
    if args.repeats < 20 or any(size < 1 for size in args.sizes):
        parser.error("sizes must be positive and repeats must be at least 20")
    print(json.dumps({
        "benchmark": "v160-junction-point-lookup",
        "results": [benchmark(size, args.repeats) for size in args.sizes],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
