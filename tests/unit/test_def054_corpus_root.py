"""DEF-054 - default corpus root under the data root, honoured by setup,
upgrade, backup/restore and doctor; upgrade must not silently drop the corpus.

Design: docs/design/SHARED-MEMORY-RUNTIME.md section 6 item 6.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path

import pytest

from src.corpus.blob_store import CorpusBlobStore
from src.corpus.registry import REGISTRY_FILENAME, CorpusSourceRegistry
from zero_mem import paths
from zero_mem.backup import create_backup, restore_backup, verify_backup
from zero_mem.commands_doctor import collect
from zero_mem.commands_setup import run as setup
from zero_mem.upgrade import UpgradeError, check, upgrade


def _env(monkeypatch: pytest.MonkeyPatch, root: Path, *, corpus: Path | None = None) -> None:
    monkeypatch.setenv("HOME", str(root / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(root / "xdg-data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root / "xdg-config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(root / "xdg-state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(root / "xdg-cache"))
    monkeypatch.delenv("ZERO_MEM_DATA_ROOT", raising=False)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    if corpus is None:
        monkeypatch.delenv("ZERO_MEM_CORPUS_ROOT", raising=False)
    else:
        monkeypatch.setenv("ZERO_MEM_CORPUS_ROOT", str(corpus))


def _register(root: Path, text: bytes = b"always run pytest before every commit\n",
              *, ref: str = "mem://persona/one", kind: str = "txt"):
    registry = CorpusSourceRegistry(root=root)
    return registry.register_source_with_blob(
        content=text,
        external_ref=ref,
        kind=kind,
        profile_id="agent-a",
        knowledge_space_id="ks-shared",
        blob_store=CorpusBlobStore(root=root),
    )


def _files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _corpus_units() -> int:
    import sqlite3

    conn = sqlite3.connect(f"file:{paths.derived_db().as_posix()}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT COUNT(*) FROM zm_corpus_units").fetchone()[0]
    finally:
        conn.close()


# --- paths.corpus_root() ----------------------------------------------------

def test_corpus_root_defaults_under_data_root(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    assert paths.corpus_root() == paths.data_root() / "data" / "corpus"


def test_corpus_root_follows_data_root_override(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("ZERO_MEM_DATA_ROOT", str(tmp_path / "alt-root"))
    assert paths.corpus_root() == tmp_path / "alt-root" / "data" / "corpus"


def test_corpus_root_env_override_wins(monkeypatch, tmp_path):
    explicit = tmp_path / "elsewhere" / "corpus"
    _env(monkeypatch, tmp_path, corpus=explicit)
    assert paths.corpus_root() == explicit


def test_corpus_root_env_must_be_absolute(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("ZERO_MEM_CORPUS_ROOT", "relative/corpus")
    with pytest.raises(paths.ConfigurationError):
        paths.corpus_root()


def test_registry_filename_constant_in_sync():
    assert paths.CORPUS_REGISTRY_FILENAME == REGISTRY_FILENAME


# --- setup -------------------------------------------------------------------

def test_setup_creates_private_default_corpus_root(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    assert setup() == 0
    root = paths.corpus_root()
    assert root.is_dir()
    assert (root / REGISTRY_FILENAME).is_file()
    assert (root / "blobs").is_dir()
    if os.name != "nt":
        assert stat.S_IMODE(root.stat().st_mode) == 0o700
        assert stat.S_IMODE((root / REGISTRY_FILENAME).stat().st_mode) == 0o600


def test_setup_creates_corpus_root_at_env_override(monkeypatch, tmp_path):
    explicit = tmp_path / "elsewhere" / "corpus"
    _env(monkeypatch, tmp_path, corpus=explicit)
    assert setup() == 0
    assert (explicit / REGISTRY_FILENAME).is_file()
    assert not (paths.data_root() / "data" / "corpus").exists()


def test_setup_is_idempotent_and_keeps_registry_bytes(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    setup()
    _register(paths.corpus_root())
    before = _files(paths.corpus_root())
    assert setup() == 0
    assert _files(paths.corpus_root()) == before


# --- upgrade -----------------------------------------------------------------

def test_upgrade_rebuilds_units_from_default_corpus_root(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    setup()
    _register(paths.corpus_root())
    before = _files(paths.corpus_root())

    result = upgrade()

    assert result["status"] == "SUCCESS"
    assert _corpus_units() >= 1
    assert result["corpus"]["sources"] == 1
    assert result["corpus"]["units"] >= 1
    assert _files(paths.corpus_root()) == before  # canonical corpus untouched


def test_upgrade_fails_loudly_when_sources_yield_zero_units(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    setup()
    # No adapter supports this kind -> a registry source with no extractable units.
    _register(paths.corpus_root(), kind="t3-no-such-adapter")
    active_before = paths.derived_db().read_bytes()

    with pytest.raises(UpgradeError) as exc_info:
        upgrade()

    assert exc_info.value.code == "CORPUS_PROJECTION_EMPTY"
    assert paths.derived_db().read_bytes() == active_before  # active state untouched


def test_upgrade_refuses_to_drop_existing_corpus_units(monkeypatch, tmp_path):
    """The DEF-054 scenario: corpus was projected with an explicit root, then
    upgrade runs without it and would activate a DB with zero corpus units."""
    explicit = tmp_path / "custom-corpus"
    _env(monkeypatch, tmp_path, corpus=explicit)
    setup()
    _register(explicit)
    assert upgrade()["status"] == "SUCCESS"
    assert _corpus_units() >= 1
    active_before = paths.derived_db().read_bytes()

    monkeypatch.delenv("ZERO_MEM_CORPUS_ROOT")  # root no longer resolved
    with pytest.raises(UpgradeError) as exc_info:
        upgrade()

    assert exc_info.value.code == "CORPUS_ROOT_UNRESOLVED"
    assert paths.derived_db().read_bytes() == active_before
    assert _corpus_units() >= 1


def test_upgrade_without_any_corpus_dir_still_works(monkeypatch, tmp_path):
    """Installs that predate the default corpus dir keep upgrading."""
    _env(monkeypatch, tmp_path)
    setup()
    shutil.rmtree(paths.corpus_root())
    assert check()["status"] == "READY"
    assert upgrade()["status"] == "SUCCESS"
    assert not paths.corpus_root().exists()  # upgrade does not create it


def test_upgrade_check_ready_with_default_corpus(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    setup()
    _register(paths.corpus_root())
    before = _files(paths.corpus_root())
    assert check()["status"] == "READY"
    assert _files(paths.corpus_root()) == before


# --- backup / restore ---------------------------------------------------------

def test_backup_includes_default_corpus_and_restore_round_trips(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    setup()
    record = _register(paths.corpus_root())
    upgrade()
    backup = create_backup(tmp_path / "bk")

    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    names = {entry["path"] for entry in manifest["files"]}
    assert f"canonical/corpus/{REGISTRY_FILENAME}" in names
    assert f"canonical/corpus/blobs/{record.blob_ref[:2]}/{record.blob_ref}" in names
    assert verify_backup(backup)["has_corpus"] is True

    # Lose the live corpus entirely, then restore from the backup alone.
    shutil.rmtree(paths.corpus_root())
    result = restore_backup(backup, yes=True)

    assert result["status"] == "SUCCESS"
    restored = CorpusSourceRegistry(root=paths.corpus_root())
    assert [r.source_id for r in restored.all_records()] == [record.source_id]
    assert CorpusBlobStore(root=paths.corpus_root()).get(record.blob_ref) == b"always run pytest before every commit\n"
    assert _corpus_units() >= 1  # derived state rebuilt from the restored corpus
    assert collect()["overall"] == "READY"


def test_restore_into_other_data_root_carries_default_corpus(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    setup()
    record = _register(paths.corpus_root())
    backup = create_backup(tmp_path / "bk")
    target = tmp_path / "other-root"

    restore_backup(backup, yes=True, target_data_root=target)

    restored = CorpusSourceRegistry(root=target / "data" / "corpus")
    assert [r.source_id for r in restored.all_records()] == [record.source_id]


def test_restore_of_backup_without_corpus_preserves_live_default_corpus(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    setup()
    shutil.rmtree(paths.corpus_root())  # emulate a pre-DEF-054 install
    backup = create_backup(tmp_path / "bk-no-corpus")
    assert verify_backup(backup)["has_corpus"] is False

    paths.ensure_corpus_root()
    record = _register(paths.corpus_root())
    live_before = _files(paths.corpus_root())

    restore_backup(backup, yes=True)

    assert _files(paths.corpus_root()) == live_before
    assert CorpusSourceRegistry(root=paths.corpus_root()).get_by_source_id(record.source_id) is not None


# --- doctor ------------------------------------------------------------------

def _corpus_check() -> dict:
    return next(c for c in collect()["checks"] if c["id"] == "corpus")


def test_doctor_corpus_empty_after_setup_is_warn_without_paths(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    setup()
    check_ = _corpus_check()
    assert check_["status"] == "WARN"
    assert str(tmp_path) not in check_["message"]
    assert collect()["overall"] == "READY"


def test_doctor_warns_when_registry_has_sources_but_no_units(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    setup()
    _register(paths.corpus_root())
    check_ = _corpus_check()
    assert check_["status"] == "WARN"
    assert "upgrade" in check_["message"]
    assert str(tmp_path) not in check_["message"]


def test_doctor_corpus_pass_after_upgrade(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    setup()
    _register(paths.corpus_root())
    upgrade()
    check_ = _corpus_check()
    assert check_["status"] == "PASS"
    assert "1 source" in check_["message"]
    assert str(tmp_path) not in check_["message"]


def test_doctor_corpus_malformed_registry_fails(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    setup()
    (paths.corpus_root() / REGISTRY_FILENAME).write_bytes(b'{"source_id": "x"')  # truncated line
    assert _corpus_check()["status"] == "FAIL"
    assert collect()["overall"] == "NOT_READY"
