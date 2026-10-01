"""PKG-3 non-mutating health checks with stable results."""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import stat
import sys
from pathlib import Path
from typing import Any

from .config import EffectiveConfigurationError, load_effective_config
from .paths import (
    CORPUS_REGISTRY_FILENAME,
    ConfigurationError,
    config_path,
    corpus_root,
    derived_db,
    load_config,
    memory_stream,
)
from .version import __version__


def _check(check_id: str, status: str, message: str) -> dict[str, str]:
    return {"id": check_id, "status": status, "message": message}


def _private_dir_ok(path: Path) -> bool:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return False
    return os.name == "nt" or (mode & 0o077) == 0


def _sqlite_check() -> tuple[str, str]:
    version = sqlite3.sqlite_version_info
    if version < (3, 35, 0):
        return "FAIL", "SQLite below required version"
    return "PASS", "SQLite compatible"


def _derived_check() -> tuple[str, str]:
    path = derived_db()
    if not path.exists() or path.is_symlink() or not path.is_file():
        return "FAIL", "derived store missing"
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT MAX(version) AS version FROM zm_migrations").fetchone()
        version = int(row["version"]) if row and row["version"] is not None else 0
        conn.close()
    except sqlite3.Error:
        return "FAIL", "derived store unavailable"
    if version <= 0:
        return "FAIL", "derived schema unavailable"
    return "PASS", "derived schema available"


def _memory_check() -> tuple[str, str]:
    path = memory_stream()
    if not path.is_file() or path.is_symlink() or not _private_dir_ok(path.parent):
        return "FAIL", "canonical Memory stream unavailable"
    try:
        data = path.read_bytes()
        if data and not data.endswith(b"\n"):
            return "FAIL", "canonical Memory stream is truncated"
        for line in data.splitlines():
            if not line.strip():
                continue
            record = json.loads(line.decode("utf-8"))
            if not isinstance(record, dict):
                return "FAIL", "canonical Memory stream is malformed"
    except (OSError, UnicodeError, ValueError):
        return "FAIL", "canonical Memory stream is malformed"
    return "PASS", "canonical Memory stream available"


def _fts5_check() -> tuple[str, str]:
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE _zero_mem_fts_probe USING fts5(content)")
        conn.execute("DROP TABLE _zero_mem_fts_probe")
        conn.close()
    except sqlite3.Error:
        return "WARN", "FTS5 capability unavailable"
    return "PASS", "FTS5 capability available"


_CORPUS_AUTHORIZATION_BASE = (
    "event-path knowledge-space grants authorize per-row via "
    "zm_meta.knowledge_space_id (canonical-first); corpus search reads the "
    "main derived store"
)


def _corpus_authorization_check() -> dict[str, str]:
    from zero_mem import userconfig

    env_val = os.environ.get("ZM_M6_CORPUS_STORE_PATH")
    effective = env_val or userconfig.get_corpus_store_path()
    if not effective:
        return _check("corpus_authorization", "PASS", _CORPUS_AUTHORIZATION_BASE)
    source = "env" if env_val else "config"
    legacy_error: Exception | None = None
    try:
        from pathlib import Path as _P

        from src.integration.m6.runtime import (
            CorpusStoreConfigError as _CorpusStoreConfigError,
            _validate_corpus_store_path,
        )

        try:
            _validate_corpus_store_path(_P(effective))
        except _CorpusStoreConfigError as exc:
            legacy_error = exc
    except Exception as exc:  # defensive: never crash doctor
        legacy_error = exc
    if legacy_error is None:
        return _check(
            "corpus_authorization", "PASS",
            f"legacy corpus-store-path ({source}) is set but unused by corpus "
            f"search; {_CORPUS_AUTHORIZATION_BASE}")
    return _check(
        "corpus_authorization", "WARN",
        f"legacy corpus-store-path ({source}) is unusable and ignored; "
        f"{_CORPUS_AUTHORIZATION_BASE}; remove it with: "
        "zero-mem config unset corpus-store-path")


def _registry_sources(registry: Path) -> int:
    """Distinct source ids in the canonical corpus registry (read-only).

    Raises ValueError on a truncated or malformed registry.
    """
    data = registry.read_bytes()
    if data and not data.endswith(b"\n"):
        raise ValueError("partial final line")
    ids: set[str] = set()
    for raw in data.splitlines():
        if not raw.strip():
            continue
        record = json.loads(raw.decode("utf-8"))
        if not isinstance(record, dict) or not isinstance(record.get("source_id"), str):
            raise ValueError("malformed record")
        ids.add(record["source_id"])
    return len(ids)


def _derived_corpus_units() -> int | None:
    """Corpus unit count in the derived store without mutating it (None = unknown)."""
    path = derived_db()
    if not path.is_file() or path.is_symlink():
        return None
    wal = Path(str(path) + "-wal")
    try:
        mode = "mode=ro" if wal.exists() and wal.stat().st_size > 0 else "mode=ro&immutable=1"
        conn = sqlite3.connect(f"file:{path.as_posix()}?{mode}", uri=True)
        try:
            return int(conn.execute("SELECT COUNT(*) FROM zm_corpus_units").fetchone()[0])
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return None


def _corpus_check() -> tuple[str, str]:
    """DEF-054: report the canonical corpus root, registry and projection state."""
    try:
        root = corpus_root()
    except ConfigurationError:
        return "FAIL", "corpus root path is invalid"
    registry = root / CORPUS_REGISTRY_FILENAME
    if root.is_symlink() or registry.is_symlink():
        return "FAIL", "corpus root is unsafe"
    if not root.is_dir():
        return "WARN", "Corpus root not initialised (run zero-mem setup)"
    if not registry.is_file():
        return "WARN", "Corpus registry missing (run zero-mem setup)"
    try:
        sources = _registry_sources(registry)
    except (OSError, UnicodeError, ValueError):
        return "FAIL", "corpus registry is malformed"
    if sources == 0:
        return "WARN", "Corpus is empty (no sources registered)"
    units = _derived_corpus_units()
    if units is None:
        return "WARN", f"corpus registry has {sources} source(s); derived corpus state is unavailable (run zero-mem upgrade)"
    if units == 0:
        return "WARN", (
            f"corpus registry has {sources} source(s) but the derived store has "
            "0 corpus units (run zero-mem upgrade to rebuild)"
        )
    return "PASS", f"corpus registry has {sources} source(s); derived store has {units} unit(s)"


def _memory_runtime_checks() -> list[dict[str, str]]:
    """T8: checks of the shared-memory runtime (read-only; counts and flags only, never paths or content).

    Every one is PASS or WARN - never FAIL: the integrity of the canonical state is the ``memory`` / ``corpus`` checks'
    job, and a rebuildable derived state or an empty memory must not block ``upgrade`` / ``restore``.
    """
    ids = ("memory_data_root", "memory_schema", "memory_grants", "memory_sources")
    try:
        from .memory_health import snapshot

        snap = snapshot()
    except Exception:  # noqa: BLE001 - doctor never crashes
        return [_check(i, "WARN", "memory runtime status unavailable") for i in ids]
    if not snap["initialised"]:
        return [_check(i, "WARN", "memory runtime not initialised (run zero-mem setup)") for i in ids]
    checks: list[dict[str, str]] = []
    if snap["data_root_writable"]:
        checks.append(_check("memory_data_root", "PASS", "data root and corpus root are writable"))
    else:
        checks.append(_check("memory_data_root", "WARN", "data root is not writable by this user: memory writes will fail"))
    if snap["schema_version"] is None:
        checks.append(_check("memory_schema", "WARN", "derived schema unreadable (run zero-mem upgrade)"))
    elif snap["schema_current"]:
        checks.append(_check("memory_schema", "PASS", f"schema version {snap['schema_version']} (current)"))
    else:
        checks.append(_check("memory_schema", "WARN",
                             f"schema version {snap['schema_version']} differs from this install (run zero-mem upgrade)"))
    grants = snap["grants"]
    if grants is None:
        checks.append(_check("memory_grants", "WARN", "grants unreadable (run zero-mem upgrade)"))
    elif grants["agents"] == 0:
        checks.append(_check("memory_grants", "WARN", "no agents registered (zero-mem agents add <profile>)"))
    else:
        checks.append(_check("memory_grants", "PASS",
                             f"{grants['active']} active grant(s) ({grants['read']} read, {grants['write']} write) "
                             f"for {grants['agents']} agent(s)"))
    sources = snap["sources"]
    if not snap["registry_ok"]:
        checks.append(_check("memory_sources", "WARN", "corpus registry unreadable (see the corpus check)"))
    elif sources["total"] == 0:
        checks.append(_check("memory_sources", "WARN", "no memories yet (zero-mem add / ingest)"))
    else:
        summary = (f"{sources['total']} source(s) ({sources['forgotten']} forgotten), "
                   f"{snap['units'] if snap['units'] is not None else '?'} unit(s)"
                   + (f"; last write {snap['last_write']}" if snap["last_write"] else ""))
        if snap["drift"]:
            checks.append(_check("memory_sources", "WARN",
                                 f"{snap['drift']} source(s) not projected: {summary} (run zero-mem upgrade)"))
        else:
            checks.append(_check("memory_sources", "PASS", summary))
    return checks


def collect() -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    implementation = getattr(sys, "implementation", None)
    if implementation is not None and implementation.name == "cpython" and (3, 11) <= sys.version_info[:2] < (3, 14):
        checks.append(_check("python", "PASS", "compatible CPython"))
    else:
        checks.append(_check("python", "FAIL", "CPython >=3.11,<3.14 required"))

    try:
        import zero_mem

        if getattr(zero_mem, "__version__", None) == __version__:
            checks.append(_check("runtime", "PASS", "runtime importable"))
        else:
            checks.append(_check("runtime", "FAIL", "runtime version mismatch"))
    except Exception:
        checks.append(_check("runtime", "FAIL", "runtime unavailable"))

    sqlite_status, sqlite_message = _sqlite_check()
    checks.append(_check("sqlite", sqlite_status, sqlite_message))

    try:
        effective = load_effective_config()
        if effective.data_root != effective.data_root.resolve():
            raise EffectiveConfigurationError("effective data root is not normalized")
        checks.append(_check("effective_configuration", "PASS", "effective configuration converged"))
    except EffectiveConfigurationError as exc:
        checks.append(_check("effective_configuration", "FAIL", str(exc)))

    try:
        load_config()
        checks.append(_check("configuration", "PASS", "configuration valid"))
    except ConfigurationError as exc:
        checks.append(_check("configuration", "FAIL", str(exc)))

    # V150-R1 (DEF-019): the event path authorizes per-row via
    # zm_meta.knowledge_space_id, and corpus search reads the main derived store.
    # DEF-066: the legacy ``corpus-store-path`` setting is vestigial - it never
    # affects either path, so a missing/invalid value is a WARN (never FAIL, so
    # it cannot block upgrade/restore) and no longer prescribes setting it.
    try:
        checks.append(_corpus_authorization_check())
    except Exception as exc:  # pragma: no cover - defensive
        checks.append(_check("corpus_authorization", "WARN", f"corpus authorization status unavailable ({type(exc).__name__})"))


    memory_status, memory_message = _memory_check()
    checks.append(_check("memory", memory_status, memory_message))

    derived_status, derived_message = _derived_check()
    checks.append(_check("derived", derived_status, derived_message))
    fts_status, fts_message = _fts5_check()
    checks.append(_check("fts5", fts_status, fts_message))

    try:
        from .hermes_integration import inspect_integration

        hermes = inspect_integration()
        if hermes["configured"] and hermes["zero_mem_ready"] and hermes["zero_mem_enabled"]:
            checks.append(_check("hermes", "PASS", "Hermes integration configured and healthy"))
        elif hermes["hermes_found"]:
            checks.append(_check("hermes", "WARN", "Hermes available but optional integration is not configured"))
        else:
            checks.append(_check("hermes", "WARN", "Hermes integration not configured"))
    except Exception:
        checks.append(_check("hermes", "WARN", "Hermes integration status unavailable"))
    corpus_status, corpus_message = _corpus_check()
    checks.append(_check("corpus", corpus_status, corpus_message))
    checks.extend(_memory_runtime_checks())
    checks.append(_check("obsidian", "WARN", "Obsidian projection not configured"))
    checks.append(_check("pypdf", "OPTIONAL", "optional PDF parser available" if importlib.util.find_spec("pypdf") else "optional PDF parser absent"))
    checks.append(_check("ai_api", "OPTIONAL", "AI API is not required"))

    overall = "NOT_READY" if any(item["status"] == "FAIL" for item in checks) else "READY"
    return {"schema_version": 1, "overall": overall, "checks": checks}


def render(report: dict[str, Any], *, as_json: bool) -> str:
    if as_json:
        return json.dumps(report, sort_keys=True, separators=(",", ":"))
    lines = [f"Zero-Mem doctor: {report['overall']}"]
    lines.extend(f"{item['status']} {item['id']}: {item['message']}" for item in report["checks"])
    return "\n".join(lines)


def run(*, as_json: bool = False) -> int:
    report = collect()
    print(render(report, as_json=as_json))
    return 0 if report["overall"] == "READY" else 1
