from __future__ import annotations

import copy

from src.integration.payload_mapping import map_hook_payload


def test_mapping_calls_redaction_before_semantic_mapping(monkeypatch):
    calls: list[str] = []

    def fake_redact(payload):
        calls.append("redact")
        class Audit:
            def to_dict(self):
                return {"applied": False}
        class Result:
            content = payload
            audit = Audit()
            content_hash = "sha256:synthetic"
        return Result()

    monkeypatch.setattr("src.integration.payload_mapping.redact_payload", fake_redact)
    result = map_hook_payload("pre_tool_call", {"tool_name": "terminal"})
    assert result.status == "mapped"
    assert calls == ["redact"]


def test_explicit_identity_and_relation_fields_are_preserved():
    payload = {
        "session_id": "s1", "turn_id": "t1", "task_id": "task1",
        "request_id": "req1", "trace_id": "trace1", "parent_trace_id": "parent1",
        "relation_ids": ["rel1"], "project_id": "project1", "profile_id": "profile1",
    }
    result = map_hook_payload("post_tool_call", payload)
    assert result.payload is not None
    for key, value in payload.items():
        assert result.payload[key] == value


def test_configured_identity_fills_only_missing_fields():
    result = map_hook_payload("on_session_start", {}, project_id="project1", profile_id="profile1")
    assert result.payload["project_id"] == "project1"
    assert result.payload["profile_id"] == "profile1"


def test_mapping_failure_has_fixed_sanitized_diagnostic():
    result = map_hook_payload("pre_tool_call", {"args": object()})
    assert result.status == "rejected"
    assert result.diagnostic_code in {"unsafe_payload", "mapping_failed"}
    assert "object at" not in repr(result)


def test_mapping_does_not_mutate_payload():
    payload = {"args": {"api_key": "SYNTHETIC_KEY"}, "session_id": "s1"}
    before = copy.deepcopy(payload)
    map_hook_payload("pre_tool_call", payload)
    assert payload == before


def test_mapping_result_has_no_persistence_fields():
    result = map_hook_payload("on_session_end", {"session_id": "s1"})
    assert not hasattr(result, "store")
    assert not hasattr(result, "append")
