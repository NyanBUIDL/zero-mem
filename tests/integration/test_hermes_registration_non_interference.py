from __future__ import annotations

import copy
from pathlib import Path

from src.integration.bridge_config import BridgeConfig
from src.integration.hermes_registration import RegistrationAdapter


class Context:
    def __init__(self):
        self.callbacks = {}

    def register_hook(self, hook, callback):
        self.callbacks[hook] = callback


def test_registered_callback_preserves_nested_payload(tmp_path: Path) -> None:
    payload = {"session_id": "s1", "nested": {"args": ["safe", 1]}}
    before = copy.deepcopy(payload)
    context = Context()
    adapter = RegistrationAdapter(BridgeConfig(enabled=True, capture_root=tmp_path / "capture", hermes_home=tmp_path / "hermes"))
    adapter.register(context)
    assert context.callbacks["post_tool_call"](payload) is None
    assert payload == before


def test_callback_failure_does_not_propagate(tmp_path: Path, monkeypatch) -> None:
    context = Context()
    adapter = RegistrationAdapter(BridgeConfig(enabled=True, capture_root=tmp_path / "capture", hermes_home=tmp_path / "hermes"))
    adapter.register(context)
    monkeypatch.setattr(adapter, "_observe", lambda *_: (_ for _ in ()).throw(RuntimeError("SYNTHETIC_SECRET")))
    assert context.callbacks["post_tool_call"]({"result": "safe"}) is None
    assert "SYNTHETIC_SECRET" not in repr(adapter.last_diagnostic)
