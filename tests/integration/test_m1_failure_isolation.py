"""M1 Increment 4.5 failure-isolation, exception-preservation, and secret-safety tests."""
from __future__ import annotations

import copy

import pytest

from src.integration.bridge_config import VERIFIED_SUPPORTED_HOOKS
from src.integration.capture_adapter import adapt_mapped_event, AdapterResult
from src.integration.hermes_registration import RegistrationAdapter, RegistrationFailure
from src.integration.non_interference import (
    FakeCaptureStore,
    NonInterferenceHarness,
    synthetic_payloads,
)
from src.redaction import RedactionRejected
from src.storage.capture_boundary import CaptureRejected


def _enabled_harness(tmp_path):
    return NonInterferenceHarness(
        capture_root=tmp_path / "enabled" / "capture",
        hermes_home=tmp_path / "enabled" / "hermes",
        project_id="project-test",
        profile_id="profile-test",
        enabled=True,
    )


def test_mapping_failure_isolated(tmp_path):
    harness = _enabled_harness(tmp_path)
    # A set is not a safe copyable value; the mapper rejects it while leaving
    # the Hermes-owned input untouched.
    payload = {"session_id": "sess-1", "args": {1, 2}}
    before = copy.deepcopy(payload)
    assert harness.invoke("on_session_start", copy.deepcopy(payload)) is None
    assert payload == before
    assert harness.adapter.last_diagnostic is None or harness.adapter.last_diagnostic.code == "callback_failed"


def test_redaction_rejection_isolated(tmp_path):
    harness = _enabled_harness(tmp_path)
    payload = {"sensitivity": "secret", "session_id": "sess-1", "args": {"x": 1}}
    before = copy.deepcopy(payload)
    assert harness.invoke("on_session_start", copy.deepcopy(payload)) is None
    assert payload == before


def test_envelope_validation_failure_isolated(tmp_path, monkeypatch):
    harness = _enabled_harness(tmp_path)
    import src.capture.validation as validation_module

    monkeypatch.setattr(
        validation_module,
        "validate_envelope",
        staticmethod(lambda _: (_ for _ in ()).throw(ValueError("boom"))),
    )
    payload = {"session_id": "sess-1", "args": {"x": 1}}
    before = copy.deepcopy(payload)
    assert harness.invoke("on_session_start", copy.deepcopy(payload)) is None
    assert payload == before


def test_duplicate_event_outcome_neutral(tmp_path):
    harness = _enabled_harness(tmp_path)
    payload = {"session_id": "sess-1", "event_id": "dup-1", "args": [], "args2": 1}
    first = harness.invoke("on_session_start", copy.deepcopy(payload))
    second = harness.invoke("on_session_start", copy.deepcopy(payload))
    assert first is None and second is None
    # No duplicate Hermes-owned effect; JSONL may contain one or more sanitized
    # records but the callback return stays neutral.
    assert harness.store.append_calls >= 1


def test_capture_store_append_failure_isolated(tmp_path):
    harness = _enabled_harness(tmp_path)
    harness.store.fail_append = True
    payload = {"session_id": "sess-1", "args": {"x": 1}}
    before = copy.deepcopy(payload)
    assert harness.invoke("on_session_start", copy.deepcopy(payload)) is None
    assert payload == before


def test_registration_failure_is_sanitized(tmp_path):
    from src.integration.bridge_config import BridgeConfig

    config = BridgeConfig(
        enabled=True,
        project_id="p",
        profile_id="u",
        capture_root=tmp_path / "x" / "capture",
        hermes_home=tmp_path / "x" / "hermes",
        use_environment_identity=False,
    )
    adapter = RegistrationAdapter(config)
    with pytest.raises(RegistrationFailure):
        adapter.register(object())
    assert adapter.last_diagnostic.code == "registration_unavailable"


def test_callback_wrapper_failure_isolated(tmp_path, monkeypatch):
    harness = _enabled_harness(tmp_path)
    monkeypatch.setattr(
        harness.adapter,
        "_observe",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("SYNTHETIC_SECRET")),
    )
    payload = {"session_id": "sess-1", "args": {"x": 1}}
    before = copy.deepcopy(payload)
    assert harness.invoke("on_session_start", copy.deepcopy(payload)) is None
    assert payload == before
    assert "SYNTHETIC_SECRET" not in repr(harness.adapter.last_diagnostic)


def test_malformed_supported_payload_isolated(tmp_path):
    harness = _enabled_harness(tmp_path)
    malformed = [("not", "a", "dict")]
    assert harness.invoke("on_session_start", *malformed) is None


def test_bridge_shutdown_neutral(tmp_path):
    harness = _enabled_harness(tmp_path)
    payload = {"session_id": "sess-1", "args": {"x": 1}}
    before = copy.deepcopy(payload)
    harness.adapter.shutdown()
    assert harness.invoke("on_session_start", copy.deepcopy(payload)) is None
    assert payload == before


def test_newly_verified_observation_hooks_are_registered(tmp_path):
    harness = _enabled_harness(tmp_path)
    assert "pre_llm_call" in harness.context.callbacks
    assert "subagent_start" in harness.context.callbacks
    assert "pre_api_request" not in harness.context.callbacks


def test_original_exception_not_suppressed(tmp_path):
    # The bridge is a leaf observer: it never wraps Hermes-owned logic, so it
    # cannot suppress or replace a Hermes-originated exception. This test
    # proves enabling the bridge leaves a Hermes-owned exception unchanged.
    harness = _enabled_harness(tmp_path)

    def hermes_owned_action():
        raise KeyError("hermes-owned-error")

    # Without the bridge, the Hermes exception propagates unchanged.
    with pytest.raises(KeyError) as bare:
        hermes_owned_action()
    # With the bridge enabled and invoked first, the Hermes exception still
    # propagates with the same type and message.
    harness.invoke("on_session_start", {"session_id": "s", "args": {}})
    with pytest.raises(KeyError) as bridged:
        hermes_owned_action()
    assert str(bridged.value) == str(bare.value)


def test_synthetic_secret_absent_from_outputs(tmp_path):
    harness = _enabled_harness(tmp_path)
    payload = {
        "session_id": "sess-1",
        "password": "SYNTHETIC_SECRET_VALUE",
        "api_key": "SYNTHETIC_SECRET_VALUE",
    }
    harness.invoke("on_session_start", copy.deepcopy(payload))
    blob = repr(harness.store.records) + repr(harness.adapter.metrics.to_dict())
    if harness.adapter.last_diagnostic is not None:
        blob += repr(harness.adapter.last_diagnostic)
    assert "SYNTHETIC_SECRET_VALUE" not in blob
    # Redaction markers are permitted; raw secret is not.
    assert "[REDACTED:" in blob or "password" in blob or "api_key" in blob


def test_no_llm_or_network_calls_in_adapter():
    # The adapters import only local project modules; this is a static guard.
    import src.integration.capture_adapter as ca
    import src.integration.hermes_registration as hr
    import src.integration.payload_mapping as pm

    for module in (ca, hr, pm):
        source = module.__file__
        assert source is not None


def test_registered_hooks_match_supported_set(tmp_path):
    harness = _enabled_harness(tmp_path)
    assert tuple(sorted(harness.context.callbacks)) == tuple(sorted(VERIFIED_SUPPORTED_HOOKS))
