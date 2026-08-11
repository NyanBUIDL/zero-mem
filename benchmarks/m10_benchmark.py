"""M10.7 — large-corpus rollout + benchmark harness (deterministic, zero-LLM).

Runs the REAL M10.1-M10.6 product pipeline over an operator-supplied source
folder and records aggregate metrics. No product behaviour is bypassed,
re-implemented, or fast-pathed: every stage calls the same public facade the
product uses.

    runtime folder -> discovery -> M10.1 registry/auth identity
    -> M10.2 blob + extraction -> M10.3 normalize/dedup/version
    -> M10.4 derived projection -> M10.5 retrieval -> M10.6 graph
    -> M7 EvidenceSet

Operator input (NEVER product configuration, never committed):

    ZERO_MEM_M10_CORPUS_PATH   absolute path to the read-only source folder
    ZERO_MEM_M10_RUN_ROOT      optional; where Zero-Mem runtime state is written
                               (defaults to a fresh temp dir)

PORTABILITY INVARIANT (logical source != filesystem location)
-------------------------------------------------------------
The absolute operator path is used ONLY to read bytes. Every registered source
carries a RELOCATABLE logical ref:

    <source_label>/<path relative to the corpus root>

so the same corpus reconnected at another location on another machine keeps its
knowledge identity. The absolute path never enters identity, provenance, the
derived store, or any emitted evidence.

The source folder is treated as strictly READ-ONLY: opened 'rb' only, never
renamed, moved, chmod-ed, written to, or used as a Zero-Mem storage root.
"""
from __future__ import annotations

import json
import os
import resource
import shutil
import sqlite3
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.access import AccessRequest, AuthorizedReadService  # noqa: E402
from src.corpus.blob_store import CorpusBlobStore  # noqa: E402
from src.corpus.derived_store import (  # noqa: E402
    project_corpus,
    rebuild_from_corpus,
)
from src.corpus.extract import ExtractionStatus  # noqa: E402
from src.corpus.graph import (  # noqa: E402
    DEFAULT_GRAPH_BOUNDS,
    build_corpus_graph,
    build_corpus_graph_readonly,
)
from src.corpus.query_planner import build_query_plan  # noqa: E402
from src.corpus.registry import CorpusSourceRegistry  # noqa: E402
from src.corpus.retrieval import (  # noqa: E402
    AuthorizedCorpusScope,
    retrieve_corpus,
)
from src.retrieval.db import open_readonly  # noqa: E402
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig  # noqa: E402

# --- operator/runtime inputs (never product configuration) ------------------

CORPUS_PATH_ENV = "ZERO_MEM_M10_CORPUS_PATH"
RUN_ROOT_ENV = "ZERO_MEM_M10_RUN_ROOT"

#: Sanitized logical label for the rollout source. Evidence refers to THIS,
#: never to the operator's absolute machine path.
SOURCE_LABEL = "quantlab-papers"

#: Explicit owner-approved rollout authorization scope (M5 semantics).
#: Authorization is NEVER derived from the filesystem path, and the unowned
#: (None, None, None) scope is deliberately NOT used.
ROLLOUT_SCOPE: dict[str, str] = {
    "profile_id": "zero-mem",
    "project_id": "m10-corpus-rollout",
    "knowledge_space_id": "quant-papers",
}

#: Supported source extensions -> adapter kind hint.
SUPPORTED_KINDS = {".pdf": "pdf", ".txt": "txt"}


def corpus_path() -> Path:
    raw = os.environ.get(CORPUS_PATH_ENV)
    if not raw:
        raise SystemExit(f"{CORPUS_PATH_ENV} is not set (operator input required)")
    path = Path(raw).expanduser()
    if not path.is_dir():
        raise SystemExit(f"{CORPUS_PATH_ENV} is not a directory")
    return path.resolve()


def logical_ref(root: Path, file_path: Path) -> str:
    """Relocatable logical reference: label + path RELATIVE to the corpus root.

    Deliberately excludes the absolute path so relocating the library does not
    mint a new knowledge identity.
    """
    return f"{SOURCE_LABEL}/{file_path.relative_to(root).as_posix()}"


# --- discovery (read-only) --------------------------------------------------

@dataclass(frozen=True)
class DiscoveredFile:
    path: Path
    logical_ref: str
    kind: Optional[str]
    size: int


def discover(root: Path) -> tuple[list[DiscoveredFile], dict[str, Any]]:
    """Deterministic read-only inventory. Never opens files for parsing."""
    found: list[DiscoveredFile] = []
    stats = {
        "entries_scanned": 0,
        "regular_files": 0,
        "symlinks": 0,
        "unsupported": 0,
        "zero_byte": 0,
        "total_bytes": 0,
    }
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in sorted(dirnames):
            stats["entries_scanned"] += 1
            if (Path(dirpath) / name).is_symlink():
                stats["symlinks"] += 1
        for name in sorted(filenames):
            stats["entries_scanned"] += 1
            path = Path(dirpath) / name
            if path.is_symlink():
                stats["symlinks"] += 1
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            stats["regular_files"] += 1
            stats["total_bytes"] += size
            if size == 0:
                stats["zero_byte"] += 1
            kind = SUPPORTED_KINDS.get(path.suffix.lower())
            if kind is None:
                stats["unsupported"] += 1
                continue
            found.append(DiscoveredFile(path, logical_ref(root, path), kind, size))
    found.sort(key=lambda f: f.logical_ref)  # deterministic order
    return found, stats


# --- ingest ----------------------------------------------------------------

@dataclass
class IngestMetrics:
    discovered: int = 0
    registered: int = 0
    extract_complete: int = 0
    extract_partial: int = 0
    extract_image_only: int = 0
    extract_corrupt: int = 0
    extract_parser_unavailable: int = 0
    extract_other_failure: int = 0
    units_projected: int = 0
    units_rejected_secret: int = 0
    sources_projected: int = 0
    duplicate_content: int = 0
    distinct_source_ids: int = 0
    versions: int = 0
    elapsed_s: float = 0.0
    failures: list[tuple[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        out = {k: v for k, v in self.__dict__.items() if k != "failures"}
        out["failure_count"] = len(self.failures)
        return out


def classify_extraction(status: str) -> str:
    """Map the closed M10.2 ExtractionStatus onto rollout metric buckets."""
    return {
        ExtractionStatus.COMPLETE.value: "extract_complete",
        ExtractionStatus.PARTIAL.value: "extract_partial",
        # PDF with no extractable text = scanned/image-only (never invented text)
        ExtractionStatus.UNSUPPORTED_FORMAT.value: "extract_image_only",
        ExtractionStatus.CORRUPT_SOURCE.value: "extract_corrupt",
        ExtractionStatus.PARSER_UNAVAILABLE.value: "extract_parser_unavailable",
    }.get(status, "extract_other_failure")


def register_all(
    files: Iterable[DiscoveredFile],
    registry: CorpusSourceRegistry,
    blob: CorpusBlobStore,
) -> tuple[IngestMetrics, dict[str, int]]:
    """Register every discovered file under the explicit rollout scope.

    One malformed source must never abort the rollout: each file is guarded
    independently and failures are recorded with a deterministic class.
    """
    metrics = IngestMetrics()
    content_hashes: dict[str, int] = {}
    source_ids: set[str] = set()

    for item in files:
        metrics.discovered += 1
        try:
            content = item.path.read_bytes()  # READ-ONLY access
        except OSError as exc:
            metrics.failures.append((item.logical_ref, f"read_error:{type(exc).__name__}"))
            continue
        try:
            record = registry.register_source_with_blob(
                content=content,
                external_ref=item.logical_ref,   # RELOCATABLE, not absolute
                kind=item.kind or "",
                blob_store=blob,
                profile_id=ROLLOUT_SCOPE["profile_id"],
                project_id=ROLLOUT_SCOPE["project_id"],
                knowledge_space_id=ROLLOUT_SCOPE["knowledge_space_id"],
            )
        except Exception as exc:
            metrics.failures.append((item.logical_ref, f"register_error:{type(exc).__name__}"))
            continue
        metrics.registered += 1
        source_ids.add(record.source_id)
        content_hashes[record.content_hash] = content_hashes.get(record.content_hash, 0) + 1

    metrics.distinct_source_ids = len(source_ids)
    metrics.duplicate_content = sum(c - 1 for c in content_hashes.values() if c > 1)
    return metrics, content_hashes


def extraction_census(
    files: Iterable[DiscoveredFile], metrics: IngestMetrics
) -> None:
    """Classify per-source extraction outcome through the real adapters."""
    from src.corpus.adapters.registry import select_adapter

    for item in files:
        adapter = select_adapter(item.kind or "")
        if adapter is None or not adapter.is_available():
            metrics.extract_parser_unavailable += 1
            continue
        try:
            content = item.path.read_bytes()
            result = adapter.extract(
                source_ref=item.logical_ref, content=content, kind_hint=item.kind or ""
            )
            bucket = classify_extraction(result.status)
        except Exception as exc:
            bucket = "extract_other_failure"
            metrics.failures.append((item.logical_ref, f"extract_raise:{type(exc).__name__}"))
        setattr(metrics, bucket, getattr(metrics, bucket) + 1)


# --- storage helpers -------------------------------------------------------

def open_writer(db_path: Path) -> SQLiteStore:
    store = SQLiteStore(SQLiteStoreConfig(path=db_path))
    store.ensure_schema()
    # DELETE journal so a subsequent read-only connection observes the projection.
    writer_conn(store).execute("PRAGMA journal_mode=DELETE")
    return store


def writer_conn(store: SQLiteStore) -> sqlite3.Connection:
    """Narrow the store's Optional connection to a live one, or fail closed."""
    conn = store._conn
    if conn is None:
        raise RuntimeError("sqlite store is not open")
    return conn


def report_dict(report: Any) -> dict[str, Any]:
    """Uniform dict view over the M10.4/M10.6 report dataclasses."""
    if is_dataclass(report) and not isinstance(report, type):
        return asdict(report)
    return {k: v for k, v in vars(report).items() if not k.startswith("_")}


def dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def peak_rss_bytes() -> int:
    """Peak RSS of this process (ru_maxrss is KiB on Linux)."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


# --- retrieval benchmark ---------------------------------------------------

def authorized_scope() -> AuthorizedCorpusScope:
    return AuthorizedCorpusScope(
        allowed_scopes=(
            (
                ROLLOUT_SCOPE["profile_id"],
                ROLLOUT_SCOPE["project_id"],
                ROLLOUT_SCOPE["knowledge_space_id"],
            ),
        )
    )


def bench_queries(conn, queries: list[str], limit: int = 10) -> dict[str, Any]:
    """Time the real authorized retrieval facade over a fixed query set."""
    scope = authorized_scope()
    latencies: list[float] = []
    hits = 0
    misses = 0
    per_query: list[dict[str, Any]] = []

    for text in queries:
        plan = build_query_plan(
            text=text, metadata={"project_id": ROLLOUT_SCOPE["project_id"]}, limit=limit
        )
        start = time.perf_counter()
        results = retrieve_corpus(conn, scope, plan)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        latencies.append(elapsed_ms)
        if results:
            hits += 1
        else:
            misses += 1
        per_query.append(
            {"query": text, "results": len(results), "ms": round(elapsed_ms, 3)}
        )

    latencies.sort()
    summary = {
        "queries": len(queries),
        "hits": hits,
        "no_hits": misses,
        "median_ms": round(statistics.median(latencies), 3) if latencies else None,
        "max_ms": round(latencies[-1], 3) if latencies else None,
        "per_query": per_query,
    }
    if len(latencies) >= 20:  # p95 only reported when the sample supports it
        summary["p95_ms"] = round(latencies[int(len(latencies) * 0.95) - 1], 3)
    return summary


def repeat_consistency(conn, queries: list[str], rounds: int = 3) -> bool:
    """Identical query set must yield byte-identical ordered unit ids."""
    scope = authorized_scope()
    signatures: list[list[tuple[str, ...]]] = []
    for _ in range(rounds):
        run: list[tuple[str, ...]] = []
        for text in queries:
            plan = build_query_plan(
                text=text,
                metadata={"project_id": ROLLOUT_SCOPE["project_id"]},
                limit=10,
            )
            run.append(tuple(h.unit_id for h in retrieve_corpus(conn, scope, plan)))
        signatures.append(run)
    return all(sig == signatures[0] for sig in signatures)


# --- logical state digest (rebuild equivalence) ----------------------------

def logical_digest(db_path: Path) -> dict[str, Any]:
    """Stable logical projection metrics, excluding transaction-specific values."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = conn.cursor()

        def scalar(sql: str) -> Any:
            return cur.execute(sql).fetchone()[0]

        digest = {
            "sources": scalar("SELECT COUNT(*) FROM zm_corpus_sources"),
            "units": scalar("SELECT COUNT(*) FROM zm_corpus_units"),
            "distinct_content_hashes": scalar(
                "SELECT COUNT(DISTINCT content_hash) FROM zm_corpus_units"
            ),
            "source_ids_digest": scalar(
                "SELECT COUNT(*) || ':' || IFNULL(GROUP_CONCAT(source_id), '') FROM "
                "(SELECT source_id FROM zm_corpus_sources ORDER BY source_id)"
            ),
            "unit_hash_digest": scalar(
                "SELECT COUNT(*) || ':' || IFNULL(GROUP_CONCAT(content_hash), '') FROM "
                "(SELECT content_hash FROM zm_corpus_units ORDER BY unit_id)"
            ),
            "scopes": scalar(
                "SELECT IFNULL(GROUP_CONCAT(s), '') FROM (SELECT DISTINCT "
                "IFNULL(profile_id,'')||'|'||IFNULL(project_id,'')||'|'||"
                "IFNULL(knowledge_space_id,'') AS s FROM zm_corpus_units ORDER BY s)"
            ),
        }
        try:
            digest["relations"] = scalar("SELECT COUNT(*) FROM zm_corpus_relations")
        except sqlite3.Error:
            digest["relations"] = 0
        return digest
    finally:
        conn.close()


def hash_digest(digest: dict[str, Any]) -> str:
    import hashlib

    payload = json.dumps(digest, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
