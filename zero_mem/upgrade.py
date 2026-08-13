"""PKG-6 safe derived-state upgrade lifecycle.

Application replacement never migrates or rewrites canonical Zero-Mem data.  The
only mutable upgrade target is the disposable SQLite projection, built in a
sibling staging directory and atomically promoted only after canonical
validation and staged rebuild succeed.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import uuid
import hashlib
from pathlib import Path
from typing import Any

from src.access.rebuild import rebuild_policy_state
from src.corpus.contracts import CorpusSourceRecord
from src.corpus.derived_store import rebuild_from_corpus
from src.corpus.registry import CorpusSourceRegistry, REGISTRY_FILENAME
from src.m8.projection_store import rebuild_graph
from src.m8.temporal_projection import project_temporal_index
from src.project_memory.rebuild import rebuild_all_project_memory
from src.storage.ingest import rebuild_from_jsonl
from src.storage.migrations import CURRENT_SCHEMA_VERSION
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig

from .commands_doctor import collect as collect_doctor
from .paths import ConfigurationError, data_root, derived_db, derived_root, load_config, memory_stream
from .version import __version__


SUPPORTED = "SUPPORTED"
NO_MIGRATION_REQUIRED = "NO_MIGRATION_REQUIRED"
MIGRATION_REQUIRED = "MIGRATION_REQUIRED"
FUTURE_VERSION_UNSUPPORTED = "FUTURE_VERSION_UNSUPPORTED"
CORRUPT_STATE = "CORRUPT_STATE"


class UpgradeError(RuntimeError):
    """Bounded operator error for safe upgrade lifecycle failures."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> UpgradeError:
    return UpgradeError(code)


def _safe_root(path: Path, *, code: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute() or candidate == Path("/"):
        raise _fail(code)
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current /= part
        if current.is_symlink():
            raise _fail(code)
    return candidate


def _validate_memory(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise _fail("CANONICAL_MEMORY_UNAVAILABLE")
    try:
        payload = path.read_bytes()
    except OSError:
        raise _fail("CANONICAL_MEMORY_UNAVAILABLE") from None
    if payload and not payload.endswith(b"\n"):
        raise _fail("CANONICAL_MEMORY_INVALID")
    for raw in payload.splitlines():
        if not raw.strip():
            continue
        try:
            record = json.loads(raw.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (UnicodeError, ValueError):
            raise _fail("CANONICAL_MEMORY_INVALID") from None
        if not isinstance(record, dict) or not isinstance(record.get("event_id"), str) or not record["event_id"]:
            raise _fail("CANONICAL_MEMORY_INVALID")


def _validate_corpus(root: Path | None) -> None:
    if root is None:
        return
    checked = _safe_root(root, code="CORPUS_UNSAFE")
    registry = checked / REGISTRY_FILENAME
    if checked.is_symlink() or not checked.is_dir() or registry.is_symlink() or not registry.is_file():
        raise _fail("CORPUS_UNAVAILABLE")
    try:
        registry_bytes = registry.read_bytes()
    except OSError:
        raise _fail("CORPUS_UNAVAILABLE") from None
    if registry_bytes and not registry_bytes.endswith(b"\n"):
        raise _fail("CORPUS_INVALID")
    try:
        for raw in registry_bytes.splitlines():
            record = CorpusSourceRecord.from_dict(json.loads(raw.decode("utf-8")))
            if record.blob_ref is None:
                continue
            digest = record.blob_ref
            blob = checked / "blobs" / digest[:2] / digest
            if blob.is_symlink() or not blob.is_file() or hashlib.sha256(blob.read_bytes()).hexdigest() != digest:
                raise ValueError
    except (OSError, UnicodeError, ValueError, KeyError):
        raise _fail("CORPUS_INVALID") from None


def _schema_version(path: Path) -> int | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
        try:
            row = conn.execute("SELECT MAX(version) FROM zm_migrations").fetchone()
            return int(row[0]) if row and row[0] is not None else 0
        finally:
            conn.close()
    except sqlite3.Error:
        raise _fail("DERIVED_STATE_INVALID") from None


def _corpus_root_from_environment() -> Path | None:
    value = os.environ.get("ZERO_MEM_CORPUS_ROOT")
    return Path(value).expanduser() if value else None


def check() -> dict[str, Any]:
    """Inspect lifecycle compatibility without changing any path or file."""
    try:
        config = load_config()
    except ConfigurationError:
        return _report(CORRUPT_STATE, schema_version=None, doctor_readiness="NOT_READY")
    if config is None:  # defensive: required=True currently never returns None
        return _report(CORRUPT_STATE, schema_version=None, doctor_readiness="NOT_READY")
    try:
        _safe_root(data_root(), code="DATA_ROOT_UNSAFE")
        _validate_memory(memory_stream())
        _validate_corpus(_corpus_root_from_environment())
        version = _schema_version(derived_db())
        if version is not None and version > CURRENT_SCHEMA_VERSION:
            return _report(FUTURE_VERSION_UNSUPPORTED, schema_version=version, doctor_readiness="NOT_READY")
        compatibility = NO_MIGRATION_REQUIRED if version == CURRENT_SCHEMA_VERSION else MIGRATION_REQUIRED
        doctor = collect_doctor()
        return _report(compatibility, schema_version=version, doctor_readiness=doctor["overall"])
    except UpgradeError:
        return _report(CORRUPT_STATE, schema_version=None, doctor_readiness="NOT_READY")


def _report(compatibility: str, *, schema_version: int | None, doctor_readiness: str) -> dict[str, Any]:
    migration_required = compatibility == MIGRATION_REQUIRED
    status = "READY" if compatibility in {SUPPORTED, NO_MIGRATION_REQUIRED, MIGRATION_REQUIRED} else "REFUSED"
    return {
        "status": status,
        "package_version": __version__,
        "data_format_version": 1,
        "schema_version": schema_version,
        "target_schema_version": CURRENT_SCHEMA_VERSION,
        "compatibility": compatibility,
        "migration_required": migration_required,
        "backup_readiness": "RECOMMENDED",
        "doctor_readiness": doctor_readiness,
    }


def _rebuild_derived(destination: Path, *, corpus_root: Path | None) -> None:
    """Rebuild every disposable projection from validated canonical sources."""
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    store = SQLiteStore(SQLiteStoreConfig(path=destination))
    try:
        conn = store._conn
        if conn is None:
            raise _fail("REBUILD_FAILED")
        store.ensure_schema()
        rebuild_from_jsonl(store, memory_stream())
        rebuild_all_project_memory(store, memory_stream())
        rebuild_policy_state(conn, memory_stream())
        if corpus_root is not None:
            registry = CorpusSourceRegistry(root=corpus_root)
            rebuild_from_corpus(conn, registry)
        latest = conn.execute("SELECT MAX(created_at) FROM zm_meta").fetchone()[0]
        if latest:
            rebuild_graph(conn, version="1", built_at=latest, source_cutoff=latest)
            project_temporal_index(conn, source_cutoff=latest, built_at=latest)
        conn.commit()
    except UpgradeError:
        raise
    except Exception:
        raise _fail("REBUILD_FAILED") from None
    finally:
        store.close()


def _validate_staged_derived(path: Path) -> None:
    version = _schema_version(path)
    if version != CURRENT_SCHEMA_VERSION:
        raise _fail("REBUILD_FAILED")


def upgrade() -> dict[str, Any]:
    """Rebuild disposable derived state and atomically activate it.

    Canonical JSONL, corpus registry/blobs, artifacts, profiles/grants, and
    configuration are validated but never rewritten.  A staging failure happens
    before activation and therefore leaves the prior active state usable.
    """
    report = check()
    compatibility = report["compatibility"]
    if compatibility == FUTURE_VERSION_UNSUPPORTED:
        raise _fail("FUTURE_VERSION_UNSUPPORTED")
    if compatibility == CORRUPT_STATE:
        raise _fail("CORRUPT_STATE")

    active = derived_db()
    parent = derived_root()
    _safe_root(data_root(), code="DATA_ROOT_UNSAFE")
    if active.is_symlink() or (active.exists() and not active.is_file()):
        raise _fail("DERIVED_STATE_INVALID")
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if parent.is_symlink() or not parent.is_dir():
        raise _fail("DERIVED_STATE_INVALID")
    corpus_root = _corpus_root_from_environment()
    staging_dir = Path(tempfile.mkdtemp(prefix=".zero-mem-upgrade-", suffix=".partial", dir=str(parent)))
    staged = staging_dir / active.name
    rollback = active.with_name(f".{active.name}.rollback-{uuid.uuid4().hex[:8]}")
    activated = False
    try:
        _rebuild_derived(staged, corpus_root=corpus_root)
        _validate_staged_derived(staged)
        if active.exists():
            os.replace(active, rollback)
        os.replace(staged, active)
        activated = True
        doctor = collect_doctor()
        if doctor["overall"] != "READY":
            raise _fail("DOCTOR_FAILED")
        if rollback.exists():
            rollback.unlink()
        return {**report, "status": "SUCCESS", "doctor_readiness": doctor["overall"]}
    except UpgradeError:
        if activated:
            try:
                if active.exists():
                    active.unlink()
                if rollback.exists():
                    os.replace(rollback, active)
            except OSError:
                raise _fail("ROLLBACK_FAILED") from None
        raise
    except OSError:
        if activated:
            try:
                if active.exists():
                    active.unlink()
                if rollback.exists():
                    os.replace(rollback, active)
            except OSError:
                raise _fail("ROLLBACK_FAILED") from None
        raise _fail("UPGRADE_FAILED") from None
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
        if rollback.exists():
            try:
                rollback.unlink()
            except OSError:
                pass


__all__ = [
    "SUPPORTED",
    "NO_MIGRATION_REQUIRED",
    "MIGRATION_REQUIRED",
    "FUTURE_VERSION_UNSUPPORTED",
    "CORRUPT_STATE",
    "UpgradeError",
    "check",
    "upgrade",
]
