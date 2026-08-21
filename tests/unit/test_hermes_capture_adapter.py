from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

import pytest

from src.capture.validation import validate_envelope
from src.integration.capture_adapter import adapt_mapped_event
from src.integration.payload_mapping import map_hook_payload
from src.storage.capture_boundary import AppendResult, CaptureRejected


@dataclass
class FakeStore:
    result: Any = None
    calls: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        self.calls = []

    def append(self, event: dict[str, Any]) -> Any:
        assert self.calls is not None
        self.calls.append(copy.deepcopy(event))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result or AppendResult("appended", event["event_id"], 0, event["sanitized_content_hash"])


def mapped(hook: str = "post_tool_call", payload: dict[str, Any] | None = None):
    return map_hook_payload(hook, payload or {"session_id": "s1", "tool_name": "terminal", "result": {"ok": True}})


def test_successful_mapper_to_envelope_to_store_append() -> None:
    store = FakeStore()
    result = adapt_mapped_event(mapped(), store=store)
    assert result.code == "appended"
    assert len(store.calls) == 1
    validate_envelope(store.calls[0])
    assert "event_id" in result.safe_metadata


def test_store_receives_only_sanitized_nested_content() -> None:
    secret = "SYNTHETIC_ADAPTER_SECRET"
    store = FakeStore()
    result = adapt_mapped_event(mapped(payload={"args": {"api_key": secret}}), store=store)
    assert result.code == "appended"
    assert secret not in repr(store.calls)
    assert secret not in repr(result)


def test_redaction_rejection_does_not_persist() -> None:
    store = FakeStore()
    result = adapt_mapped_event(mapped(payload={"retention": "never_store", "password": "SYNTHETIC"}), store=store)
    assert result.code == "redaction_rejected"
    assert store.calls == []


@pytest.mark.parametrize("hook", ["pre_api_request", "file_operations"])
def test_unsupported_and_conditional_results_do_not_persist(hook: str) -> None:
    store = FakeStore()
    mapped_result = map_hook_payload(hook, {})
    result = adapt_mapped_event(mapped_result, store=store)
    assert result.code in {"conditional_fixture_required", "unsupported_hook"}
    assert store.calls == []


@pytest.mark.parametrize(
    ("hook", "payload", "event_type"),
    [
        ("pre_llm_call", {"session_id": "s", "turn_id": "t", "user_message": "hello"}, "user_statement"),
        ("post_llm_call", {"session_id": "s", "turn_id": "t", "assistant_response": "hi"}, "assistant_claim"),
    ],
)
def test_message_hooks_persist_with_semantic_event_type(hook, payload, event_type) -> None:
    store = FakeStore()
    mapped_result = map_hook_payload(hook, payload)
    result = adapt_mapped_event(mapped_result, store=store)
    assert result.code == "appended"
    assert len(store.calls) == 1
    assert store.calls[0]["event_type"] == event_type


def test_duplicate_event_id_and_content_hash_are_preserved() -> None:
    event = mapped()
    first = FakeStore(AppendResult("duplicate", "e1", 4, "sha256:x", "event_id"))
    result = adapt_mapped_event(event, store=first)
    assert result.code == "duplicate_event_id"
    second = FakeStore(AppendResult("duplicate", "e1", 4, "sha256:x", "content_hash"))
    result = adapt_mapped_event(event, store=second)
    assert result.code == "duplicate_content_hash"


def test_duplicate_does_not_advance_or_rewrite_store() -> None:
    store = FakeStore(AppendResult("duplicate", "e1", 0, "sha256:x", "event_id"))
    result = adapt_mapped_event(mapped(), store=store)
    assert result.sequence == 0
    assert len(store.calls) == 1


def test_source_payload_immutable_on_success_and_failure() -> None:
    payload = {"args": {"password": "SYNTHETIC"}, "session_id": "s1"}
    before = copy.deepcopy(payload)
    store = FakeStore()
    adapt_mapped_event(mapped(payload=payload), store=store)
    assert payload == before
    failing = FakeStore(CaptureRejected("raw failure"))
    adapt_mapped_event(mapped(payload=payload), store=failing)
    assert payload == before


def test_storage_failure_is_sanitized_and_isolated() -> None:
    result = adapt_mapped_event(mapped(), store=FakeStore(CaptureRejected("SYNTHETIC_RAW_ERROR")))
    assert result.code == "capture_failed"
    assert "SYNTHETIC_RAW_ERROR" not in repr(result)


def test_malformed_mapping_and_envelope_fail_without_store() -> None:
    store = FakeStore()
    result = adapt_mapped_event(None, store=store)
    assert result.code == "mapping_rejected"
    assert store.calls == []


def test_explicit_identity_and_correlation_preserved() -> None:
    event = mapped(payload={
        "event_id": "event-1", "trace_id": "trace-1", "session_id": "s1",
        "turn_id": "t1", "task_id": "task1", "request_id": "req1",
        "parent_trace_id": "parent1", "relation_ids": ["rel1"],
        "project_id": "project1", "profile_id": "profile1",
    })
    store = FakeStore()
    adapt_mapped_event(event, store=store)
    saved = store.calls[0]
    for field in ("event_id", "trace_id", "session_id", "turn_id", "task_id", "parent_trace_id", "relation_ids", "project_id", "profile_id"):
        assert saved[field] == event.payload[field]


def test_no_retry_or_dead_letter_behavior() -> None:
    class Store:
        def __init__(self): self.calls = 0
        def append(self, event):
            self.calls += 1
            raise CaptureRejected("failure")
    store = Store()
    result = adapt_mapped_event(mapped(), store=store)
    assert result.code == "capture_failed"
    assert store.calls == 1
    assert not hasattr(store, "write_dead_letter")


def test_adapter_has_no_hook_registration_or_llm_dependency() -> None:
    store = FakeStore()
    result = adapt_mapped_event(mapped("on_session_start", {"session_id": "s1"}), store=store)
    assert result.code == "appended"
    assert not hasattr(result, "register_hook")
