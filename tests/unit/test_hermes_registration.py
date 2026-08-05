from __future__ import annotations

import copy
from pathlib import Path

import pytest

from src.integration.bridge_config import BridgeConfig, VERIFIED_SUPPORTED_HOOKS, CONDITIONAL_FIXTURE_REQUIRED, DEFERRED_HOOKS
from src.integration.hermes_registration import RegistrationAdapter, RegistrationFailure


class FakeContext:
    def __init__(self):
        self.callbacks = {}

    def register_hook(self, hook, callback):
        self.callbacks.setdefault(hook, []).append(callback)


def test_disabled_by_default_registers_nothing():
    context = FakeContext()
    adapter = RegistrationAdapter(BridgeConfig(capture_root=Path('/tmp/zero-mem-registration')))
    assert adapter.register(context) == ()
    assert context.callbacks == {}


def test_enabled_registers_only_verified_hooks():
    context = FakeContext()
    adapter = RegistrationAdapter(BridgeConfig(enabled=True, capture_root=Path('/tmp/zero-mem-registration')))
    registered = adapter.register(context)
    assert registered == VERIFIED_SUPPORTED_HOOKS
    assert tuple(context.callbacks) == VERIFIED_SUPPORTED_HOOKS
    assert not set(context.callbacks) & set(CONDITIONAL_FIXTURE_REQUIRED)
    assert not set(context.callbacks) & set(DEFERRED_HOOKS)


def test_registration_is_idempotent():
    context = FakeContext()
    adapter = RegistrationAdapter(BridgeConfig(enabled=True, capture_root=Path('/tmp/zero-mem-registration')))
    first = adapter.register(context)
    second = adapter.register(context)
    assert first == second
    assert all(len(callbacks) == 1 for callbacks in context.callbacks.values())


def test_callback_is_neutral_and_does_not_mutate_payload(monkeypatch):
    context = FakeContext()
    adapter = RegistrationAdapter(BridgeConfig(enabled=True, capture_root=Path('/tmp/zero-mem-registration')))
    adapter.register(context)
    payload = {'session_id': 's1', 'args': {'value': 'safe'}}
    before = copy.deepcopy(payload)
    monkeypatch.setattr(adapter, '_observe', lambda hook, payload: None)
    assert context.callbacks['pre_tool_call'][0](payload) is None
    assert payload == before


def test_callback_failure_isolated(monkeypatch):
    context = FakeContext()
    adapter = RegistrationAdapter(BridgeConfig(enabled=True, capture_root=Path('/tmp/zero-mem-registration')))
    adapter.register(context)
    monkeypatch.setattr(adapter, '_observe', lambda hook, payload: (_ for _ in ()).throw(RuntimeError('raw secret')))
    assert context.callbacks['post_tool_call'][0]({'result': 'safe'}) is None
    assert adapter.metrics.to_dict()['counts']


def test_shutdown_disables_new_capture():
    context = FakeContext()
    adapter = RegistrationAdapter(BridgeConfig(enabled=True, capture_root=Path('/tmp/zero-mem-registration')))
    adapter.register(context)
    adapter.shutdown()
    assert adapter.enabled is False


def test_unsupported_registration_surface_is_sanitized():
    adapter = RegistrationAdapter(BridgeConfig(enabled=True, capture_root=Path('/tmp/zero-mem-registration')))
    with pytest.raises(RegistrationFailure, match='registration_unavailable'):
        adapter.register(object())
    assert 'raw secret' not in str(adapter.last_diagnostic).lower()
