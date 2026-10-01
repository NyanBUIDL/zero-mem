"""DEF-065 - derived DB file mode 0600.  DEF-066 - vestigial corpus-store-path
config/doctor advice must never block readiness, upgrade or restore.
"""
from __future__ import annotations

import json
import os
import sqlite3
import stat
from pathlib import Path

import pytest

from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from zero_mem import paths
from zero_mem.backup import create_backup, restore_backup
from zero_mem.commands_doctor import collect
from zero_mem.commands_setup import run as setup
from zero_mem.upgrade import upgrade

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")


def _env(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setenv("HOME", str(root / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(root / "xdg-data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root / "xdg-config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(root / "xdg-state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(root / "xdg-cache"))
    monkeypatch.delenv("ZERO_MEM_DATA_ROOT", raising=False)
    monkeypatch.delenv("ZERO_MEM_CORPUS_ROOT", raising=False)
    monkeypatch.delenv("ZM_M6_CORPUS_STORE_PATH", raising=False)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _sidecar_files(db: Path) -> list[Path]:
    return [p for p in (Path(str(db) + "-wal"), Path(str(db) + "-shm")) if p.exists()]


# --- DEF-065 -------------------------------------------------------------------

@posix_only
def test_new_store_file_is_private(tmp_path):
    db = tmp_path / "d" / "memory.sqlite3"
    store = SQLiteStore(SQLiteStoreConfig(path=db))
    try:
        store.ensure_schema()
        store._conn.execute("CREATE TABLE IF NOT EXISTS t3_probe(x)")
        store._conn.execute("INSERT INTO t3_probe VALUES (1)")
        store._conn.commit()
        assert _mode(db) == 0o600
        for sidecar in _sidecar_files(db):
            assert _mode(sidecar) == 0o600
    finally:
        store.close()


@posix_only
def test_existing_world_readable_store_is_tightened_on_open(tmp_path):
    db = tmp_path / "d" / "memory.sqlite3"
    store = SQLiteStore(SQLiteStoreConfig(path=db))
    store.ensure_schema()
    store.close()
    os.chmod(db, 0o644)

    reopened = SQLiteStore(SQLiteStoreConfig(path=db))
    try:
        assert _mode(db) == 0o600
    finally:
        reopened.close()


@posix_only
def test_setup_creates_private_derived_db(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    setup()
    assert _mode(paths.derived_db()) == 0o600
    assert _mode(paths.derived_db().parent) == 0o700


@posix_only
def test_upgrade_activates_private_derived_db(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    setup()
    os.chmod(paths.derived_db(), 0o644)
    assert upgrade()["status"] == "SUCCESS"
    assert _mode(paths.derived_db()) == 0o600


@posix_only
def test_restore_rebuilds_private_derived_db(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    setup()
    backup = create_backup(tmp_path / "bk")
    restore_backup(backup, yes=True)
    assert _mode(paths.derived_db()) == 0o600


# --- DEF-066 -------------------------------------------------------------------

def _doctor_check(check_id: str) -> dict:
    return next(c for c in collect()["checks"] if c["id"] == check_id)


def _write_stale_corpus_store_path(tmp_path: Path) -> str:
    """Persist a configured path, then remove the file so only a stale value stays."""
    from zero_mem import userconfig

    store = tmp_path / "legacy-corpus.sqlite"
    conn = sqlite3.connect(store)
    conn.execute("CREATE TABLE zm_corpus_units(unit_id TEXT)")
    conn.execute("CREATE TABLE zm_corpus_sources(source_id TEXT)")
    conn.commit()
    conn.close()
    userconfig.set_corpus_store_path(str(store))
    store.unlink()
    return str(store)


def test_doctor_unconfigured_has_no_corpus_store_advice(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    setup()
    check = _doctor_check("corpus_authorization")
    assert check["status"] == "PASS"
    assert "corpus-store-path" not in check["message"]
    assert "config set" not in check["message"]
    assert "main derived store" in check["message"]


def test_doctor_stale_corpus_store_path_warns_without_prescribing_it(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    setup()
    _write_stale_corpus_store_path(tmp_path)

    check = _doctor_check("corpus_authorization")

    assert check["status"] == "WARN"
    assert "config set" not in check["message"]
    assert "config unset corpus-store-path" in check["message"]
    assert collect()["overall"] == "READY"  # non-fatal


def test_doctor_stale_env_corpus_store_path_is_non_fatal(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    setup()
    monkeypatch.setenv("ZM_M6_CORPUS_STORE_PATH", str(tmp_path / "nowhere.sqlite"))
    check = _doctor_check("corpus_authorization")
    assert check["status"] == "WARN"
    assert "(env)" in check["message"]
    assert collect()["overall"] == "READY"


def test_upgrade_is_not_blocked_by_a_stale_corpus_store_path(monkeypatch, tmp_path):
    """Previously the stale value made the doctor FAIL, which rolled the upgrade back."""
    _env(monkeypatch, tmp_path)
    setup()
    _write_stale_corpus_store_path(tmp_path)
    result = upgrade()
    assert result["status"] == "SUCCESS"
    assert result["doctor_readiness"] == "READY"


def test_restore_is_not_blocked_by_a_stale_corpus_store_path(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    setup()
    backup = create_backup(tmp_path / "bk")
    _write_stale_corpus_store_path(tmp_path)
    assert restore_backup(backup, yes=True)["status"] == "SUCCESS"


def test_config_show_marks_the_key_as_vestigial(monkeypatch, tmp_path):
    from zero_mem.commands_config_grant import run_config_show

    _env(monkeypatch, tmp_path)
    shown = run_config_show()
    assert "vestigial" in shown["note"]
    assert "main derived store" in shown["note"]
    assert json.dumps(shown)  # still plain JSON-serializable


def test_descriptor_tolerates_the_legacy_key_but_still_rejects_unknown_fields(monkeypatch, tmp_path):
    """``zero-mem config set`` writes into the same config.json as the descriptor."""
    _env(monkeypatch, tmp_path)
    setup()
    descriptor = json.loads(paths.config_path().read_text(encoding="utf-8"))

    descriptor["corpus-store-path"] = "/somewhere/legacy.sqlite"
    paths.config_path().write_text(json.dumps(descriptor), encoding="utf-8")
    assert paths.load_config()["corpus-store-path"] == "/somewhere/legacy.sqlite"

    descriptor["corpus-store-path"] = 7  # wrong type is still rejected
    paths.config_path().write_text(json.dumps(descriptor), encoding="utf-8")
    with pytest.raises(paths.ConfigurationError):
        paths.load_config()

    del descriptor["corpus-store-path"]
    descriptor["surprise"] = True  # unknown fields are still rejected
    paths.config_path().write_text(json.dumps(descriptor), encoding="utf-8")
    with pytest.raises(paths.ConfigurationError):
        paths.load_config()


def test_config_set_through_the_cli_does_not_break_doctor(monkeypatch, tmp_path, capsys):
    from zero_mem import cli

    _env(monkeypatch, tmp_path)
    setup()
    store = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(store)
    conn.execute("CREATE TABLE zm_corpus_units(unit_id TEXT)")
    conn.commit()
    conn.close()
    assert cli.main(["config", "set", "corpus-store-path", str(store)]) == 0
    capsys.readouterr()
    assert collect()["overall"] == "READY"
