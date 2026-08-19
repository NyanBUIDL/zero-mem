from __future__ import annotations

from pathlib import Path

import pytest

from src.integration.bridge_config import BridgeConfig
from src.integration.payload_mapping import map_hook_payload
from src.integration.hermes_registration import RegistrationAdapter
from src.integration.zero_mem_runtime import RuntimeConfig, ZeroMemRuntime
from src.storage.capture_boundary import CaptureStoreConfig
from src.storage.jsonl_capture import JsonlCaptureStore
from src.storage.runtime_root import RuntimeStorageRoot


def test_runtime_opens_one_canonical_writer_and_closes_idempotently(tmp_path: Path) -> None:
    runtime = ZeroMemRuntime.open(RuntimeConfig(capture_root=tmp_path / "capture"))
    try:
        assert isinstance(runtime.writer, JsonlCaptureStore)
        assert runtime.writer.path == tmp_path / "capture" / "canonical" / CaptureStoreConfig(tmp_path / "capture").stream_name
        assert runtime.health().status == "OPEN"
    finally:
        runtime.close()
    runtime.close()
    assert runtime.health().status == "CLOSED"
    with pytest.raises(RuntimeError, match="RUNTIME_CLOSED"):
        _ = runtime.writer


def test_disabled_runtime_does_not_open_writer(tmp_path: Path) -> None:
    runtime = ZeroMemRuntime.open(RuntimeConfig(capture_root=tmp_path / "capture", enabled=False))
    assert runtime.health().reason_code == "ZERO_MEM_DISABLED"
    with pytest.raises(RuntimeError, match="RUNTIME_WRITER_UNAVAILABLE"):
        _ = runtime.writer
    runtime.close()


def test_runtime_rejects_relative_capture_root() -> None:
    with pytest.raises(ValueError, match="absolute"):
        RuntimeConfig(capture_root=Path("relative-root"))


    with pytest.raises(ValueError, match="real home"):
        RuntimeConfig(capture_root=Path.home() / "unsafe-zero-mem-root")


def test_runtime_storage_root_creates_controlled_domains(tmp_path: Path) -> None:
    storage = RuntimeStorageRoot.open(tmp_path / "zero-mem")
    assert storage.root == tmp_path / "zero-mem"
    assert storage.canonical == storage.root / "canonical"
    assert storage.canonical.is_dir()
    for name in ("derived", "recovery", "locks", "metadata"):
        assert (storage.root / name).is_dir()


def test_runtime_storage_root_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        RuntimeStorageRoot.open(link)


def test_runtime_storage_root_rejects_symlinked_missing_root_ancestor(tmp_path: Path) -> None:
    target = tmp_path / "redirected"
    target.mkdir()
    ancestor = tmp_path / "ancestor-link"
    ancestor.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        RuntimeStorageRoot.open(ancestor / "new-root")
    assert not (target / "new-root").exists()


def test_runtime_config_does_not_resolve_symlink_before_root_validation(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    config = RuntimeConfig(capture_root=link)
    with pytest.raises(ValueError, match="symlink"):
        ZeroMemRuntime.open(config)


def test_production_adapter_observes_without_injected_store(tmp_path: Path) -> None:
    adapter = RegistrationAdapter(
        BridgeConfig(enabled=True, capture_root=tmp_path / "capture"),
    )
    try:
        adapter._observe("on_session_start", {"session_id": "s-2"})
        assert (tmp_path / "capture" / "canonical" / "events-v1.jsonl").read_text()
    finally:
        adapter.shutdown()


    adapter = RegistrationAdapter(
        BridgeConfig(enabled=True, capture_root=tmp_path / "capture"),
    )
    try:
        mapped = map_hook_payload("on_session_start", {"session_id": "s-1"})
        result = adapter._client.capture(mapped)
        assert result.status == "CAPTURED"
    finally:
        adapter.shutdown()


def test_registration_adapter_uses_runtime_owned_injected_test_store(tmp_path: Path) -> None:
    store = JsonlCaptureStore(CaptureStoreConfig(tmp_path / "capture"))
    adapter = RegistrationAdapter(
        BridgeConfig(enabled=True, capture_root=tmp_path / "config-root"),
        store=store,
    )
    try:
        assert adapter.runtime.writer is store
    finally:
        adapter.shutdown()
    assert adapter.runtime.health().status == "CLOSED"
