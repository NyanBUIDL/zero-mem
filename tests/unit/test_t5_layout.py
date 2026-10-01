"""T5 - storage layout resolution + first-run setup shared by Memory and the provisioning commands."""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from zero_mem import paths
from zero_mem.memory_layout import Layout, LayoutError


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def test_explicit_root_uses_the_standard_relative_layout(tmp_path):
    root = tmp_path / "zm"
    lay = Layout.resolve(root)
    assert lay.data_root == root and lay.explicit is True
    assert lay.memory_stream == root / paths.MEMORY_STREAM_RELATIVE
    assert lay.derived_db == root / paths.DERIVED_DB_RELATIVE
    assert lay.corpus_root == root / paths.CORPUS_RELATIVE


def test_explicit_root_ignores_the_corpus_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("ZERO_MEM_CORPUS_ROOT", str(tmp_path / "elsewhere"))
    lay = Layout.resolve(tmp_path / "zm")
    assert lay.corpus_root == tmp_path / "zm" / paths.CORPUS_RELATIVE


def test_explicit_corpus_root_wins(tmp_path):
    lay = Layout.resolve(tmp_path / "zm", corpus_root=tmp_path / "corp")
    assert lay.corpus_root == tmp_path / "corp"


def test_relative_roots_are_rejected(tmp_path):
    with pytest.raises(LayoutError):
        Layout.resolve(Path("relative/dir"))
    with pytest.raises(LayoutError):
        Layout.resolve(tmp_path / "zm", corpus_root=Path("rel"))


def test_default_resolution_follows_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ZERO_MEM_DATA_ROOT", str(tmp_path / "envroot"))
    monkeypatch.delenv("ZERO_MEM_CORPUS_ROOT", raising=False)
    lay = Layout.resolve(None)
    assert lay.explicit is False
    assert lay.data_root == tmp_path / "envroot"
    assert lay.memory_stream == paths.memory_stream()
    assert lay.derived_db == paths.derived_db()
    assert lay.corpus_root == paths.corpus_root()


def test_ensure_creates_private_dirs_stream_corpus_and_schema(tmp_path):
    lay = Layout.resolve(tmp_path / "zm")
    lay.ensure()
    assert _mode(lay.data_root) == 0o700
    assert lay.memory_stream.is_file() and _mode(lay.memory_stream) == 0o600
    assert _mode(lay.derived_db.parent) == 0o700
    assert (lay.corpus_root / "corpus_sources.jsonl").is_file()
    assert (lay.corpus_root / "blobs").is_dir() and _mode(lay.corpus_root) == 0o700
    import sqlite3
    conn = sqlite3.connect(lay.derived_db)
    try:
        assert conn.execute("SELECT MAX(version) FROM zm_migrations").fetchone()[0] >= 13
    finally:
        conn.close()


def test_ensure_is_idempotent_and_keeps_existing_bytes(tmp_path):
    lay = Layout.resolve(tmp_path / "zm")
    lay.ensure()
    lay.memory_stream.write_text('{"event_id":"x"}\n')
    registry = lay.corpus_root / "corpus_sources.jsonl"
    before = (lay.memory_stream.read_bytes(), registry.read_bytes())
    lay.ensure()
    assert (lay.memory_stream.read_bytes(), registry.read_bytes()) == before


def test_ensure_rejects_a_symlinked_root(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(LayoutError):
        Layout.resolve(link / "zm").ensure()


def test_default_ensure_runs_the_standard_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("ZERO_MEM_DATA_ROOT", str(tmp_path / "d"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "ca"))
    monkeypatch.delenv("ZERO_MEM_CORPUS_ROOT", raising=False)
    Layout.resolve(None).ensure()
    assert (tmp_path / "cfg" / "zero-mem" / "config.json").is_file()  # what `zero-mem setup` writes
    assert paths.derived_db().is_file()


def test_explicit_ensure_does_not_touch_the_user_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    Layout.resolve(tmp_path / "zm").ensure()
    assert not (tmp_path / "cfg").exists()
