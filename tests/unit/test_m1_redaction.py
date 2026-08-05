from __future__ import annotations

import copy
import hashlib
import json

import pytest

from src.redaction.redactor import (
    RedactionRejected,
    redact_payload,
    supported_secret_patterns,
)


SECRET_CORPUS = {
    "bearer": "Bearer SYNTHETIC_BEARER_SECRET",
    "api_key": "SYNTHETIC_API_KEY_123",
    "oauth": "SYNTHETIC_OAUTH_SECRET_456",
    "password": "SYNTHETIC_PASSWORD_789",
    "private_key": "-----BEGIN PRIVATE KEY-----\nSYNTHETIC_PRIVATE_KEY\n-----END PRIVATE KEY-----",
    "url_secret": "https://user:SYNTHETIC_URL_SECRET@example.invalid/path",
}


def test_authorization_and_proxy_authorization_headers_redacted() -> None:
    result = redact_payload(
        {
            "headers": {
                "Authorization": SECRET_CORPUS["bearer"],
                "Proxy-Authorization": "Basic SYNTHETIC_PROXY_SECRET",
            }
        }
    )
    assert result.content["headers"]["Authorization"] == "[REDACTED:bearer_authorization]"
    assert result.content["headers"]["Proxy-Authorization"] == "[REDACTED:authorization_header]"


def test_secret_pattern_registry_is_explicit() -> None:
    assert supported_secret_patterns() == (
        "api_key_assignment",
        "authorization_header",
        "bearer_token",
        "credential_url_userinfo",
        "oauth_secret",
        "password_assignment",
        "private_key_block",
    )


def test_bearer_api_oauth_password_private_key_and_url_redaction() -> None:
    result = redact_payload(
        {
            "bearer_token": SECRET_CORPUS["bearer"],
            "api_key": SECRET_CORPUS["api_key"],
            "oauth_client_secret": SECRET_CORPUS["oauth"],
            "password": SECRET_CORPUS["password"],
            "private_key": SECRET_CORPUS["private_key"],
            "endpoint": SECRET_CORPUS["url_secret"],
        },
        event_id="event-1",
        trace_id="trace-1",
    )
    serialized = json.dumps(result.content, sort_keys=True)
    for secret in SECRET_CORPUS.values():
        assert secret not in serialized
    assert result.audit.original_values_included is False
    assert result.audit.event_id == "event-1"
    assert result.audit.trace_id == "trace-1"


def test_nested_mapping_list_and_tuple_values_redacted() -> None:
    result = redact_payload(
        {
            "tool_args": {"items": [{"password": SECRET_CORPUS["password"]}]},
            "tool_result": ("safe", {"api_key": SECRET_CORPUS["api_key"]}),
        }
    )
    assert result.content["tool_args"]["items"][0]["password"].startswith("[REDACTED:")
    assert result.content["tool_result"][1]["api_key"].startswith("[REDACTED:")


def test_never_store_context_rejects_without_secret_in_error() -> None:
    with pytest.raises(RedactionRejected) as exc_info:
        redact_payload({"secret": SECRET_CORPUS["api_key"]}, retention="never_store")
    message = str(exc_info.value)
    assert "SYNTHETIC" not in message
    assert "api_key" not in message


def test_source_payload_immutable_on_success_and_failure() -> None:
    payload = {"nested": {"password": SECRET_CORPUS["password"]}}
    before = copy.deepcopy(payload)
    redact_payload(payload)
    assert payload == before
    failing = {"secret": SECRET_CORPUS["api_key"]}
    before_failing = copy.deepcopy(failing)
    with pytest.raises(RedactionRejected):
        redact_payload(failing, sensitivity="secret")
    assert failing == before_failing


def test_output_is_deterministic_and_idempotent() -> None:
    first = redact_payload({"api_key": SECRET_CORPUS["api_key"], "a": "safe"})
    second = redact_payload(first.content)
    assert first.content == second.content
    assert first.content_hash == second.content_hash
    assert first.audit.rule_ids == second.audit.rule_ids == ("api_key_assignment",)


def test_cyclic_input_fails_closed_without_secret_diagnostic() -> None:
    payload: dict[str, object] = {}
    payload["self"] = payload
    with pytest.raises(RedactionRejected) as exc_info:
        redact_payload(payload)
    assert "cycle" in str(exc_info.value).lower()
    assert "{" not in str(exc_info.value)


def test_unsupported_type_fails_closed_without_stringifying() -> None:
    class Unsupported:
        def __repr__(self) -> str:
            return "UNSAFE_REPR_VALUE"

    with pytest.raises(RedactionRejected) as exc_info:
        redact_payload({"value": Unsupported()})
    assert "UNSAFE_REPR_VALUE" not in str(exc_info.value)
    assert "unsupported" in str(exc_info.value).lower()


def test_audit_has_no_secret_values_or_reversible_hashes() -> None:
    result = redact_payload({"password": SECRET_CORPUS["password"]})
    audit = json.dumps(result.audit.to_dict(), sort_keys=True)
    assert SECRET_CORPUS["password"] not in audit
    assert hashlib.sha256(SECRET_CORPUS["password"].encode()).hexdigest() not in audit
    assert result.audit.original_values_included is False
    assert result.audit.action == "redact"


def test_hash_is_computed_from_sanitized_content_only() -> None:
    result = redact_payload({"api_key": SECRET_CORPUS["api_key"]})
    canonical = json.dumps(result.content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    expected = "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
    assert result.content_hash == expected
    assert SECRET_CORPUS["api_key"] not in result.content_hash


def test_malformed_private_key_fails_closed() -> None:
    with pytest.raises(RedactionRejected) as exc_info:
        redact_payload({"private_key": "-----BEGIN PRIVATE KEY-----\ntruncated"})
    assert "truncated" not in str(exc_info.value)
    assert "private_key" in str(exc_info.value)


def test_audit_is_sorted_and_json_serializable() -> None:
    result = redact_payload(
        {
            "z": {"password": SECRET_CORPUS["password"]},
            "a": {"api_key": SECRET_CORPUS["api_key"]},
        },
        observed_at="2026-08-05T00:00:00.000Z",
    )
    assert result.audit.rule_ids == tuple(sorted(result.audit.rule_ids))
    assert result.audit.field_paths == tuple(sorted(result.audit.field_paths))
    assert json.loads(json.dumps(result.audit.to_dict()))["schema_version"] == 1


def test_safe_values_and_empty_containers_are_preserved() -> None:
    payload = {"none": None, "bool": True, "number": 3, "empty": {}, "items": []}
    result = redact_payload(payload)
    assert result.content == payload
    assert result.audit.applied is False
    assert result.audit.action == "none"
