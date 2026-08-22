"""WP-33 lexical retrieval benchmark over the real SQLite/FTS5 path.

This module is benchmark infrastructure only. It creates a deterministic synthetic
labeled corpus under an operator-provided run root, ingests it through the existing
canonical-to-derived ingest path, and queries through ``AuthorizedReadService``
which gates the existing read-only SQLite/FTS5 retrieval. No product retrieval
algorithm is reimplemented here.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from src.access import AccessRequest, AuthorizedReadService
from src.access.contracts import READ
from src.storage.ingest import ingest_file
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.retrieval.db import open_readonly

BENCHMARK_VERSION = "wp33-lexical-v1"
MAX_CORPUS_SIZE = 1_000_000
QUERY_LABELS = (
    ("deployment", "e0000000"),
    ("authorization", "e0000001"),
    ("projection", "e0000002"),
    ("recovery", "e0000003"),
)


def _event(event_id: str, text: str, sequence: int) -> dict[str, object]:
    return {
        "event_id": event_id,
        "trace_id": f"trace-{sequence:07d}",
        "event_type": "tool_observation",
        "source": "wp33_benchmark",
        "schema_version": 1,
        "created_at": f"2026-01-01T00:00:{sequence % 60:02d}Z",
        "observed_at": f"2026-01-01T00:00:{sequence % 60:02d}Z",
        "sequence": sequence,
        "lifecycle_status": "observed",
        "verification_status": "direct_tool_output",
        "confidence": "high",
        "profile_id": "wp33-profile",
        "project_id": "wp33-benchmark",
        "knowledge_space_id": "wp33-knowledge",
        "sensitivity": "internal",
        "retention": "persistent",
        "sanitized_content_hash": "sha256:" + hashlib.sha256(
            json.dumps({"text": text}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "sanitized_content": {"text": text},
        "redaction_audit": [],
    }


def _build_labeled_jsonl(path: Path, corpus_size: int) -> dict[str, set[str]]:
    labels: dict[str, set[str]] = {query: {event_id} for query, event_id in QUERY_LABELS}
    with path.open("w", encoding="utf-8") as handle:
        for index in range(corpus_size):
            event_id = f"e{index:07d}"
            matches = [query for query, relevant_id in QUERY_LABELS if relevant_id == event_id]
            text = (
                f"benchmark labeled {matches[0]} result"
                if matches
                else f"benchmark distractor document unit {index:07d}"
            )
            handle.write(json.dumps(_event(event_id, text, index), sort_keys=True) + "\n")
    return labels


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * percentile)))
    return round(ordered[index], 4)


def _reject_symlinked_components(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        if current.is_symlink():
            raise ValueError("run_root_symlink_component")


@contextmanager
def _secure_run_root(run_root: Path) -> Iterator[Path]:
    """Create and hold a new run root through directory descriptors.

    R124-07/R124-10: the descriptor-based path (``/proc/self/fd`` + dir_fd) is
    Linux-only. On Windows there is no ``O_DIRECTORY``/``dir_fd`` support at
    all; on macOS/BSD there is no ``/proc``. The parent is always rejected if
    it contains any symlink component (``_reject_symlinked_components``), so
    the real path is a safe fallback on those platforms.
    """
    parent = run_root.parent
    if not parent.exists():
        raise ValueError("run_root_parent_missing")
    _reject_symlinked_components(parent)
    if os.name == "nt":
        # Windows: no dir_fd support; parent components already proven
        # symlink-free above.
        try:
            run_root.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise ValueError("run_root_must_be_new") from exc
        yield run_root
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW
    try:
        parent_fd = os.open(parent, flags)
    except OSError as exc:
        raise ValueError("run_root_parent_open_failed") from exc
    root_fd: int | None = None
    try:
        try:
            os.mkdir(run_root.name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError as exc:
            raise ValueError("run_root_must_be_new") from exc
        root_fd = os.open(run_root.name, flags, dir_fd=parent_fd)
        if sys.platform == "linux":
            yield Path(f"/proc/self/fd/{root_fd}")
        else:
            # macOS/BSD: no /proc/self/fd; parent symlink components were
            # already rejected, so the real path is safe.
            yield run_root
    except FileNotFoundError as exc:
        raise ValueError("run_root_descriptor_unavailable") from exc
    finally:
        if root_fd is not None:
            os.close(root_fd)
        os.close(parent_fd)


def _run_benchmark_in_root(root: Path, *, corpus_size: int, repeats: int) -> dict[str, object]:
    jsonl_path = root / "corpus.jsonl"
    db_path = root / "derived.sqlite"
    labels = _build_labeled_jsonl(jsonl_path, corpus_size)

    store = SQLiteStore(SQLiteStoreConfig(path=db_path))
    try:
        store.ensure_schema()
        ingest_file(store, jsonl_path)
        conn = store._conn
        if conn is None:
            raise RuntimeError("benchmark_store_closed")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()
    finally:
        store.close()

    readonly = open_readonly(db_path)
    try:
        metrics: list[dict[str, object]] = []
        order_digest_parts: list[str] = []
        authorization_checks: list[bool] = []
        auth_request = AccessRequest(
            operation=READ,
            requesting_profile_id="wp33-profile",
            target_profile_ids=["wp33-profile"],
            project_ids=["wp33-benchmark"],
            include_global=False,
        )
        authorized_reader = AuthorizedReadService(readonly, "wp33-profile")
        for query, _ in QUERY_LABELS:
            samples: list[float] = []
            observed: list[str] = []
            for _ in range(repeats):
                start = time.perf_counter()
                result = authorized_reader.search_text(auth_request, query, limit=10)
                samples.append((time.perf_counter() - start) * 1000.0)
                authorization_checks.append(result.allowed and not result.denied)
                if result.error is not None or result.denied:
                    raise RuntimeError("lexical_benchmark_authorization_or_query_failed")
                observed = [hit.event_id for hit in result.items]
            relevant = labels[query]
            retrieved = set(observed)
            true_positive = len(retrieved & relevant)
            metrics.append({
                "query": query,
                "k": 10,
                "retrieved": len(observed),
                "relevant": len(relevant),
                "precision_at_k": round(true_positive / 10.0, 6),
                "recall_at_k": round(true_positive / len(relevant), 6) if relevant else 1.0,
                "latency_ms": {
                    "p50": _percentile(samples, 0.50),
                    "p95": _percentile(samples, 0.95),
                },
            })
            order_digest_parts.append(query + ":" + ",".join(observed))
    finally:
        readonly.close()

    return {
        "benchmark_version": BENCHMARK_VERSION,
        "corpus_size": corpus_size,
        "queries": len(QUERY_LABELS),
        "retrieval_version": "m3-fts5-readonly-v1",
        "authorization_before_candidate_discovery": bool(authorization_checks) and all(authorization_checks),
        "metrics": metrics,
        "retrieval_order_digest": hashlib.sha256("|".join(order_digest_parts).encode()).hexdigest(),
    }


def run_lexical_benchmark(run_root: Path, *, corpus_size: int, repeats: int = 3) -> dict[str, object]:
    """Run labeled lexical retrieval against a deterministic derived FTS store."""
    if not isinstance(run_root, Path):
        raise TypeError("run_root must be a pathlib.Path")
    if isinstance(corpus_size, bool) or not isinstance(corpus_size, int) or not (4 <= corpus_size <= MAX_CORPUS_SIZE):
        raise ValueError("corpus_size_out_of_range")
    if isinstance(repeats, bool) or not isinstance(repeats, int) or not (1 <= repeats <= 20):
        raise ValueError("repeats_out_of_range")
    if not run_root.is_absolute():
        raise ValueError("run_root_must_be_absolute")
    with _secure_run_root(run_root) as root:
        return _run_benchmark_in_root(root, corpus_size=corpus_size, repeats=repeats)


__all__ = ["BENCHMARK_VERSION", "run_lexical_benchmark"]
