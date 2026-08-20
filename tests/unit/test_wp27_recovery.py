from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest
from src.storage.recovery import DEFAULT_RECOVERY_TIMEOUT, RecoveryCoordinator, RecoveryResult, RecoveryStatus, _CleanupFailure, _identity
from src.storage.runtime_root import RuntimeStorageRoot


def _event(event_id: str = "evt-1") -> dict:
    return {
        "event_id": event_id,
        "trace_id": "tr-1",
        "event_type": "tool_observation",
        "source": "pre_tool_call",
        "schema_version": 1,
        "created_at": "2026-08-06T00:00:00Z",
        "observed_at": "2026-08-06T00:00:00Z",
        "sequence": 0,
        "lifecycle_status": "observed",
        "verification_status": "none",
        "confidence": "medium",
        "sensitivity": "internal",
        "retention": "persistent",
        "sanitized_content_hash": "h-evt-1",
        "sanitized_content": {"text": "clean"},
        "redaction_audit": [],
    }


def _storage(tmp_path: Path) -> RuntimeStorageRoot:
    return RuntimeStorageRoot.open(tmp_path / "zero-mem")


def _write_canonical(path: Path) -> bytes:
    path.write_text(json.dumps(_event()) + "\n")
    return path.read_bytes()


def test_diagnose_missing_derived_is_fail_closed(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    coordinator = RecoveryCoordinator(storage, canonical, storage.derived / "meta.sqlite")
    result = coordinator.diagnose()
    assert result.status is RecoveryStatus.MISSING
    assert result.canonical_sequence == 0


def test_recover_rebuilds_missing_derived_without_mutating_canonical(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    before = _write_canonical(canonical)
    coordinator = RecoveryCoordinator(storage, canonical, storage.derived / "meta.sqlite")
    result = coordinator.recover(timeout=5.0)
    assert result.status is RecoveryStatus.REBUILT
    assert coordinator.diagnose().status is RecoveryStatus.CURRENT
    assert canonical.read_bytes() == before


def test_malformed_canonical_is_not_rebuilt(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    canonical.write_text("not-json\n")
    coordinator = RecoveryCoordinator(storage, canonical, storage.derived / "meta.sqlite")
    result = coordinator.recover(timeout=1.0)
    assert result.status is RecoveryStatus.UNAVAILABLE
    assert not (storage.derived / "meta.sqlite").exists()


def test_recovery_does_not_retry_after_terminal_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    coordinator = RecoveryCoordinator(storage, canonical, storage.derived / "meta.sqlite")
    monkeypatch.setattr(coordinator, "_build_default", lambda *_args: (_ for _ in ()).throw(RuntimeError("secret")))
    first = coordinator.recover(timeout=1.0)
    second = coordinator.recover(timeout=1.0)
    assert first.status is RecoveryStatus.UNAVAILABLE
    assert second.status is RecoveryStatus.UNAVAILABLE


def test_recovery_deadline_leaves_canonical_and_derived_unchanged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    before = _write_canonical(canonical)
    gate = threading.Event()
    coordinator = RecoveryCoordinator(storage, canonical, storage.derived / "meta.sqlite")

    def blocked_rebuild(*_args: object) -> None:
        gate.wait(timeout=1.0)

    monkeypatch.setattr(coordinator, "_build_default", blocked_rebuild)
    result = coordinator.recover(timeout=0.01)
    gate.set()
    assert result.status is RecoveryStatus.INTERRUPTED
    assert canonical.read_bytes() == before
    assert not (storage.derived / "meta.sqlite").exists()


def test_symlinked_derived_path_is_rejected(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    target = tmp_path / "real.sqlite"
    link = storage.derived / "meta.sqlite"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        RecoveryCoordinator(storage, canonical, link)


def test_dangling_recovery_build_symlink_is_rejected(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    derived = storage.derived / "meta.sqlite"
    building = storage.derived / "meta.sqlite.recovery-building"
    outside = tmp_path / "outside.sqlite"
    building.symlink_to(outside)
    result = RecoveryCoordinator(storage, canonical, derived).recover(timeout=1.0)
    assert result.status is RecoveryStatus.UNAVAILABLE
    assert not outside.exists()


def test_invalid_timeout_fails_closed(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    result = RecoveryCoordinator(storage, canonical, storage.derived / "meta.sqlite").recover(timeout="bad")  # type: ignore[arg-type]
    assert result.status is RecoveryStatus.UNAVAILABLE
    assert result.diagnostic_code == "invalid_timeout"


def test_destination_sidecar_symlink_fails_closed(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    derived = storage.derived / "meta.sqlite"
    derived.write_bytes(b"not sqlite")
    outside = tmp_path / "outside.sqlite"
    sidecar = Path(str(derived) + "-wal")
    sidecar.symlink_to(outside)
    result = RecoveryCoordinator(storage, canonical, derived).recover(timeout=1.0)
    assert result.status is RecoveryStatus.UNAVAILABLE
    assert not outside.exists()


def test_corrupt_derived_is_replaced_by_verified_rebuild(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    derived = storage.derived / "meta.sqlite"
    derived.write_bytes(b"not sqlite")
    coordinator = RecoveryCoordinator(storage, canonical, derived)
    result = coordinator.recover(timeout=5.0)
    assert result.status is RecoveryStatus.REBUILT
    assert coordinator.diagnose().status is RecoveryStatus.CURRENT


def test_shared_derived_lock_blocks_diagnosis_with_bounded_timeout(tmp_path: Path) -> None:
    from src.storage.coordination import locked

    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    derived = storage.derived / "meta.sqlite"
    lock_path = derived.with_name(derived.name + ".lock")
    with locked(lock_path, mode="exclusive", timeout=1.0):
        result = RecoveryCoordinator(storage, canonical, derived).diagnose()
    assert result.status is RecoveryStatus.UNAVAILABLE
    assert result.diagnostic_code == "coordination_unavailable"


def test_unknown_nonregular_legacy_build_is_never_removed(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    derived = storage.derived / "meta.sqlite"
    building = storage.derived / "meta.sqlite.recovery-building"
    building.mkdir()
    result = RecoveryCoordinator(storage, canonical, derived).recover(timeout=1.0)
    assert result.status is RecoveryStatus.UNAVAILABLE
    assert building.is_dir()


def test_unknown_regular_legacy_build_is_preserved_and_blocks(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    derived = storage.derived / "meta.sqlite"
    building = storage.derived / "meta.sqlite.recovery-building"
    building.write_bytes(b"unknown")
    result = RecoveryCoordinator(storage, canonical, derived).recover(timeout=1.0)
    assert result.status is RecoveryStatus.UNAVAILABLE
    assert result.diagnostic_code == "unsafe_derived_artifact"
    assert building.exists()


def test_owned_build_missing_identity_is_preserved(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    derived = storage.derived / "meta.sqlite"
    building = storage.derived / "meta.sqlite.recovery-building.owned"
    marker = Path(str(building) + ".owner")
    building.write_bytes(b"untrusted")
    marker.write_text(json.dumps({"token": "owned", "build": str(building), "destination": str(derived), "canonical": {}}))
    result = RecoveryCoordinator(storage, canonical, derived).recover(timeout=1.0)
    assert result.status is RecoveryStatus.UNAVAILABLE
    assert building.exists()
    assert marker.exists()


def test_promotion_rejects_replaced_build_identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    derived = storage.derived / "meta.sqlite"
    coordinator = RecoveryCoordinator(storage, canonical, derived)
    original = coordinator._build_default

    def replace_build(snapshot: Path, build: Path, marker: Path, token: str) -> None:
        original(snapshot, build, marker, token)
        replacement = build.with_name(build.name + ".replacement")
        replacement.write_bytes(build.read_bytes())
        build.unlink()
        replacement.rename(build)

    monkeypatch.setattr(coordinator, "_build_default", replace_build)
    result = coordinator.recover(timeout=5.0)
    assert result.status is RecoveryStatus.UNAVAILABLE
    assert not derived.exists()


def test_promotion_rollback_failure_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    derived = storage.derived / "meta.sqlite"
    derived.write_bytes(b"not sqlite")
    sidecar = Path(str(derived) + "-wal")
    sidecar.write_bytes(b"old wal")
    real_rename = os.replace
    calls = 0

    def fail_rollback(src: str, dst: str, *, src_dir_fd: int | None = None, dst_dir_fd: int | None = None) -> None:
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise OSError("simulated rollback failure")
        real_rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr("src.storage.platform.os.replace", fail_rollback)
    result = RecoveryCoordinator(storage, canonical, derived).recover(timeout=5.0)
    assert result.status is RecoveryStatus.UNAVAILABLE
    assert result.diagnostic_code == "promotion_rollback_failed"


def test_canonical_mutation_during_rebuild_is_fenced(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    derived = storage.derived / "meta.sqlite"

    class Report:
        stopped = False

    def mutate_then_report(*_args: object, **_kwargs: object) -> dict[str, Report]:
        with canonical.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(_event("evt-2")) + "\n")
        return {"events.jsonl": Report()}

    monkeypatch.setattr("src.storage.recovery.rebuild_from_jsonl", mutate_then_report)
    result = RecoveryCoordinator(storage, canonical, derived).recover(timeout=2.0)
    assert result.status is RecoveryStatus.INTERRUPTED
    assert not derived.exists()


def test_timeout_worker_cannot_block_subsequent_owned_recovery(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    gate = threading.Event()
    first = RecoveryCoordinator(storage, canonical, storage.derived / "meta.sqlite")

    def blocked_rebuild(*_args: object) -> None:
        gate.wait(timeout=1.0)

    monkeypatch.setattr(first, "_build_default", blocked_rebuild)
    interrupted = first.recover(timeout=0.01)
    assert interrupted.status is RecoveryStatus.INTERRUPTED
    gate.set()
    threading.Event().wait(0.02)
    second = RecoveryCoordinator(storage, canonical, storage.derived / "meta.sqlite")
    assert second.recover(timeout=2.0).status is RecoveryStatus.REBUILT


def test_duplicate_content_hash_tail_is_current_after_rebuild(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    first = _event("evt-1")
    second = _event("evt-2")
    second["sequence"] = 1
    canonical.write_text(json.dumps(first) + "\n" + json.dumps(second) + "\n")
    coordinator = RecoveryCoordinator(storage, canonical, storage.derived / "meta.sqlite")
    assert coordinator.recover(timeout=2.0).status is RecoveryStatus.REBUILT
    assert coordinator.diagnose().status is RecoveryStatus.CURRENT


def test_timeout_none_uses_finite_runtime_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    monkeypatch.setattr("src.storage.recovery.DEFAULT_RECOVERY_TIMEOUT", 0.01)
    from src.storage.coordination import locked

    lock_path = (storage.derived / "meta.sqlite").with_name("meta.sqlite.lock")
    with locked(lock_path, mode="exclusive", timeout=1.0):
        result = RecoveryCoordinator(storage, canonical, storage.derived / "meta.sqlite").recover(timeout=None)
    assert DEFAULT_RECOVERY_TIMEOUT > 0
    assert result.status is RecoveryStatus.UNAVAILABLE
    assert result.diagnostic_code == "coordination_unavailable"


def test_late_canonical_derived_hardlink_alias_fails_closed(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    derived = storage.derived / "meta.sqlite"
    coordinator = RecoveryCoordinator(storage, canonical, derived)
    derived.hardlink_to(canonical)
    result = coordinator.recover(timeout=1.0)
    assert result.status is RecoveryStatus.UNAVAILABLE
    assert result.diagnostic_code in {"canonical_derived_alias", "unsafe_derived_artifact", "coordination_unavailable"}


def test_recovery_rejects_paths_outside_runtime_domains(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    with pytest.raises(ValueError, match="outside runtime storage domain"):
        RecoveryCoordinator(storage, tmp_path / "outside.jsonl", storage.derived / "meta.sqlite")
    with pytest.raises(ValueError, match="outside runtime storage domain"):
        RecoveryCoordinator(storage, canonical, tmp_path / "outside.sqlite")


def test_owner_identity_rejects_boolean_device_and_inode(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    derived = storage.derived / "meta.sqlite"
    building = storage.derived / "meta.sqlite.recovery-building.bool"
    marker = Path(str(building) + ".owner")
    building.write_bytes(b"untrusted")
    marker.write_text(json.dumps({
        "token": "owned",
        "build": str(building),
        "destination": str(derived),
        "canonical": {},
        "build_identity": {"device": True, "inode": 1},
    }))
    result = RecoveryCoordinator(storage, canonical, derived).recover(timeout=1.0)
    assert result.status is RecoveryStatus.UNAVAILABLE
    assert building.exists()
    assert marker.exists()


def test_owner_identity_rejects_malformed_canonical_identity(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    derived = storage.derived / "meta.sqlite"
    building = storage.derived / "meta.sqlite.recovery-building.malformed-canonical"
    marker = Path(str(building) + ".owner")
    building.write_bytes(b"untrusted")
    marker.write_text(json.dumps({
        "token": "owned",
        "build": str(building),
        "destination": str(derived),
        "canonical": {},
        "build_identity": {"device": 1, "inode": 2},
    }))
    result = RecoveryCoordinator(storage, canonical, derived).recover(timeout=1.0)
    assert result.status is RecoveryStatus.UNAVAILABLE
    assert building.exists()
    assert marker.exists()


def test_cleanup_failure_is_reported_not_swallowed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    coordinator = RecoveryCoordinator(storage, canonical, storage.derived / "meta.sqlite")
    monkeypatch.setattr(coordinator, "_safe_unlink_snapshot", lambda *_args: (_ for _ in ()).throw(_CleanupFailure("snapshot_cleanup_failed")))
    result = coordinator.recover(timeout=5.0)
    assert result.status is RecoveryStatus.UNAVAILABLE
    assert result.diagnostic_code == "snapshot_cleanup_failed"


def test_snapshot_cleanup_failure_is_not_swallowed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    coordinator = RecoveryCoordinator(storage, canonical, storage.derived / "meta.sqlite")
    snapshot = canonical.with_name("events.jsonl.recovery-snapshot.injected")
    identity = _identity(canonical)
    monkeypatch.setattr("src.storage.recovery.os.fsync", lambda _fd: (_ for _ in ()).throw(OSError("fsync failure")))
    monkeypatch.setattr("src.storage.recovery.os.unlink", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("unlink failure")))
    with pytest.raises(_CleanupFailure, match="snapshot_cleanup_failed"):
        coordinator._create_snapshot(snapshot, identity)


def test_post_commit_diagnosis_failure_is_not_interrupted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    coordinator = RecoveryCoordinator(storage, canonical, storage.derived / "meta.sqlite")
    original = coordinator._diagnose_unlocked
    calls = 0

    def diagnose_after_commit() -> RecoveryResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            return original()
        return RecoveryResult(RecoveryStatus.STALE, "events.jsonl", 0, 0, "derived_stale")

    monkeypatch.setattr(coordinator, "_diagnose_unlocked", diagnose_after_commit)
    result = coordinator.recover(timeout=5.0)
    assert result.status is RecoveryStatus.UNAVAILABLE
    assert result.diagnostic_code == "committed_post_diagnosis_failed"


def test_orphan_owner_marker_fails_closed(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    orphan = storage.derived / "meta.sqlite.recovery-building.orphan.owner"
    orphan.write_text("{}")
    result = RecoveryCoordinator(storage, canonical, storage.derived / "meta.sqlite").recover(timeout=1.0)
    assert result.status is RecoveryStatus.UNAVAILABLE
    assert result.diagnostic_code == "unsafe_derived_artifact"
    assert orphan.exists()


def test_unknown_quarantine_artifact_fails_closed(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    canonical = storage.canonical / "events.jsonl"
    _write_canonical(canonical)
    quarantine = storage.derived / "meta.sqlite-wal.recovery-old.unknown"
    quarantine.write_bytes(b"old")
    result = RecoveryCoordinator(storage, canonical, storage.derived / "meta.sqlite").recover(timeout=1.0)
    assert result.status is RecoveryStatus.UNAVAILABLE
    assert result.diagnostic_code == "unsafe_derived_artifact"
    assert quarantine.exists()


@pytest.mark.parametrize("timeout", [True, float("nan"), float("inf"), "bad"])
def test_coordination_rejects_non_finite_or_invalid_timeout(tmp_path: Path, timeout: object) -> None:
    from src.storage.coordination import locked

    with pytest.raises(ValueError, match="invalid_lock_timeout"):
        with locked(tmp_path / "lock", timeout=timeout):  # type: ignore[arg-type]
            pass
