from __future__ import annotations

import copy
import json

import pytest

from src.capture.adapter import deserialize_envelope, normalize_event, serialize_envelope
from src.capture.event_types import (
    DEFERRED_EVENT_CLASSES,
    EVENT_CLASS_REGISTRY,
    SUPPORTED_EVENT_CLASSES,
    EventType,
)
from src.capture.validation import validate_envelope


def test_valid_minimal_envelope() -> None:
    envelope = normalize_event({}, sequence=0, event_type=EventType.SYSTEM_EVENT, source="test")
    validate_envelope(envelope)
    assert envelope["profile_id"] is None
    assert envelope["project_id"] is None
    assert envelope["schema_version"] == 1


def test_valid_complete_envelope() -> None:
    envelope = normalize_event(
        {
            "event_id": "event-1",
            "trace_id": "trace-1",
            "session_id": "session-1",
            "task_id": "task-1",
            "turn_id": "turn-1",
            "parent_trace_id": "trace-0",
            "relation_ids": ("trace-0",),
            "sanitized_content": {"result": "ok"},
        },
        sequence=4,
        event_type=EventType.TOOL_OBSERVATION,
        source="hermes.post_tool_call",
        profile_id="developer",
        project_id="external-zeromem",
    )
    assert envelope["event_id"] == "event-1"
    assert envelope["relation_ids"] == ("trace-0",)


def test_missing_required_field_rejected() -> None:
    envelope = normalize_event({}, sequence=0, event_type=EventType.SYSTEM_EVENT, source="test")
    del envelope["source"]
    with pytest.raises(ValueError, match="missing required fields"):
        validate_envelope(envelope)


def test_invalid_event_type_rejected() -> None:
    with pytest.raises(ValueError, match="event_type"):
        normalize_event({}, sequence=0, event_type="not-an-event", source="test")


def test_invalid_timestamp_rejected() -> None:
    envelope = normalize_event({}, sequence=0, event_type=EventType.SYSTEM_EVENT, source="test")
    envelope["created_at"] = "2026-08-05T00:00:00+00:00"
    with pytest.raises(ValueError, match="RFC3339 UTC"):
        validate_envelope(envelope)


@pytest.mark.parametrize("field,value", [("sensitivity", "top_secret"), ("retention", "forever")])
def test_invalid_policy_value_rejected(field: str, value: str) -> None:
    envelope = normalize_event({}, sequence=0, event_type=EventType.SYSTEM_EVENT, source="test")
    envelope[field] = value
    with pytest.raises(ValueError, match="invalid value"):
        validate_envelope(envelope)


def test_optional_fields_are_explicit_null_or_empty_tuple() -> None:
    envelope = normalize_event({}, sequence=0, event_type=EventType.SYSTEM_EVENT, source="test")
    assert envelope["session_id"] is None
    assert envelope["profile_id"] is None
    assert envelope["project_id"] is None
    assert envelope["relation_ids"] == ()


def test_deterministic_serialization_and_round_trip() -> None:
    envelope = normalize_event({"b": 2, "a": 1}, sequence=0, event_type=EventType.SYSTEM_EVENT, source="test")
    first = serialize_envelope(envelope)
    second = serialize_envelope(deserialize_envelope(first))
    assert first == second
    assert json.loads(first)["schema_version"] == 1


def test_source_payload_is_not_mutated() -> None:
    payload = {"nested": {"value": "original"}}
    before = copy.deepcopy(payload)
    normalize_event(payload, sequence=0, event_type=EventType.SYSTEM_EVENT, source="test")
    assert payload == before


def test_assistant_claim_cannot_become_verified_state_implicitly() -> None:
    envelope = normalize_event(
        {"message": "task complete"},
        sequence=0,
        event_type=EventType.ASSISTANT_CLAIM,
        source="assistant",
    )
    assert envelope["verification_status"] == "none"
    assert envelope["lifecycle_status"] == "observed"
    envelope["lifecycle_status"] = "active"
    with pytest.raises(ValueError, match="assistant_claim"):
        validate_envelope(envelope)


def test_supported_and_deferred_event_class_registry() -> None:
    assert "pre_tool_call" in SUPPORTED_EVENT_CLASSES
    assert "file_operations" in DEFERRED_EVENT_CLASSES
    assert EVENT_CLASS_REGISTRY["supported"] == SUPPORTED_EVENT_CLASSES
    assert EVENT_CLASS_REGISTRY["deferred"] == DEFERRED_EVENT_CLASSES


def test_schema_version_behavior() -> None:
    envelope = normalize_event({}, sequence=0, event_type=EventType.SYSTEM_EVENT, source="test")
    envelope["schema_version"] = 999
    with pytest.raises(ValueError, match="schema_version"):
        validate_envelope(envelope)
