"""Read-only health snapshot of the shared-memory runtime (``zero-mem doctor`` and ``zero-mem memory-status --json``).

Cheap and non-mutating: it stats a few paths, reads the canonical corpus registry (one JSON line per source version)
and opens the derived SQLite store read-only. The result carries counts, flags and one timestamp - never a path and
never any memory content - so it is safe to print, log or paste into a bug report.

``snapshot()`` follows the standard data root (``ZERO_MEM_DATA_ROOT`` / XDG, ``ZERO_MEM_CORPUS_ROOT``), exactly like
``zero-mem doctor``.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import paths


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect_ro(db: Path) -> sqlite3.Connection:
    wal = Path(str(db) + "-wal")
    mode = "mode=ro" if wal.exists() and wal.stat().st_size > 0 else "mode=ro&immutable=1"
    return sqlite3.connect(f"file:{db.as_posix()}?{mode}", uri=True)


def _latest_registry(registry: Path) -> dict[str, tuple[Any, Any]]:
    """``source_id -> (content_hash, lifecycle_status)`` of the latest version of every source (append-only file)."""
    data = registry.read_bytes()
    if data and not data.endswith(b"\n"):
        raise ValueError("partial final line")
    latest: dict[str, tuple[Any, Any]] = {}
    for raw in data.splitlines():
        if not raw.strip():
            continue
        record = json.loads(raw.decode("utf-8"))
        if not isinstance(record, dict) or not isinstance(record.get("source_id"), str):
            raise ValueError("malformed record")
        latest[record["source_id"]] = (record.get("content_hash"), record.get("lifecycle_status"))
    return latest


def _writable(path: Path) -> bool:
    return path.is_dir() and os.access(path, os.W_OK | os.X_OK)


def snapshot() -> dict[str, Any]:
    """Counts and flags of the memory runtime. Never raises for a missing or damaged store (fields stay ``None``)."""
    out: dict[str, Any] = {
        "initialised": False, "data_root_writable": False, "corpus_root_exists": False,
        "schema_version": None, "schema_current": False,
        "sources": {"total": 0, "live": 0, "forgotten": 0}, "units": None, "grants": None, "drift": None,
        "last_write": None, "registry_ok": True,
    }
    data, db, stream, corpus = paths.data_root(), paths.derived_db(), paths.memory_stream(), paths.corpus_root()
    registry = corpus / paths.CORPUS_REGISTRY_FILENAME
    out["corpus_root_exists"] = corpus.is_dir() and registry.is_file()
    out["initialised"] = data.is_dir() and db.is_file() and stream.is_file()
    if not out["initialised"]:
        return out
    out["data_root_writable"] = all(_writable(p) for p in (data, db.parent, stream.parent)) and (
        _writable(corpus) if corpus.is_dir() else True)

    stamps = [p.stat().st_mtime for p in (registry, stream) if p.is_file()]
    out["last_write"] = _iso(max(stamps)) if stamps else None

    latest: Optional[dict[str, tuple[Any, Any]]] = None
    if registry.is_file() and not registry.is_symlink():
        try:
            latest = _latest_registry(registry)
        except (OSError, UnicodeError, ValueError):
            out["registry_ok"] = False
    if latest is not None:
        forgotten = sum(1 for _h, status in latest.values() if status == "deleted")
        out["sources"] = {"total": len(latest), "live": len(latest) - forgotten, "forgotten": forgotten}

    try:
        from src.storage.migrations import CURRENT_SCHEMA_VERSION

        conn = _connect_ro(db)
        try:
            version = conn.execute("SELECT MAX(version) FROM zm_migrations").fetchone()[0]
            out["schema_version"] = int(version) if version is not None else None
            out["schema_current"] = out["schema_version"] == CURRENT_SCHEMA_VERSION
            out["units"] = int(conn.execute("SELECT COUNT(*) FROM zm_corpus_units").fetchone()[0])
            grants = conn.execute(
                "SELECT operation, subject_profile FROM zm_access_grants "
                "WHERE lifecycle_status='active' AND (state IS NULL OR state != 'revoked')").fetchall()
            out["grants"] = {"active": len(grants), "read": sum(1 for op, _p in grants if op == "READ"),
                             "write": sum(1 for op, _p in grants if op == "WRITE"),
                             "agents": len({p for _op, p in grants})}
            if latest is not None:
                derived = {row[0]: (row[1], row[2]) for row in conn.execute(
                    "SELECT source_id, content_hash, lifecycle_status FROM zm_corpus_sources")}
                out["drift"] = sum(1 for sid, key in latest.items() if derived.get(sid) != key)
        finally:
            conn.close()
    except (sqlite3.Error, OSError, ImportError, ValueError, TypeError):
        pass
    return out


__all__ = ["snapshot"]
