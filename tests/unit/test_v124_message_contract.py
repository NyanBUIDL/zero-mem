from __future__ import annotations

from src.integration.payload_mapping import map_hook_payload


def test_pre_llm_is_user_statement_without_history_snapshot() -> None:
    result = map_hook_payload(
        "pre_llm_call",
        {
            "session_id": "session-1",
            "turn_id": "turn-1",
            "user_message": "Remember this decision",
            "conversation_history": [{"role": "user", "content": "old"}],
        },
    )
    assert result.status == "mapped"
    assert result.event_type == "user_statement"
    assert result.payload["actor"] == "user"
    assert result.payload["message"] == "Remember this decision"
    assert "conversation_history" not in result.payload["sanitized_content"]


def test_post_llm_is_assistant_claim_without_recopying_user_or_history() -> None:
    result = map_hook_payload(
        "post_llm_call",
        {
            "session_id": "session-1",
            "turn_id": "turn-1",
            "user_message": "question",
            "assistant_response": "unverified answer",
            "conversation_history": [{"role": "assistant", "content": "old"}],
        },
    )
    assert result.status == "mapped"
    assert result.event_type == "assistant_claim"
    assert result.payload["actor"] == "assistant"
    assert result.payload["message"] == "unverified answer"
    assert "conversation_history" not in result.payload["sanitized_content"]
    assert "user_message" not in result.payload["sanitized_content"]


def test_same_turn_is_retry_stable_but_user_and_assistant_are_distinct() -> None:
    user_a = map_hook_payload("pre_llm_call", {"session_id": "s", "turn_id": "t", "user_message": "same"})
    user_b = map_hook_payload("pre_llm_call", {"session_id": "s", "turn_id": "t", "user_message": "same"})
    assistant = map_hook_payload("post_llm_call", {"session_id": "s", "turn_id": "t", "assistant_response": "same"})
    assert user_a.payload["event_id"] == user_b.payload["event_id"]
    assert user_a.payload["event_id"] != assistant.payload["event_id"]


def test_public_messages_have_public_provenance_and_semantic_types() -> None:
    user = map_hook_payload("public_user_message", {"text": "hello"})
    assistant = map_hook_payload("public_assistant_message", {"text": "hi"})
    assert (user.source, user.event_type, user.payload["actor"]) == (
        "public.user_message", "user_statement", "user"
    )
    assert (assistant.source, assistant.event_type, assistant.payload["actor"]) == (
        "public.assistant_message", "assistant_claim", "assistant"
    )
    assert user.payload["event_id"] != assistant.payload["event_id"]


def test_skill_and_subagent_hooks_preserve_provenance_fields() -> None:
    skill = map_hook_payload(
        "on_skill_lifecycle",
        {"session_id": "s", "action": "activated", "skill_name": "pdf", "use_count": 2},
    )
    child = map_hook_payload(
        "subagent_start",
        {"parent_session_id": "s", "parent_turn_id": "t", "child_subagent_id": "child-1", "child_role": "leaf"},
    )
    assert skill.status == "mapped" and skill.payload["skill_name"] == "pdf"
    assert child.status == "mapped" and child.payload["child_subagent_id"] == "child-1"
