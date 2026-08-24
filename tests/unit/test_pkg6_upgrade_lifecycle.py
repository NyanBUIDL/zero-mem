"""PKG-6 clean-machine lifecycle and safe derived upgrade regressions."""
from __future__ import annotations

import hashlib
import json
import re
import os
import sqlite3
from pathlib import Path

import pytest

import zero_mem.upgrade as upgrade_module
from src.corpus.blob_store import CorpusBlobStore
from src.corpus.registry import CorpusSourceRegistry
from src.storage.ingest import ingest_file
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from zero_mem.backup import create_backup, verify_backup
from zero_mem.commands_doctor import collect
from zero_mem.commands_setup import run as setup
from zero_mem.paths import config_path, data_root, derived_db, memory_stream
from zero_mem.upgrade import (
    CORRUPT_STATE,
    FUTURE_VERSION_UNSUPPORTED,
    NO_MIGRATION_REQUIRED,
    UpgradeError,
    check,
    upgrade,
)


TS = "2026-08-13T00:00:00Z"


def _env(monkeypatch: pytest.MonkeyPatch, root: Path) -> Path:
    corpus = root / "corpus root with spaces"
    monkeypatch.setenv("HOME", str(root / "home with spaces"))
    monkeypatch.setenv("XDG_DATA_HOME", str(root / "data with spaces"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root / "config with spaces"))
    monkeypatch.setenv("XDG_STATE_HOME", str(root / "state with spaces"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(root / "cache with spaces"))
    monkeypatch.setenv("ZERO_MEM_CORPUS_ROOT", str(corpus))
    monkeypatch.delenv("PYTHONPATH", raising=False)
    return corpus


def _event() -> dict:
    text = "PKG-6 synthetic canonical memory"
    return {
        "event_id": "pkg6-event",
        "trace_id": "pkg6-trace",
        "event_type": "user_statement",
        "source": "pre_tool_call",
        "schema_version": 1,
        "created_at": TS,
        "observed_at": TS,
        "sequence": 0,
        "lifecycle_status": "observed",
        "verification_status": "none",
        "confidence": "medium",
        "sensitivity": "internal",
        "retention": "persistent",
        "sanitized_content_hash": hashlib.sha256(text.encode()).hexdigest(),
        "sanitized_content": {"text": text},
        "redaction_audit": [],
        "profile_id": "profile-pkg6",
        "project_id": "project-pkg6",
    }


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


_UTC_SECOND_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _logical_snapshot(path: Path) -> dict[str, list[tuple]]:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'zm_%' ORDER BY name"
            )
            if row[0] != "zm_migrations" and not row[0].endswith("_fts") and not row[0].endswith("_fts_data")
            and not row[0].endswith("_fts_idx") and not row[0].endswith("_fts_docsize")
            and not row[0].endswith("_fts_config")
        ]
        # R124-10: the rebuild re-stamps bookkeeping *_at columns with the wall
        # clock (second granularity); on a slow runner the second upgrade can
        # cross a second boundary and differ only in those cells. Normalize
        # UTC-second timestamp cells so the assertion proves content/identity
        # equality, not wall-clock drift.
        def _norm(row):
            return tuple(
                "TIMESTAMP" if isinstance(value, str) and _UTC_SECOND_TS.match(value) else value
                for value in row
            )

        return {
            table: [_norm(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()]
            for table in tables
        }
    finally:
        conn.close()


def _fixture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, bytes]:
    corpus = _env(monkeypatch, tmp_path)
    setup()
    event = _event()
    memory_stream().write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")
    store = SQLiteStore(SQLiteStoreConfig(derived_db()))
    try:
        ingest_file(store, memory_stream())
    finally:
        store.close()
    payload = b"PKG-6 synthetic authoritative artifact payload"
    registry = CorpusSourceRegistry(root=corpus)
    registry.register_source_with_blob(
        content=payload,
        external_ref="pkg6/logical-source",
        kind="text",
        profile_id="profile-pkg6",
        project_id="project-pkg6",
        blob_store=CorpusBlobStore(root=corpus),
    )
    return corpus, payload


def test_upgrade_check_is_read_only_and_classifies_current_state(monkeypatch, tmp_path: Path) -> None:
    corpus, payload = _fixture(monkeypatch, tmp_path)
    before_data = _files(data_root())
    before_config = _files(config_path().parent)
    before_corpus = _files(corpus)

    result = check()

    assert result["status"] == "READY"
    assert result["compatibility"] == NO_MIGRATION_REQUIRED
    assert result["migration_required"] is False
    assert result["schema_version"] == 12
    assert result["package_version"] == "1.4.1"
    assert _files(data_root()) == before_data
    assert _files(config_path().parent) == before_config
    assert _files(corpus) == before_corpus
    assert CorpusBlobStore(root=corpus).get(hashlib.sha256(payload).hexdigest()) == payload


def test_setup_and_same_version_reinstall_preserve_authoritative_state(monkeypatch, tmp_path: Path) -> None:
    corpus, payload = _fixture(monkeypatch, tmp_path)
    # Model a descriptor created by an earlier compatible application version.
    descriptor = json.loads(config_path().read_text(encoding="utf-8"))
    descriptor["version"] = "0.9.0"
    config_path().write_text(json.dumps(descriptor, sort_keys=True) + "\n", encoding="utf-8")
    before_data = _files(data_root())
    before_corpus = _files(corpus)

    setup()

    assert _files(data_root()) == before_data
    assert _files(corpus) == before_corpus
    assert json.loads(config_path().read_text(encoding="utf-8"))["version"] == "0.9.0"
    assert CorpusBlobStore(root=corpus).get(hashlib.sha256(payload).hexdigest()) == payload
    assert collect()["overall"] == "READY"


def test_upgrade_rebuilds_derived_state_and_preserves_canonical_backup_and_artifact(monkeypatch, tmp_path: Path) -> None:
    corpus, payload = _fixture(monkeypatch, tmp_path)
    backup = create_backup(tmp_path / "backup with spaces")
    before_memory = memory_stream().read_bytes()
    before_corpus = _files(corpus)

    first = upgrade()
    before_logical = _logical_snapshot(derived_db())
    second = upgrade()

    assert first["status"] == "SUCCESS"
    assert second["status"] == "SUCCESS"
    assert _logical_snapshot(derived_db()) == before_logical
    assert memory_stream().read_bytes() == before_memory
    assert _files(corpus) == before_corpus
    assert CorpusBlobStore(root=corpus).get(hashlib.sha256(payload).hexdigest()) == payload
    assert verify_backup(backup)["status"] == "VALID"
    assert collect()["overall"] == "READY"


def test_rebuild_failure_before_activation_preserves_active_state(monkeypatch, tmp_path: Path) -> None:
    _fixture(monkeypatch, tmp_path)
    upgrade()
    before = derived_db().read_bytes()
    before_memory = memory_stream().read_bytes()

    def fail_rebuild(*_args, **_kwargs):
        raise UpgradeError("REBUILD_FAILED")

    monkeypatch.setattr(upgrade_module, "_rebuild_derived", fail_rebuild)
    with pytest.raises(UpgradeError) as exc_info:
        upgrade()

    assert exc_info.value.code == "REBUILD_FAILED"
    assert derived_db().read_bytes() == before
    assert memory_stream().read_bytes() == before_memory
    assert collect()["overall"] == "READY"


def test_future_schema_is_refused_without_active_mutation(monkeypatch, tmp_path: Path) -> None:
    _fixture(monkeypatch, tmp_path)
    before = derived_db().read_bytes()
    conn = sqlite3.connect(derived_db())
    try:
        conn.execute("UPDATE zm_migrations SET version=999 WHERE version=10")
        conn.commit()
    finally:
        conn.close()
    future_state = derived_db().read_bytes()

    result = check()
    assert result["status"] == "REFUSED"
    assert result["compatibility"] == FUTURE_VERSION_UNSUPPORTED
    with pytest.raises(UpgradeError) as exc_info:
        upgrade()
    assert exc_info.value.code == "FUTURE_VERSION_UNSUPPORTED"
    assert derived_db().read_bytes() == future_state
    assert before != future_state


def test_corrupt_canonical_state_is_refused_without_derived_mutation(monkeypatch, tmp_path: Path) -> None:
    _fixture(monkeypatch, tmp_path)
    before = derived_db().read_bytes()
    memory_stream().write_bytes(b'{"event_id":"unterminated"}')

    result = check()

    assert result["compatibility"] == CORRUPT_STATE
    assert result["status"] == "REFUSED"
    assert derived_db().read_bytes() == before
