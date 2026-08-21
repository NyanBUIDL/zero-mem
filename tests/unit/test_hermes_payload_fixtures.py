from __future__ import annotations

import copy

import pytest

from src.integration.bridge_config import (
    CONDITIONAL_FIXTURE_REQUIRED,
    DEFERRED_HOOKS,
    VERIFIED_SUPPORTED_HOOKS,
)
from src.integration.payload_mapping import map_hook_payload


@pytest.mark.parametrize("hook", VERIFIED_SUPPORTED_HOOKS)
def test_verified_supported_fixture_maps(hook: str) -> None:
    result = map_hook_payload(hook, {"session_id": "session-1"})
    assert result.status == "mapped"
    assert result.hook == hook
    assert result.event_class is not None
    assert result.payload is not None


@pytest.mark.parametrize("hook", CONDITIONAL_FIXTURE_REQUIRED)
def test_conditional_hooks_require_fixtures(hook: str) -> None:
    result = map_hook_payload(hook, {})
    assert result.status == "conditional_fixture_required"
    assert result.diagnostic_code == "conditional_fixture_required"
    assert result.payload is None


@pytest.mark.parametrize("hook", DEFERRED_HOOKS)
def test_deferred_hooks_are_not_mapped(hook: str) -> None:
    result = map_hook_payload(hook, {})
    assert result.status == "deferred"
    assert result.payload is None


def test_minimal_session_and_complete_tool_payloads() -> None:
    minimal = map_hook_payload("on_session_start", {})
    assert minimal.payload["session_id"] is None
    complete = map_hook_payload(
        "post_tool_call",
        {
            "tool_name": "terminal",
            "args": {"password": "SYNTHETIC_PASSWORD"},
            "result": {"value": "ok"},
            "status": "success",
            "duration": 1.5,
            "session_id": "s1",
            "turn_id": "t1",
            "task_id": "task1",
            "request_id": "req1",
            "trace_id": "trace1",
            "parent_trace_id": "parent1",
            "project_id": "project1",
            "profile_id": "profile1",
        },
    )
    assert complete.payload["tool_name"] == "terminal"
    assert complete.payload["session_id"] == "s1"
    assert complete.payload["request_id"] == "req1"
    assert "SYNTHETIC_PASSWORD" not in repr(complete.payload)


def test_kanban_fields_are_redacted_and_preserved() -> None:
    result = map_hook_payload(
        "kanban_task_blocked",
        {"task_id": "task1", "board": "engineering", "reason": {"password": "SYNTHETIC"}},
    )
    assert result.payload["task_id"] == "task1"
    assert "SYNTHETIC" not in repr(result.payload)


def test_source_payload_is_immutable() -> None:
    payload = {"args": {"api_key": "SYNTHETIC_KEY"}, "session_id": "s1"}
    before = copy.deepcopy(payload)
    result = map_hook_payload("pre_tool_call", payload)
    assert result.status == "mapped"
    assert payload == before


def test_missing_required_mapping_field_is_sanitized_failure() -> None:
    result = map_hook_payload("pre_tool_call", {"args": object()})
    assert result.status == "rejected"
    assert result.diagnostic_code == "unsafe_payload"
    assert "object at" not in repr(result)


def test_unsupported_and_cyclic_values_fail_closed() -> None:
    class Unsupported:
        def __repr__(self) -> str:
            return "SYNTHETIC_UNSAFE_REPR"

    unsupported = map_hook_payload("pre_tool_call", {"args": Unsupported()})
    assert unsupported.status == "rejected"
    assert "SYNTHETIC_UNSAFE_REPR" not in repr(unsupported)

    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic
    cycle_result = map_hook_payload("pre_tool_call", cyclic)
    assert cycle_result.status == "rejected"
    assert cycle_result.diagnostic_code == "cyclic_payload"


def test_identity_is_explicit_and_missing_values_are_null() -> None:
    result = map_hook_payload("on_session_start", {"message": "project cwd / secret"})
    assert result.payload["project_id"] is None
    assert result.payload["profile_id"] is None
    assert result.payload["session_id"] is None


def test_pre_post_events_do_not_pair_heuristically() -> None:
    pre = map_hook_payload("pre_tool_call", {"tool_name": "same", "turn_id": "t1"})
    post = map_hook_payload("post_tool_call", {"tool_name": "same", "turn_id": "t2"})
    assert pre.payload["turn_id"] == "t1"
    assert post.payload["turn_id"] == "t2"
    assert pre.payload.get("event_id") != post.payload.get("event_id")


def test_mapping_is_deterministic_when_host_occurrence_identity_is_present() -> None:
    left = map_hook_payload("post_tool_call", {"status": "ok", "tool_name": "x", "tool_call_id": "tc-1"})
    right = map_hook_payload("post_tool_call", {"tool_call_id": "tc-1", "tool_name": "x", "status": "ok"})
    assert left.payload == right.payload
    assert left.event_type == right.event_type


def test_mapping_generates_distinct_occurrences_without_host_identity() -> None:
    left = map_hook_payload("post_tool_call", {"status": "ok", "tool_name": "x"})
    right = map_hook_payload("post_tool_call", {"status": "ok", "tool_name": "x"})
    assert left.payload["event_id"] != right.payload["event_id"]


def test_no_persistence_side_effect() -> None:
    result = map_hook_payload("on_session_start", {"session_id": "s1"})
    assert result.status == "mapped"
    assert not hasattr(result, "store")


def test_no_llm_or_network_dependency() -> None:
    result = map_hook_payload("on_session_end", {"session_id": "s1"})
    assert result.status == "mapped"
