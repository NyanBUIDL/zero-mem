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
    ConfigurationError,
    config_path,
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
    checks.append(_check("corpus", "WARN", "Corpus root not configured"))
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
