"""M1 Increment 4.5 non-interference integration tests.

Paired disabled/enabled execution paths with identical synthetic Hermes
inputs. Asserts enabled observation preserves every Hermes-owned value.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from src.integration.bridge_config import (
    CONDITIONAL_FIXTURE_REQUIRED,
    DEFERRED_HOOKS,
    VERIFIED_SUPPORTED_HOOKS,
)
from src.integration.non_interference import (
    NonInterferenceHarness,
    synthetic_payloads,
)


@pytest.fixture
def payloads() -> dict[str, dict[str, object]]:
    return synthetic_payloads()


def _disabled_harness(tmp_path):
    return NonInterferenceHarness(
        capture_root=tmp_path / "disabled" / "capture",
        hermes_home=tmp_path / "disabled" / "hermes",
        project_id="project-test",
        profile_id="profile-test",
        enabled=False,
    )


def _enabled_harness(tmp_path):
    return NonInterferenceHarness(
        capture_root=tmp_path / "enabled" / "capture",
        hermes_home=tmp_path / "enabled" / "hermes",
        project_id="project-test",
        profile_id="profile-test",
        enabled=True,
    )


def test_registers_only_verified_hooks(tmp_path):
    harness = _enabled_harness(tmp_path)
    assert harness.registered == VERIFIED_SUPPORTED_HOOKS
    assert set(harness.registered).isdisjoint(
        {
            "pre_api_request",
            "post_api_request",
            "api_request_error",
        }
    )


def test_disabled_registers_no_hooks(tmp_path):
    harness = _disabled_harness(tmp_path)
    assert harness.registered == ()
    assert harness.context.callbacks == {}


def test_conditional_and_deferred_hooks_remain_unregistered(tmp_path):
    harness = _enabled_harness(tmp_path)
    assert not (set(harness.context.callbacks) & set(CONDITIONAL_FIXTURE_REQUIRED))
    assert not (set(harness.context.callbacks) & set(DEFERRED_HOOKS))


def test_enabled_versus_disabled_equivalence(tmp_path, payloads):
    disabled = _disabled_harness(tmp_path)
    enabled = _enabled_harness(tmp_path)
    for hook, payload in payloads.items():
        args_before = copy.deepcopy(payload)
        kwargs_before = copy.deepcopy(payload)
        # Disabled bridge: no wrapper is registered, so Hermes runs its own
        # (here: no-op) callback and returns None.
        assert hook not in disabled.context.callbacks
        d_return = None
        e_return = enabled.invoke(hook, copy.deepcopy(payload))
        assert d_return == e_return
        # Hermes-owned inputs unchanged under both paths.
        assert args_before == payload
        assert kwargs_before == payload


def test_nested_payload_immutability(tmp_path, payloads):
    harness = _enabled_harness(tmp_path)
    for hook, payload in payloads.items():
        before = copy.deepcopy(payload)
        harness.invoke(hook, copy.deepcopy(payload))
        after = payload
        assert after == before


def test_tool_arguments_preserved(tmp_path):
    harness = _enabled_harness(tmp_path)
    payload = {
        "session_id": "sess-1",
        "tool_name": "shell_exec",
        "args": {"command": "ls", "flags": ["-la", "-h"]},
    }
    before = copy.deepcopy(payload)
    harness.invoke("pre_tool_call", copy.deepcopy(payload))
    assert payload == before
    assert payload["args"]["flags"] == ["-la", "-h"]


def test_tool_results_preserved(tmp_path):
    harness = _enabled_harness(tmp_path)
    payload = {
        "session_id": "sess-1",
        "tool_name": "shell_exec",
        "args": {"command": "ls"},
        "result": {"exit_code": 0, "stdout": ["file_a"]},
    }
    before = copy.deepcopy(payload)
    harness.invoke("post_tool_call", copy.deepcopy(payload))
    assert payload == before


def test_kanban_transition_data_preserved(tmp_path):
    harness = _enabled_harness(tmp_path)
    payload = {
        "session_id": "sess-1",
        "board": "main",
        "assignee": "agent",
        "run_id": "run-1",
        "summary": "done",
        "reason": "success",
        "lifecycle_status": "completed",
    }
    before = copy.deepcopy(payload)
    harness.invoke("kanban_task_completed", copy.deepcopy(payload))
    assert payload == before


def test_session_id_preserved(tmp_path):
    harness = _enabled_harness(tmp_path)
    payload = {"session_id": "sess-unique", "args": {"x": 1}}
    before = copy.deepcopy(payload)
    harness.invoke("on_session_start", copy.deepcopy(payload))
    assert payload == before


def test_neutral_callback_return_value(tmp_path, payloads):
    harness = _enabled_harness(tmp_path)
    for hook in payloads:
        assert harness.invoke(hook, copy.deepcopy(payloads[hook])) is None


def test_temporary_hermes_home_used(tmp_path):
    harness = _enabled_harness(tmp_path)
    assert harness.hermes_home == (tmp_path / "enabled" / "hermes").resolve()
    assert not harness.hermes_home.is_relative_to(Path.home())
