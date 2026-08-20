from __future__ import annotations

import copy
from pathlib import Path

from src.integration.bridge_config import BridgeConfig, VERIFIED_SUPPORTED_HOOKS
from src.integration.hermes_registration import RegistrationAdapter
from src.integration.hermes_plugin import create_plugin
from src.integration.non_interference import FakeCaptureStore
from src.integration.zero_mem_runtime import configure


class Context:
    def __init__(self):
        self.callbacks = {}

    def register_hook(self, hook, callback):
        self.callbacks[hook] = callback


def test_v0191_plugin_context_surface_fixture(tmp_path: Path) -> None:
    context = Context()
    adapter = RegistrationAdapter(BridgeConfig(enabled=True, capture_root=tmp_path / "capture", hermes_home=tmp_path / "hermes"))
    assert adapter.register(context) == VERIFIED_SUPPORTED_HOOKS
    assert tuple(context.callbacks) == VERIFIED_SUPPORTED_HOOKS


def test_enabled_and_disabled_paths_are_non_interfering(tmp_path: Path) -> None:
    payload = {"session_id": "s1", "args": {"value": "safe"}}
    before = copy.deepcopy(payload)
    disabled = RegistrationAdapter(BridgeConfig(enabled=False, capture_root=tmp_path / "disabled"))
    context = Context()
    assert disabled.register(context) == ()
    enabled = RegistrationAdapter(BridgeConfig(enabled=True, capture_root=tmp_path / "enabled"))
    enabled.register(context)
    assert context.callbacks["pre_tool_call"](payload) is None
    assert payload == before


def test_hermes_home_is_temporary_and_explicit(tmp_path: Path) -> None:
    config = BridgeConfig(enabled=True, capture_root=tmp_path / "capture", hermes_home=tmp_path / "hermes")
    assert config.hermes_home == (tmp_path / "hermes").resolve()
    assert not Path.home().joinpath(".hermes").joinpath("events-v1.jsonl").exists()


def test_public_host_factory_composes_existing_registration_boundary(tmp_path: Path) -> None:
    configure(enabled=True)
    config = BridgeConfig(enabled=True, capture_root=tmp_path / "capture", hermes_home=tmp_path / "hermes")
    store = FakeCaptureStore(tmp_path / "store")
    plugin = create_plugin(config, store=store)
    assert isinstance(plugin, RegistrationAdapter)
    context = Context()
    assert plugin.register(context) == VERIFIED_SUPPORTED_HOOKS
    assert context.callbacks["pre_tool_call"]({"session_id": "s1", "tool_name": "shell"}) is None
    assert store.append_calls == 1
    assert store.inspect_record(next(iter(store.event_ids))) is not None
    plugin.restart()
    assert plugin.register(context) == VERIFIED_SUPPORTED_HOOKS
    plugin.shutdown()
