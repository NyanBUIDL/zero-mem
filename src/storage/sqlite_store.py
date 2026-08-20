"""M2.1 SQLite foundation and deterministic migration framework.

SQLite is a *derived*, fully-rebuildable projection of the canonical JSONL raw
event stream (ADR-M1-001, ARCHITECTURE §2/§9). This module establishes only the
connection lifecycle, required pragmas, schema-version tracking, and a
transaction-safe migration runner. It does NOT ingest JSONL, build indexes,
project lifecycle/provenance/relations, or perform any retrieval/routing. Those
belong to later M2 increments.

Design invariants (required rules):
- SQLite is derived only; JSONL remains the source of record.
- Migrations are idempotent: reopening an up-to-date database applies nothing.
- A failed migration never advances the recorded schema version (rolled back).
- An unknown future schema version is refused without modifying the database.
- Errors are sanitized: no raw SQL, payloads, secrets, or uncontrolled exception
  text reach the exception message.
- No LLM or network calls.
"""
from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .migrations import CURRENT_SCHEMA_VERSION, MIGRATIONS

MIN_SQLITE_VERSION = (3, 35, 0)  # transactional DDL / robust WAL
DEFAULT_BUSY_TIMEOUT_MS = 5000
# WAL + NORMAL is the approved M2.1 durability setting (plan §6). FULL is
# selectable when per-line fsync matters (M2.2 ingestion).
DEFAULT_SYNCHRONOUS = "NORMAL"
APPROVED_SYNCHRONOUS = frozenset({"OFF", "NORMAL", "FULL", "EXTRA"})
# The derived store must never live inside the installed Hermes home.
REAL_HERMES_HOME = Path.home() / ".hermes"


class StoreError(Exception):
    """Base class for sanitized store errors."""


class StoreInitError(StoreError):
    """Sanitized database initialization failure."""


class MigrationError(StoreError):
    """Sanitized migration failure (version not advanced)."""


class SchemaVersionError(StoreError):
    """Sanitized incompatible schema-version refusal."""


@dataclass(frozen=True)
class SQLiteStoreConfig:
    path: Path
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS
    synchronous: str = DEFAULT_SYNCHRONOUS

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path):
            raise StoreInitError("store_init_error: invalid_path_type")
        if self.synchronous not in APPROVED_SYNCHRONOUS:
            raise StoreInitError("store_init_error: invalid_synchronous_setting")
        if self.busy_timeout_ms < 0:
            raise StoreInitError("store_init_error: invalid_busy_timeout")


def _safe_basename(path: Path) -> str:
    try:
        return path.name
    except Exception:
        return "db"


def _sanitized_init_error(kind: str, path: Path) -> StoreInitError:
    return StoreInitError(f"store_init_error: {kind}: {_safe_basename(path)}")


def _sanitized_migration_error(kind: str, version: int) -> MigrationError:
    return MigrationError(f"migration_error: {kind}: version_{version}")


def _require_compatible_sqlite() -> None:
    if sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
        raise StoreInitError(
            f"store_init_error: sqlite_too_old: have_{sqlite3.sqlite_version_info}"
        )


def _guard_real_hermes_home(path: Path) -> None:
    try:
        resolved = path.resolve()
    except Exception:
        raise _sanitized_init_error("unresolvable_path", path)
    try:
        resolved.relative_to(REAL_HERMES_HOME.resolve())
        raise _sanitized_init_error("refuses_real_hermes_home", path)
    except ValueError:
        return


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class SQLiteStore:
    """Project-owned SQLite store: derived index/state layer over JSONL."""

    def __init__(self, config: SQLiteStoreConfig) -> None:
        _require_compatible_sqlite()
        _guard_real_hermes_home(config.path)
        self.config = config
        self.path = config.path
        self._conn: Optional[sqlite3.Connection] = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if os.name != "nt":
                os.chmod(self.path.parent, 0o700)
            self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._apply_pragmas()
        except StoreError:
            raise
        except Exception:
            raise _sanitized_init_error("open_failed", self.path)

    def _apply_pragmas(self) -> None:
        try:
            cur = self._conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=%d" % int(self.config.busy_timeout_ms))
            cur.execute("PRAGMA synchronous=%s" % self.config.synchronous)
            self._conn.commit()
        except Exception:
            raise _sanitized_init_error("pragma_failed", self.path)

    # ---- schema version tracking ------------------------------------------
    def get_schema_version(self) -> int:
        try:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='zm_migrations'"
            )
            if cur.fetchone() is None:
                return 0
            cur.execute("SELECT MAX(version) AS v FROM zm_migrations")
            row = cur.fetchone()
            return int(row["v"]) if row and row["v"] is not None else 0
        except Exception:
            raise _sanitized_init_error("version_query_failed", self.path)

    def ensure_schema(self) -> int:
        """Idempotently apply all pending migrations up to CURRENT_SCHEMA_VERSION.

        Returns the resulting schema version. Refuses to touch a database whose
        recorded version exceeds the code's current version (unknown future).
        """
        current = self.get_schema_version()
        if current > CURRENT_SCHEMA_VERSION:
            raise SchemaVersionError(
                f"schema_version_error: unknown_future_version: "
                f"db_{current} > code_{CURRENT_SCHEMA_VERSION}"
            )
        if current < 0:
            raise SchemaVersionError(
                f"schema_version_error: negative_version: {current}"
            )
        pending = sorted(
            v for v in MIGRATIONS if v > current and v <= CURRENT_SCHEMA_VERSION
        )
        for version in pending:
            self._apply_up(version, note="m2.1_initial")
        return self.get_schema_version()

    def _apply_up(self, version: int, note: str) -> None:
        module = MIGRATIONS[version]
        try:
            self._conn.execute("BEGIN")
            module.up(self._conn, note)
            self._conn.execute(
                "INSERT INTO zm_migrations(version, applied_at, note) "
                "VALUES (?,?,?)",
                (version, _now(), note),
            )
            self._conn.commit()
        except Exception:
            try:
                self._conn.rollback()
            except Exception:
                pass
            raise _sanitized_migration_error("apply_up_failed", version)

    def _apply_down(self, version: int, note: str) -> None:
        if version not in MIGRATIONS:
            raise _sanitized_migration_error("unknown_migration", version)
        current = self.get_schema_version()
        if version > current:
            raise _sanitized_migration_error("downgrade_above_current", version)
        try:
            self._conn.execute("BEGIN")
            # Remove ledger row first so the migration may freely drop tables.
            self._conn.execute(
                "DELETE FROM zm_migrations WHERE version=?", (version,)
            )
            MIGRATIONS[version].down(self._conn, note)
            self._conn.commit()
        except Exception:
            try:
                self._conn.rollback()
            except Exception:
                pass
            raise _sanitized_migration_error("apply_down_failed", version)

    def downgrade_to(self, target: int, note: str = "rollback") -> None:
        """Supported rollback to a lower version.

        Rejects unknown, negative, or not-lower targets. Applies downgrades in
        reverse version order so intermediate schema states stay consistent.
        """
        if target < 0:
            raise SchemaVersionError(
                f"schema_version_error: downgrade_negative: {target}"
            )
        current = self.get_schema_version()
        if target >= current:
            raise SchemaVersionError(
                f"schema_version_error: downgrade_not_supported: "
                f"target_{target} >= current_{current}"
            )
        for version in sorted(
            (v for v in MIGRATIONS if v <= current and v > target), reverse=True
        ):
            self._apply_down(version, note=note)

    # ---- inspection helpers (no ranking/routing) ---------------------------
    def table_exists(self, name: str) -> bool:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type IN ('table','view') AND name=?",
            (name,),
        )
        return cur.fetchone() is not None

    def index_exists(self, name: str) -> bool:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            (name,),
        )
        return cur.fetchone() is not None

    def pragma_value(self, name: str) -> Optional[str]:
        cur = self._conn.cursor()
        cur.execute(f"PRAGMA {name}")
        row = cur.fetchone()
        return row[0] if row is not None else None

    def secure_permissions(self) -> None:
        if os.name == "nt":
            return
        try:
            os.chmod(self.path, 0o600)
            for suffix in ("-wal", "-shm"):
                p = Path(str(self.path) + suffix)
                if p.exists():
                    os.chmod(p, 0o600)
        except Exception:
            raise _sanitized_init_error("permission_lock_failed", self.path)

    def close(self) -> None:
        try:
            if getattr(self, "_conn", None) is not None:
                self._conn.close()
                self._conn = None
        except Exception:
            pass

    def __enter__(self) -> "SQLiteStore":
        return self

    def __exit__(self, *_a: object) -> None:
        self.close()


__all__ = [
    "SQLiteStore",
    "SQLiteStoreConfig",
    "StoreError",
    "StoreInitError",
    "MigrationError",
    "SchemaVersionError",
    "CURRENT_SCHEMA_VERSION",
]
