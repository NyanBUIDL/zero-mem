"""PKG-5 backup/restore lifecycle and fail-closed recovery regressions."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

import zero_mem.backup as backup_module
from src.corpus.blob_store import CorpusBlobStore
from src.corpus.registry import CorpusSourceRegistry
from src.storage.ingest import ingest_file
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from zero_mem.backup import BackupError, create_backup, restore_backup, verify_backup
from zero_mem.commands_doctor import collect
from zero_mem.commands_setup import run as setup
from zero_mem.paths import config_path, config_root, data_root, derived_db, memory_stream


TS = "2026-08-13T00:00:00Z"


def _env(monkeypatch: pytest.MonkeyPatch, root: Path, *, corpus: Path | None = None) -> None:
    monkeypatch.setenv("HOME", str(root / "home with spaces"))
    monkeypatch.setenv("XDG_DATA_HOME", str(root / "data with spaces"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root / "config with spaces"))
    monkeypatch.setenv("XDG_STATE_HOME", str(root / "state with spaces"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(root / "cache with spaces"))
    monkeypatch.delenv("PYTHONPATH", raising=False)
    if corpus is None:
        monkeypatch.delenv("ZERO_MEM_CORPUS_ROOT", raising=False)
    else:
        monkeypatch.setenv("ZERO_MEM_CORPUS_ROOT", str(corpus))


def _event(event_id: str, *, text: str, lifecycle: str = "observed") -> dict:
    return {
        "event_id": event_id,
        "trace_id": f"trace-{event_id}",
        "event_type": "user_statement",
        "source": "pre_tool_call",
        "schema_version": 1,
        "created_at": TS,
        "observed_at": TS,
        "sequence": 0,
        "lifecycle_status": lifecycle,
        "verification_status": "none",
        "confidence": "medium",
        "sensitivity": "internal",
        "retention": "persistent",
        "sanitized_content_hash": hashlib.sha256(text.encode()).hexdigest(),
        "sanitized_content": {"text": text},
        "redaction_audit": [],
        "profile_id": "profile-a",
        "project_id": "project-a",
    }


def _write_events(events: list[dict]) -> None:
    memory_stream().parent.mkdir(parents=True, exist_ok=True)
    memory_stream().write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )


def _fixture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, corpus: bool = False) -> Path:
    corpus_root = tmp_path / "corpus root with spaces" if corpus else None
    _env(monkeypatch, tmp_path, corpus=corpus_root)
    setup()
    _write_events([
        _event("event-user", text="user statement"),
        _event("event-claim", text="assistant claim"),
        _event("event-decision", text="decision", lifecycle="active"),
        _event("event-verify", text="verification"),
    ])
    store = SQLiteStore(SQLiteStoreConfig(derived_db()))
    try:
        ingest_file(store, memory_stream())
    finally:
        store.close()
    if corpus_root is not None:
        registry = CorpusSourceRegistry(root=corpus_root)
        blobs = CorpusBlobStore(root=corpus_root)
        registry.register_source_with_blob(
            content=b"synthetic canonical source",
            external_ref="logical-source",
            kind="text",
            profile_id="profile-a",
            project_id="project-a",
            blob_store=blobs,
        )
    return tmp_path


def test_backup_create_verify_and_restore_rebuilds_derived_state(monkeypatch, tmp_path: Path) -> None:
    _fixture(monkeypatch, tmp_path)
    before = memory_stream().read_bytes()
    backup = create_backup(tmp_path / "backup destination with spaces")
    assert verify_backup(backup)["status"] == "VALID"
    assert not (backup / "canonical/derived").exists()

    _write_events([_event("post-backup", text="mutated active state")])
    result = restore_backup(backup, yes=True)
    assert result["status"] == "SUCCESS"
    assert memory_stream().read_bytes() == before
    assert collect()["overall"] == "READY"

    rebuilt = SQLiteStore(SQLiteStoreConfig(derived_db()))
    try:
        assert rebuilt._conn.execute("SELECT COUNT(*) FROM zm_meta").fetchone()[0] == 4
        assert rebuilt._conn.execute("SELECT MAX(version) FROM zm_migrations").fetchone()[0] == 10
    finally:
        rebuilt.close()


def test_corpus_registry_and_blob_are_verified_and_restored(monkeypatch, tmp_path: Path) -> None:
    _fixture(monkeypatch, tmp_path, corpus=True)
    source_root = Path(os.environ["ZERO_MEM_CORPUS_ROOT"])
    backup = create_backup(tmp_path / "corpus backup")
    assert verify_backup(backup)["has_corpus"] is True
    target_corpus = tmp_path / "different corpus root with spaces"
    restore_backup(backup, yes=True, target_corpus_root=target_corpus)
    assert (target_corpus / "corpus_sources.jsonl").is_file()
    restored = CorpusSourceRegistry(root=target_corpus)
    assert [record.source_id for record in restored.all_records()] == [
        record.source_id for record in CorpusSourceRegistry(root=source_root).all_records()
    ]


def test_corpus_artifact_payload_round_trip_and_tamper_is_fail_closed(
    monkeypatch, tmp_path: Path
) -> None:
    _fixture(monkeypatch, tmp_path, corpus=True)
    active_data_root = data_root()
    active_corpus_root = Path(os.environ["ZERO_MEM_CORPUS_ROOT"])
    artifact_bytes = b"synthetic canonical source"
    original_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
    source_record = CorpusSourceRegistry(root=active_corpus_root).all_records()[0]
    digest = source_record.blob_ref
    assert digest is not None
    assert digest == original_sha256
    assert CorpusBlobStore(root=active_corpus_root).get(digest) == artifact_bytes

    backup = create_backup(tmp_path / "artifact payload backup")
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    artifact_path = f"canonical/corpus/blobs/{digest[:2]}/{digest}"
    artifact_entry = next(entry for entry in manifest["files"] if entry["path"] == artifact_path)
    assert artifact_entry["category"] == "canonical"
    assert artifact_entry["size"] == len(artifact_bytes)
    assert artifact_entry["sha256"] == original_sha256
    assert verify_backup(backup)["status"] == "VALID"

    # Mutate the active payload, then restore the same backup into different roots.
    active_blob = active_corpus_root / "blobs" / original_sha256[:2] / original_sha256
    active_blob.write_bytes(b"active mutation")
    target_data_root = tmp_path / "different data root"
    target_corpus_root = tmp_path / "different corpus root"
    restore_backup(
        backup,
        yes=True,
        target_data_root=target_data_root,
        target_corpus_root=target_corpus_root,
    )
    monkeypatch.setenv("ZERO_MEM_DATA_ROOT", str(target_data_root))
    monkeypatch.setenv("ZERO_MEM_CORPUS_ROOT", str(target_corpus_root))
    restored_record = CorpusSourceRegistry(root=target_corpus_root).get_by_source_id(
        source_record.source_id
    )
    assert restored_record is not None
    restored_digest = restored_record.blob_ref
    assert restored_digest is not None
    assert restored_digest == original_sha256
    restored_blob = CorpusBlobStore(root=target_corpus_root).get(restored_digest)
    assert restored_blob == artifact_bytes
    assert hashlib.sha256(restored_blob).hexdigest() == original_sha256
    assert memory_stream().read_bytes() == (backup / "canonical/memory/events-v1.jsonl").read_bytes()

    # A separately copied backup with only the artifact payload tampered must not
    # verify or replace the still-valid active state.
    monkeypatch.setenv("ZERO_MEM_DATA_ROOT", str(active_data_root))
    monkeypatch.setenv("ZERO_MEM_CORPUS_ROOT", str(active_corpus_root))
    active_memory_before = memory_stream().read_bytes()
    active_blob_before = active_blob.read_bytes()
    tampered = tmp_path / "tampered artifact backup"
    shutil.copytree(backup, tampered)
    tampered_blob = tampered / artifact_path
    tampered_bytes = bytearray(tampered_blob.read_bytes())
    tampered_bytes[0] ^= 1
    tampered_blob.write_bytes(bytes(tampered_bytes))
    with pytest.raises(BackupError) as exc_info:
        verify_backup(tampered)
    assert exc_info.value.code == "CHECKSUM_MISMATCH"
    with pytest.raises(BackupError) as exc_info:
        restore_backup(
            tampered,
            yes=True,
            target_data_root=active_data_root,
            target_corpus_root=active_corpus_root,
        )
    assert exc_info.value.code == "CHECKSUM_MISMATCH"
    assert memory_stream().read_bytes() == active_memory_before
    assert active_blob.read_bytes() == active_blob_before


@pytest.mark.parametrize("tamper", ["memory", "manifest", "missing"])
def test_tampering_is_rejected_and_active_state_survives(monkeypatch, tmp_path: Path, tamper: str) -> None:
    _fixture(monkeypatch, tmp_path)
    active_before = memory_stream().read_bytes()
    backup = create_backup(tmp_path / f"tamper-{tamper}")
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    if tamper == "memory":
        path = backup / "canonical/memory/events-v1.jsonl"
        path.write_bytes(path.read_bytes().replace(b"user statement", b"user statememt", 1))
    elif tamper == "manifest":
        manifest["files"][0]["size"] += 1
        (backup / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    else:
        (backup / "canonical/memory/events-v1.jsonl").unlink()
    with pytest.raises(BackupError) as exc_info:
        verify_backup(backup)
    assert exc_info.value.code in {"CHECKSUM_MISMATCH", "MISSING_PAYLOAD", "INVALID_MANIFEST"}
    with pytest.raises(BackupError):
        restore_backup(backup, yes=True)
    assert memory_stream().read_bytes() == active_before


def test_verify_rejects_unsafe_and_duplicate_manifest_paths_without_mutation(monkeypatch, tmp_path: Path) -> None:
    _fixture(monkeypatch, tmp_path)
    backup = create_backup(tmp_path / "path checks")
    before = (backup / "manifest.json").read_bytes()
    manifest = json.loads(before)
    manifest["files"][0]["path"] = "../escape"
    (backup / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BackupError) as exc_info:
        verify_backup(backup)
    assert exc_info.value.code == "UNSAFE_PATH"
    (backup / "manifest.json").write_bytes(before)
    manifest = json.loads(before)
    manifest["files"].append(dict(manifest["files"][0]))
    (backup / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BackupError) as exc_info:
        verify_backup(backup)
    assert exc_info.value.code == "INVALID_MANIFEST"


def test_unknown_format_and_future_schema_fail_closed(monkeypatch, tmp_path: Path) -> None:
    _fixture(monkeypatch, tmp_path)
    backup = create_backup(tmp_path / "version checks")
    manifest_path = backup / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["backup_format_version"] = 999
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BackupError) as exc_info:
        verify_backup(backup)
    assert exc_info.value.code == "UNSUPPORTED_BACKUP_VERSION"
    manifest["backup_format_version"] = 1
    manifest["schema_version"] = 999
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BackupError) as exc_info:
        verify_backup(backup)
    assert exc_info.value.code == "SCHEMA_INCOMPATIBLE"


def test_restore_requires_explicit_confirmation_and_verify_is_read_only(monkeypatch, tmp_path: Path) -> None:
    _fixture(monkeypatch, tmp_path)
    backup = create_backup(tmp_path / "readonly proof")
    before_backup = sorted((p.relative_to(backup).as_posix(), p.read_bytes()) for p in backup.rglob("*") if p.is_file())
    before_active = {
        path.relative_to(data_root()).as_posix(): path.read_bytes()
        for path in data_root().rglob("*")
        if path.is_file()
    }
    before_config = {
        path.relative_to(config_root()).as_posix(): path.read_bytes()
        for path in config_root().rglob("*")
        if path.is_file()
    }
    before_memory = memory_stream().read_bytes()
    before_derived = derived_db().read_bytes()
    before_descriptor = config_path().read_bytes()
    with pytest.raises(BackupError) as exc_info:
        restore_backup(backup)
    assert exc_info.value.code == "CONFIRMATION_REQUIRED"
    assert verify_backup(backup)["status"] == "VALID"
    after_backup = sorted((p.relative_to(backup).as_posix(), p.read_bytes()) for p in backup.rglob("*") if p.is_file())
    assert after_backup == before_backup
    after_active = {
        path.relative_to(data_root()).as_posix(): path.read_bytes()
        for path in data_root().rglob("*")
        if path.is_file()
    }
    after_config = {
        path.relative_to(config_root()).as_posix(): path.read_bytes()
        for path in config_root().rglob("*")
        if path.is_file()
    }
    assert after_active == before_active
    assert after_config == before_config
    assert memory_stream().read_bytes() == before_memory
    assert derived_db().read_bytes() == before_derived
    assert config_path().read_bytes() == before_descriptor


def test_restore_failure_after_staging_preserves_active_state(monkeypatch, tmp_path: Path) -> None:
    _fixture(monkeypatch, tmp_path)
    backup = create_backup(tmp_path / "staging failure")
    _write_events([_event("post-backup", text="active candidate")])
    before = memory_stream().read_bytes()

    def fail_rebuild(_stage_root: Path, _corpus_stage: Path | None) -> None:
        raise BackupError("REBUILD_FAILED")

    monkeypatch.setattr(backup_module, "_rebuild_staged_derived", fail_rebuild)
    with pytest.raises(BackupError) as exc_info:
        restore_backup(backup, yes=True)
    assert exc_info.value.code == "REBUILD_FAILED"
    assert memory_stream().read_bytes() == before


def test_activation_failure_rolls_back_old_active_state(monkeypatch, tmp_path: Path) -> None:
    _fixture(monkeypatch, tmp_path)
    backup = create_backup(tmp_path / "activation failure")
    _write_events([_event("post-backup", text="active candidate")])
    before = memory_stream().read_bytes()

    def fail_configuration(_root: Path, _manifest: dict) -> None:
        raise BackupError("RESTORE_FAILED")

    monkeypatch.setattr(backup_module, "_restore_configuration", fail_configuration)
    with pytest.raises(BackupError) as exc_info:
        restore_backup(backup, yes=True)
    assert exc_info.value.code == "RESTORE_FAILED"
    assert memory_stream().read_bytes() == before