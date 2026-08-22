"""M3.1 — true read-only SQLite access path.

M3 must NOT reuse the M2 read-write ``SQLiteStore``. This module opens the derived
SQLite database through an explicitly read-only connection and performs only
``SELECT`` statements. It never calls ``ensure_schema``, migrations, ``downgrade_to``,
schema creation, WAL-setup that mutates state, or any write transaction.

Schema-version validation is SELECT-only: it reads ``MAX(version)`` from
``zm_migrations`` and refuses an incompatible (unknown-future) version with a fixed
sanitized error. It performs no migration.
"""

from __future__ import annotations

import sqlite3
import stat
from pathlib import Path
from typing import Optional

from .models import QueryError
from src.storage.coordination import locked, regular_identity

# Imported read-only: the code's current schema version. No migration is ever run.
from src.storage.migrations import CURRENT_SCHEMA_VERSION  # noqa: E402


class ReadonlyStore:
    """Project-owned read-only view over the derived SQLite store.

    Opens with ``file:<path>?mode=ro`` (URI) and enables ``PRAGMA query_only=ON``
    where supported. Any attempt to mutate would fail at the connection level.
    """

    def __init__(self, conn: sqlite3.Connection, path: Path) -> None:
        self._conn = conn
        self.path = path

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def get_schema_version(self) -> int:
        """SELECT-only schema-version read. No migration; never writes.

        Returns 0 if the store has no ``zm_migrations`` table yet.
        """
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
        except sqlite3.Error as exc:  # pragma: no cover - defensive
            raise QueryError(code="database_unavailable", message="schema_version_query_failed") from exc

    def validate_schema(self) -> int:
        """Read-only version check. Raises ``schema_mismatch`` on unknown-future version.

        Returns the current version. Performs no write.
        """
        version = self.get_schema_version()
        if version > CURRENT_SCHEMA_VERSION:
            raise QueryError(
                code="schema_mismatch",
                message=f"unknown_future_version: db_{version} > code_{CURRENT_SCHEMA_VERSION}",
            )
        return version

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass


def open_readonly(database_path: Path) -> ReadonlyStore:
    """Open the derived SQLite store as strictly read-only.

    Uses ``file:<path>?mode=ro`` (``uri=True``) and enables ``PRAGMA query_only=ON``
    where supported. Schema version is validated SELECT-only; no migration runs.
    """
    if not isinstance(database_path, Path):
        raise QueryError(code="database_unavailable", message="invalid_path_type")
    if not database_path.is_absolute():
        raise QueryError(code="database_unavailable", message="invalid_path")
    try:
        identity = regular_identity(database_path)
    except OSError:
        raise QueryError(code="database_unavailable", message="missing_database") from None
    uri = f"file:{database_path.as_posix()}?mode=ro"
    if len(database_path.parts) >= 5 and database_path.parts[1:4] == ("proc", "self", "fd"):
        try:
            coordination_path = database_path.resolve(strict=True)
        except OSError:
            raise QueryError(code="database_unavailable", message="unsafe_database_path") from None
    else:
        coordination_path = database_path
    lock_path = coordination_path.with_name(coordination_path.name + ".lock")
    try:
        with locked(lock_path, mode="shared", timeout=5.0):
            try:
                conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
            except sqlite3.Error as exc:
                raise QueryError(code="database_unavailable", message="open_failed") from exc
            conn.row_factory = sqlite3.Row
            try:
                if regular_identity(database_path) != identity:
                    conn.close()
                    raise QueryError(code="database_unavailable", message="database_identity_changed")
            except OSError:
                conn.close()
                raise QueryError(code="database_unavailable", message="unsafe_database_path") from None
            try:
                # R124-10: without a busy timeout, concurrent readonly opens can
                # fail transiently with "database is locked" when another reader
                # is checkpointing; wait instead of erroring.
                conn.execute("PRAGMA busy_timeout = 5000")
            except sqlite3.Error:
                pass
            try:
                # Blocks write-adjacent pragmas (e.g. checkpoint) where supported.
                conn.execute("PRAGMA query_only = ON")
            except sqlite3.Error:
                # Older / unsupported builds ignore it; mode=ro still prevents writes.
                pass
            store = ReadonlyStore(conn, database_path)
            store.validate_schema()
            return store
    except TimeoutError:
        raise QueryError(code="database_unavailable", message="coordination_timeout") from None


def _readonly_conn_is_query_only(store: ReadonlyStore) -> bool:
    """Best-effort reflection of whether ``query_only`` is active (test support)."""
    try:
        row = store.conn.execute("PRAGMA query_only").fetchone()
        if row is None:
            return False
        # PRAGMA query_only returns a single integer column (0/1).
        value = int(tuple(row)[0])
        return value == 1
    except sqlite3.Error:
        return False
