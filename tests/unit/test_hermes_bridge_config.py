from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.integration.bridge_config import (
    CONDITIONAL_FIXTURE_REQUIRED,
    DEFERRED_HOOKS,
    VERIFIED_SUPPORTED_HOOKS,
    BridgeConfig,
    BridgeMetrics,
    event_class_for_hook,
    registry_snapshot,
)


def test_bridge_disabled_by_default() -> None:
    config = BridgeConfig(capture_root=Path("/tmp/zero-mem-increment-4-1"))
    assert config.enabled is False


def test_explicit_enable_and_identity_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERMES_PROJECT_ID", "environment-project")
    monkeypatch.setenv("HERMES_PROFILE_ID", "environment-profile")
    config = BridgeConfig(
        enabled=True,
        project_id="explicit-project",
        profile_id="explicit-profile",
        capture_root=tmp_path / "capture",
        hermes_home=tmp_path / "hermes",
    )
    assert config.enabled is True
    assert config.project_id == "explicit-project"
    assert config.profile_id == "explicit-profile"
    assert config.hermes_home == (tmp_path / "hermes").resolve()


def test_environment_identity_is_optional_and_no_unapproved_inference(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HERMES_PROJECT_ID", "approved-project")
    config = BridgeConfig(capture_root=tmp_path, use_environment_identity=False)
    assert config.project_id is None
    assert config.profile_id is None


def test_missing_identity_is_null_and_not_inferred(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HERMES_PROJECT_ID", raising=False)
    monkeypatch.delenv("HERMES_PROFILE_ID", raising=False)
    config = BridgeConfig(capture_root=tmp_path)
    assert config.project_id is None
    assert config.profile_id is None


def test_safe_capture_root_rejects_real_home(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="real home"):
        BridgeConfig(capture_root=Path.home() / "forbidden")
    assert BridgeConfig(capture_root=tmp_path).capture_root == tmp_path.resolve()


def test_configuration_serialization_is_deterministic(tmp_path: Path) -> None:
    config = BridgeConfig(capture_root=tmp_path, hermes_home=tmp_path / "home")
    assert config.to_json() == config.to_json()
    assert json.loads(config.to_json())["enabled"] is False


def test_supported_registry_exactness() -> None:
    assert VERIFIED_SUPPORTED_HOOKS == (
        "on_session_start", "on_session_end", "on_session_finalize",
        "pre_tool_call", "post_tool_call", "kanban_task_claimed",
        "kanban_task_completed", "kanban_task_blocked",
    )
    assert all(event_class_for_hook(hook) for hook in VERIFIED_SUPPORTED_HOOKS)


def test_conditional_registry_exactness() -> None:
    assert CONDITIONAL_FIXTURE_REQUIRED == (
        "on_session_reset", "pre_llm_call", "post_llm_call",
        "pre_api_request", "post_api_request", "api_request_error",
        "subagent_start", "subagent_stop",
    )
    assert all(event_class_for_hook(hook) for hook in CONDITIONAL_FIXTURE_REQUIRED)


def test_deferred_registry_exactness_and_behavior_hooks_excluded() -> None:
    assert "file_operations" in DEFERRED_HOOKS
    assert "skill_usage" in DEFERRED_HOOKS
    assert "generic_task_transitions" in DEFERRED_HOOKS
    assert "transform_llm_output" in DEFERRED_HOOKS
    assert "pre_approval_request" in DEFERRED_HOOKS
    assert event_class_for_hook("transform_llm_output") is None


def test_registry_has_no_duplicate_entries() -> None:
    snapshot = registry_snapshot()
    hooks = [hook for group in snapshot.values() for hook in group]
    assert len(hooks) == len(set(hooks))


def test_metrics_are_aggregate_and_sanitized() -> None:
    metrics = BridgeMetrics()
    metrics.record("post_tool_call", "captured")
    metrics.record("post_tool_call", "captured")
    metrics.record("file_operations", "deferred")
    value = metrics.to_dict()
    assert value == {"counts": [
        {"category": "deferred", "count": 1, "hook": "file_operations"},
        {"category": "captured", "count": 2, "hook": "post_tool_call"},
    ]}
    assert "payload" not in metrics.to_json()
    assert "secret" not in metrics.to_json()


def test_metrics_reject_unknown_hooks_and_unsafe_categories() -> None:
    metrics = BridgeMetrics()
    with pytest.raises(ValueError):
        metrics.record("unknown", "captured")
    with pytest.raises(ValueError):
        metrics.record("post_tool_call", "raw payload")


def test_configuration_does_not_call_network_or_llm(tmp_path: Path) -> None:
    config = BridgeConfig(capture_root=tmp_path)
    metrics = BridgeMetrics()
    assert config and metrics
