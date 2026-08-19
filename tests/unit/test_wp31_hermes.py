from __future__ import annotations

from pathlib import Path

from src.integration.bridge_config import BridgeConfig
from src.integration.hermes_read_adapter import HermesReadAdapter
from src.integration.m7.injection_adapter import InjectionAdapter
from src.integration.sidecar import ZeroMemSidecar
from src.integration.zero_mem_runtime import configure, get_runtime
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from zero_mem.hermes_integration import HermesBoundary, IntegrationConfig


def test_wp31_read_adapter_uses_bounded_sidecar_and_restarts(tmp_path: Path) -> None:
    store_path = tmp_path / "hermes.sqlite"
    store = SQLiteStore(SQLiteStoreConfig(path=store_path))
    store.close()
    adapter = HermesReadAdapter(BridgeConfig(enabled=True, capture_root=tmp_path / "capture"), store_path=store_path)
    adapter.startup()
    assert isinstance(adapter._sidecar, ZeroMemSidecar)
    assert adapter.call("unknown_tool", {})["status"] == "UNSUPPORTED_TOOL"
    adapter.shutdown()
    assert adapter.call("unknown_tool", {})["reason_code"] == "adapter_not_ready"
    adapter.restart()
    assert adapter.call("unknown_tool", {})["status"] == "UNSUPPORTED_TOOL"
    adapter.shutdown()


def test_wp31_disabled_boundary_clears_stale_runtime(monkeypatch) -> None:
    configure(enabled=True)
    monkeypatch.setenv("ZERO_MEM_ENABLED", "false")
    result = HermesBoundary(IntegrationConfig("project-a", "profile-a")).register(object())
    assert result == {"hooks": (), "tools": (), "injection": ()}
    assert get_runtime().is_enabled() is False


def test_wp31_boundary_cannot_reenable_disabled_global_runtime(monkeypatch) -> None:
    configure(enabled=False)
    monkeypatch.delenv("ZERO_MEM_ENABLED", raising=False)
    result = HermesBoundary(IntegrationConfig("project-global-off", "profile-global-off")).register(object())
    assert result == {"hooks": (), "tools": (), "injection": ()}
    assert get_runtime().is_enabled() is False


def test_wp31_boundary_registration_is_idempotent(tmp_path: Path) -> None:
    class Context:
        def __init__(self) -> None:
            self.hooks = []
            self.tools = []

        def register_hook(self, name, callback):
            self.hooks.append(name)

        def register_tool(self, *args, **kwargs):
            self.tools.append(args[0])

    context = Context()
    boundary = HermesBoundary(IntegrationConfig("project-b", "profile-b"), capture_root=tmp_path / "capture")
    first = boundary.register(context)
    hook_count = len(context.hooks)
    second = boundary.register(context)
    assert second == first
    assert len(context.hooks) == hook_count
    boundary.shutdown()
    third = boundary.register(context)
    assert third == first
    assert len(context.hooks) == hook_count


def test_wp31_injection_adapter_revokes_and_restarts_with_boundary(tmp_path: Path) -> None:
    configure(enabled=True)

    class Context:
        def register_hook(self, name, callback):
            self.callback = callback

    context = Context()
    boundary = HermesBoundary(IntegrationConfig("project-c", "profile-c"))
    result = boundary.register(context)
    assert result["injection"] == ("pre_llm_call",)
    adapter = boundary._injection_adapter
    assert isinstance(adapter, InjectionAdapter)
    assert adapter.process(user_message="what did we decide?").reason == "no_store"

    boundary.shutdown()
    assert adapter.process(user_message="what did we decide?").reason == "adapter_shutdown"

    restarted = boundary.register(context)
    assert restarted == result
    assert adapter.process(user_message="what did we decide?").reason == "no_store"
    boundary.shutdown()


def test_wp31_direct_injection_process_is_fail_closed(monkeypatch) -> None:
    adapter = InjectionAdapter()
    monkeypatch.setattr(
        "src.integration.m7.injection_adapter.route",
        lambda request: (_ for _ in ()).throw(RuntimeError("raw detail")),
    )
    result = adapter.process(user_message="needs memory")
    assert result.injected is False
    assert result.context == ""
    assert result.reason == "downstream_error"


def test_wp31_old_read_handler_fails_closed_after_master_disable(tmp_path: Path, monkeypatch) -> None:
    store_path = tmp_path / "read.sqlite"
    store = SQLiteStore(SQLiteStoreConfig(path=store_path))
    store.close()

    class Context:
        def __init__(self) -> None:
            self.handlers = {}

        def register_tool(self, name, *args, **kwargs):
            self.handlers[name] = args[2] if len(args) >= 3 else args[1]

    context = Context()
    adapter = HermesReadAdapter(BridgeConfig(enabled=True, capture_root=tmp_path / "capture"), store_path=store_path)
    adapter.startup()
    adapter.register(context)
    handler = context.handlers["memory_query"]
    monkeypatch.setenv("ZERO_MEM_ENABLED", "false")
    configure(enabled=False)
    assert handler({"requesting_profile_id": "profile-a"})["reason_code"] == "ZERO_MEM_DISABLED"
    adapter.shutdown()
