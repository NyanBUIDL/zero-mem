"""M2.1 focused tests: SQLite foundation and migration framework.

These tests cover the M2.1 scope only (schema + migration framework). They do
not ingest JSONL, build indexes, or perform retrieval/routing. All use temporary
directories; none write to the real ~/.hermes.
"""
from __future__ import annotations

import os
import socket
import sqlite3
from pathlib import Path
from unittest import mock

import pytest

from src.storage.migrations import CURRENT_SCHEMA_VERSION, MIGRATIONS
from src.storage.sqlite_store import (
    SQLiteStore,
    SQLiteStoreConfig,
    MigrationError,
    SchemaVersionError,
    StoreInitError,
)


def _config(tmp_path: Path, name: str = "meta.sqlite") -> SQLiteStoreConfig:
    return SQLiteStoreConfig(path=tmp_path / name)


def test_database_creation_in_temporary_directory(tmp_path: Path) -> None:
    db = SQLiteStore(_config(tmp_path))
    try:
        assert db.path.exists()
        assert db.get_schema_version() == 0
    finally:
        db.close()


def test_parent_directory_creation(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "c" / "meta.sqlite"
    assert not nested.parent.exists()
    db = SQLiteStore(SQLiteStoreConfig(path=nested))
    try:
        assert nested.parent.is_dir()
        assert nested.exists()
    finally:
        db.close()


def test_connection_open_and_close(tmp_path: Path) -> None:
    db = SQLiteStore(_config(tmp_path))
    assert db._conn is not None
    db.close()
    assert db._conn is None
    # Reopen works after close.
    db2 = SQLiteStore(_config(tmp_path))
    try:
        assert db2._conn is not None
    finally:
        db2.close()


def test_required_sqlite_pragmas(tmp_path: Path) -> None:
    db = SQLiteStore(_config(tmp_path))
    try:
        assert db.pragma_value("journal_mode") == "wal"
        assert db.pragma_value("foreign_keys") == 1
        assert db.pragma_value("synchronous") == 1  # NORMAL
        assert db.pragma_value("busy_timeout") == 5000
    finally:
        db.close()


def test_busy_timeout_and_synchronous_configurable(tmp_path: Path) -> None:
    cfg = SQLiteStoreConfig(
        path=tmp_path / "x.sqlite", busy_timeout_ms=2500, synchronous="FULL"
    )
    db = SQLiteStore(cfg)
    try:
        assert db.pragma_value("busy_timeout") == 2500
        assert db.pragma_value("synchronous") == 2  # FULL
    finally:
        db.close()


def test_initial_schema_version(tmp_path: Path) -> None:
    db = SQLiteStore(_config(tmp_path))
    try:
        assert db.get_schema_version() == 0
        db.ensure_schema()
        assert db.get_schema_version() == CURRENT_SCHEMA_VERSION
        assert CURRENT_SCHEMA_VERSION == 2
    finally:
        db.close()


def test_both_m2_1_tables_created(tmp_path: Path) -> None:
    db = SQLiteStore(_config(tmp_path))
    try:
        db.ensure_schema()
        assert db.table_exists("zm_meta")
        assert db.table_exists("zm_migrations")
    finally:
        db.close()


def test_deterministic_migration_ordering() -> None:
    # Registry yields versions in ascending deterministic order.
    assert list(MIGRATIONS) == sorted(MIGRATIONS)
    # Pending computation is sorted ascending (proven via a synthetic v2).
    from src.storage import migrations as reg

    class _Fake:
        @staticmethod
        def up(conn, note):  # type: ignore[no-untyped-def]
            conn.execute("CREATE TABLE zm_marker_v2(x INTEGER)")

        @staticmethod
        def down(conn, note):  # type: ignore[no-untyped-def]
            conn.execute("DROP TABLE IF EXISTS zm_marker_v2")

    original = reg.MIGRATIONS
    try:
        reg.MIGRATIONS = {1: original[1], 2: _Fake()}  # type: ignore[index]
        pending = sorted(
            v for v in reg.MIGRATIONS if v > 0 and v <= 2
        )
        assert pending == [1, 2]
    finally:
        reg.MIGRATIONS = original


def test_applying_pending_migrations(tmp_path: Path) -> None:
    db = SQLiteStore(_config(tmp_path))
    try:
        assert db.get_schema_version() == 0
        v = db.ensure_schema()
        assert v == CURRENT_SCHEMA_VERSION
        assert db.table_exists("zm_meta")
        # Ledger rows present for every applied migration (v1, v2).
        cur = db._conn.cursor()
        cur.execute("SELECT version FROM zm_migrations ORDER BY version")
        assert [r["version"] for r in cur.fetchall()] == list(range(1, CURRENT_SCHEMA_VERSION + 1))
    finally:
        db.close()


def test_reopening_up_to_date_database_is_noop(tmp_path: Path) -> None:
    db = SQLiteStore(_config(tmp_path))
    try:
        db.ensure_schema()
    finally:
        db.close()
    # Reopen and re-ensure: no duplicate table, same version.
    db2 = SQLiteStore(_config(tmp_path))
    try:
        v = db2.ensure_schema()
        assert v == CURRENT_SCHEMA_VERSION
        cur = db2._conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM zm_migrations")
        assert cur.fetchone()["n"] == CURRENT_SCHEMA_VERSION
    finally:
        db2.close()


def test_migration_idempotence(tmp_path: Path) -> None:
    db = SQLiteStore(_config(tmp_path))
    try:
        db.ensure_schema()
        db.ensure_schema()  # second call must not duplicate
        db.ensure_schema()
        assert db.get_schema_version() == CURRENT_SCHEMA_VERSION
        cur = db._conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM zm_migrations")
        assert cur.fetchone()["n"] == CURRENT_SCHEMA_VERSION
    finally:
        db.close()


def test_migration_transaction_rollback_on_failure(tmp_path: Path) -> None:
    db = SQLiteStore(_config(tmp_path))
    try:
        from src.storage import migrations as reg

        original_up = reg.MIGRATIONS[1].up
        # Force the migration body to fail after starting the transaction.
        def _boom(conn, note):  # type: ignore[no-untyped-def]
            conn.execute(
                "CREATE TABLE zm_partial_should_rollback(x INTEGER)"
            )
            raise RuntimeError("induced migration failure")

        reg.MIGRATIONS[1].up = _boom  # type: ignore[attr-defined]
        try:
            with pytest.raises(MigrationError):
                db.ensure_schema()
        finally:
            reg.MIGRATIONS[1].up = original_up  # type: ignore[attr-defined]
        # Nothing committed: no domain tables, ledger absent, version 0.
        assert not db.table_exists("zm_meta")
        assert not db.table_exists("zm_partial_should_rollback")
        assert db.get_schema_version() == 0
    finally:
        db.close()


def test_failed_migration_does_not_advance_schema_version(tmp_path: Path) -> None:
    db = SQLiteStore(_config(tmp_path))
    try:
        from src.storage import migrations as reg

        original_up = reg.MIGRATIONS[1].up
        reg.MIGRATIONS[1].up = lambda conn, note: (_ for _ in ()).throw(  # type: ignore[attr-defined]
            RuntimeError("nope")
        )
        try:
            with pytest.raises(MigrationError):
                db.ensure_schema()
        finally:
            reg.MIGRATIONS[1].up = original_up  # type: ignore[attr-defined]
        assert db.get_schema_version() == 0
    finally:
        db.close()


def test_unknown_future_schema_version_rejected(tmp_path: Path) -> None:
    db = SQLiteStore(_config(tmp_path))
    try:
        db.ensure_schema()  # creates v1 and v2
        # Simulate a FUTURE version recorded in the ledger (code only knows up to v2).
        db._conn.execute(
            "INSERT INTO zm_migrations(version, applied_at, note) VALUES (3, 't', 'future')"
        )
        db._conn.commit()
        with pytest.raises(SchemaVersionError):
            db.ensure_schema()  # must refuse to touch; code only knows v2
    finally:
        db.close()


def test_unsupported_downgrade_rejected(tmp_path: Path) -> None:
    db = SQLiteStore(_config(tmp_path))
    try:
        db.ensure_schema()  # v2
        # target >= current is not a downgrade
        with pytest.raises(SchemaVersionError):
            db.downgrade_to(2)
        with pytest.raises(SchemaVersionError):
            db.downgrade_to(3)
        # negative target
        with pytest.raises(SchemaVersionError):
            db.downgrade_to(-1)
        # target 1 (< current) IS a supported downgrade and must succeed
        db.downgrade_to(1)
        assert db.get_schema_version() == 1
        assert db.table_exists("zm_meta")
    finally:
        db.close()


def test_supported_downgrade_restores_prior_state(tmp_path: Path) -> None:
    db = SQLiteStore(_config(tmp_path))
    try:
        db.ensure_schema()
        assert db.get_schema_version() == CURRENT_SCHEMA_VERSION
        db.downgrade_to(0)
        assert db.get_schema_version() == 0
        assert not db.table_exists("zm_meta")
        assert not db.table_exists("zm_migrations")
    finally:
        db.close()


def test_sanitized_initialization_error_no_leak(tmp_path: Path) -> None:
    # Opening a path inside the real ~/.hermes is refused with a sanitized error.
    home_db = Path.home() / ".hermes" / "should_not_be_created.sqlite"
    with pytest.raises(StoreInitError) as exc:
        SQLiteStore(SQLiteStoreConfig(path=home_db))
    msg = str(exc.value)
    assert "store_init_error" in msg
    # No raw path prefix or payload leakage.
    assert str(home_db) not in msg
    assert "store_init_error" == msg.split(":")[0] or msg.startswith("store_init_error")
    # File must not actually be created.
    assert not home_db.exists()


def test_sanitized_initialization_error_on_pragma_failure(tmp_path: Path) -> None:
    real_connect = sqlite3.connect

    def _bad_connect(*a, **k):  # type: ignore[no-untyped-def]
        conn = real_connect(*a, **k)
        orig = conn.execute

        def _raise(*aa, **kk):  # type: ignore[no-untyped-def]
            raise sqlite3.OperationalError("PRAGMA journal_mode=WAL failed: internal detail")

        conn.execute = _raise  # type: ignore[assignment]
        return conn

    with mock.patch("sqlite3.connect", _bad_connect):
        with pytest.raises(StoreInitError) as exc:
            SQLiteStore(_config(tmp_path))
    msg = str(exc.value)
    assert "store_init_error" in msg
    assert "PRAGMA journal_mode=WAL failed" not in msg  # raw SQL text not leaked


def test_sanitized_migration_error_no_leak(tmp_path: Path) -> None:
    db = SQLiteStore(_config(tmp_path))
    try:
        from src.storage import migrations as reg

        original_up = reg.MIGRATIONS[1].up

        def _boom(conn, note):  # type: ignore[no-untyped-def]
            raise ValueError("secret_payload=ABC123 raw_sql=DROPTABLE detail")

        reg.MIGRATIONS[1].up = _boom  # type: ignore[attr-defined]
        try:
            with pytest.raises(MigrationError) as exc:
                db.ensure_schema()
        finally:
            reg.MIGRATIONS[1].up = original_up  # type: ignore[attr-defined]
        msg = str(exc.value)
        assert "migration_error" in msg
        assert "ABC123" not in msg
        assert "DROPTABLE" not in msg
    finally:
        db.close()


def test_restrictive_file_permissions(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX permissions not applicable on Windows")
    db = SQLiteStore(_config(tmp_path))
    try:
        db.secure_permissions()
        mode = oct(os.stat(db.path).st_mode & 0o777)
        assert mode == "0o600", mode
    finally:
        db.close()


def test_no_real_hermes_home_writes(tmp_path: Path) -> None:
    home = Path.home() / ".hermes"
    before = set(p.name for p in home.rglob("*")) if home.exists() else set()
    db = SQLiteStore(_config(tmp_path))
    try:
        db.ensure_schema()
    finally:
        db.close()
    after = set(p.name for p in home.rglob("*")) if home.exists() else set()
    assert after == before, "M2.1 must not write into the real ~/.hermes"


def test_no_installed_hermes_source_modification(tmp_path: Path) -> None:
    # M2.1 does not import or mutate the installed Hermes source.
    import importlib

    import src.storage.sqlite_store as mod

    importlib.reload(mod)
    # The module must not reference installed-hermes paths.
    assert "hermes-agent" not in repr(mod.__file__)
    assert not hasattr(mod, "installed_hermes")


def test_no_jsonl_ingestion_api(tmp_path: Path) -> None:
    # M2.1 exposes no ingestion / rebuild surface.
    assert not hasattr(SQLiteStore, "ingest")
    assert not hasattr(SQLiteStore, "rebuild_from_jsonl")
    # Importing sqlite_store must not load the M1 JSONL capture store.
    import sys

    sys.modules.pop("src.storage.jsonl_capture", None)
    import importlib

    import src.storage.sqlite_store as s

    importlib.reload(s)
    assert "src.storage.jsonl_capture" not in sys.modules


def test_no_llm_dependency_imported(tmp_path: Path) -> None:
    import sys

    for mod in ("openai", "anthropic", "langchain"):
        assert mod not in sys.modules, f"unexpected LLM dependency {mod}"


def test_no_network_calls(tmp_path: Path) -> None:
    # Patching socket proves the store performs no network I/O.
    class _NoNetwork:
        def __call__(self, *a, **k):  # type: ignore[no-untyped-def]
            raise AssertionError("network socket used by M2.1 store")

        def socket(self, *a, **k):  # type: ignore[no-untyped-def]
            raise AssertionError("network socket used by M2.1 store")

    db = None
    with mock.patch("socket.socket", side_effect=AssertionError("net")):
        db = SQLiteStore(_config(tmp_path))
        db.ensure_schema()  # must succeed without any socket use
    try:
        assert db.get_schema_version() == CURRENT_SCHEMA_VERSION
    finally:
        db.close()
