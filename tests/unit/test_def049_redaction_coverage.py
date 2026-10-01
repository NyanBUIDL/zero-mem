"""DEF-049: the central redactor must detect vendor credentials ANYWHERE in text.

Every sample is synthetic and assembled at runtime from fragments so that no complete
credential-shaped literal sits in the repository (secret scanners, push protection).
"""
from __future__ import annotations

import base64
import json

import pytest

from src.corpus.redact import scan_extracted_text
from src.redaction import redact_payload, supported_secret_patterns


def _b64url(obj) -> str:
    raw = json.dumps(obj, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _jwt() -> str:
    return ".".join([
        _b64url({"alg": "HS256", "typ": "JWT"}),
        _b64url({"sub": "synthetic-user", "iat": 1700000000}),
        "c2lnbmF0dXJlLXNpZ25hdHVyZS1zaWduYXR1cmU",
    ])


A36 = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"      # 36 alnum
A24 = "A1b2C3d4E5f6G7h8I9j0K1l2"                  # 24 alnum

VENDOR = {
    "anthropic": "sk-" + "ant-api03-" + A24 + "-" + "XyZ",
    "openai_project": "sk-" + "proj-" + A36 + "_" + A24,
    "openai_generic": "sk-" + A24 + "abcd",
    "aws_access_key_id": "AK" + "IA" + "IOSFODNN7EXAMPLE",
    "github_ghp": "gh" + "p_" + A36,
    "github_gho": "gh" + "o_" + A36,
    "github_ghu": "gh" + "u_" + A36,
    "github_ghs": "gh" + "s_" + A36,
    "github_ghr": "gh" + "r_" + A36,
    "github_pat": "github_" + "pat_" + "11ABCDEFG0" + A24 + "_" + A36,
    "slack_bot": "xo" + "xb-" + "1234567890-" + "0987654321-" + A24,
    "slack_user": "xo" + "xp-" + "1234567890-" + A24,
    "slack_app": "xo" + "xa-" + "2-" + A24,
    "slack_refresh": "xo" + "xr-" + "1234567890-" + A24,
    "slack_session": "xo" + "xs-" + "1234567890-" + A24,
    "google_api": "AI" + "za" + "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6",
    "stripe_secret": "sk" + "_live_" + A24,
    "stripe_restricted": "rk" + "_live_" + A24,
    "jwt": _jwt(),
    "huggingface": "hf" + "_" + A36[:34],
}


def _embed(secret: str) -> str:
    return f"Remember for later: the value {secret} is what the deploy script uses, ok?"


def _unsafe(text: str) -> bool:
    outcome = scan_extracted_text(text)
    return (not outcome.safe) and outcome.contained_secret


@pytest.mark.parametrize("name", sorted(VENDOR))
def test_vendor_token_detected_mid_text(name):
    text = _embed(VENDOR[name])
    assert _unsafe(text), name
    # redact_payload replaces the string and never echoes the secret
    res = redact_payload({"note": text})
    assert res.audit.applied
    assert VENDOR[name] not in json.dumps(res.content)
    assert all(rule in supported_secret_patterns() for rule in res.audit.rule_ids)


@pytest.mark.parametrize("name", sorted(VENDOR))
def test_vendor_token_detected_on_its_own_and_multiline(name):
    assert _unsafe(VENDOR[name])
    assert _unsafe(f"line one\nline two\n{VENDOR[name]}\nline four\n")


def test_inline_authorization_bearer_header_detected():
    for text in (
        "curl -H 'Authorization: Bearer abc123DEF456ghi789' https://api.example.com/v1",
        'headers = {"Authorization": "Bearer abc123DEF456ghi789"}',
        "authorization: bearer abc123DEF456ghi789 was sent",
        "Authorization: Basic dXNlcjpwYXNzd29yZA==",
    ):
        assert _unsafe(text), text


def test_bare_bearer_token_mid_text_detected():
    assert _unsafe("send header Bearer " + "q7Zr2Lm9Xc4Vb6Nk1Jh8Tg3Fd5Sa0Pw and retry")
    # existing anchored behavior kept
    assert _unsafe("Bearer SYNTHETIC_BEARER_SECRET")


@pytest.mark.parametrize("text", [
    "connect to postgres://admin:s3cretpw@db.internal:5432/app for the migration",
    "mirror: https://user:SYNTHETIC_URL_SECRET@example.invalid/path (read-only)",
])
def test_url_with_embedded_credentials_detected_mid_text(text):
    assert _unsafe(text)


@pytest.mark.parametrize("text", [
    "export GITHUB_TOKEN=abcdef1234567890",
    "export OPENAI_API_KEY=\"not-a-real-key-value-123\"",
    "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCY0000000",
    "DB_PASSWORD=hunter2hunter2",
    "run it as: STRIPE_SECRET_KEY='abc 123 def' ./deploy.sh",
    "export slack_token=abcdef1234567890",
    "# .env\nAPI_TOKEN=abcdef1234567890\nPORT=8080\n",
    "SECRET_KEY=abc123abc123",
])
def test_env_style_secret_assignments_detected(text):
    assert _unsafe(text), text


@pytest.mark.parametrize("text", [
    "-----BEGIN PRIVATE KEY-----\nSYNTHETIC_PRIVATE_KEY\n-----END PRIVATE KEY-----",
    "password = SYNTHETIC_PASSWORD_789",
    "my api_key: SYNTHETIC_API_KEY_123 in the notes",
    "Bearer SYNTHETIC_BEARER_SECRET",
    "https://user:SYNTHETIC_URL_SECRET@example.invalid/path",
])
def test_existing_detections_preserved(text):
    assert _unsafe(text), text


def test_new_rule_ids_are_registered_and_audit_is_clean():
    rules = supported_secret_patterns()
    for expected in ("vendor_api_token", "jwt_token", "env_secret_assignment"):
        assert expected in rules
    res = redact_payload({"a": _embed(VENDOR["jwt"]), "b": _embed(VENDOR["github_ghp"])})
    assert res.audit.original_values_included is False
    dumped = json.dumps(res.audit.to_dict()) + json.dumps(res.content)
    assert VENDOR["jwt"] not in dumped and VENDOR["github_ghp"] not in dumped


def test_redaction_is_idempotent_for_new_rules():
    first = redact_payload({"a": _embed(VENDOR["anthropic"]), "b": "export MY_TOKEN=abcdef123456"})
    second = redact_payload(first.content)
    assert first.content == second.content
    assert second.audit.applied is False


# --- negative tests: ordinary prose / code must stay safe --------------------------------

SAFE_TEXTS = [
    "The task-force reviewed the risk-assessment-framework and ask-me-anything-about-everything notes.",
    "Alice prefers PostgreSQL for storage and deploys staging on fly.io every Friday.",
    "Please rotate the API key every 90 days and store the password in the vault, not in notes.",
    "The bearer of the message arrived late; bearer bonds are rare.",
    "AKIA is the prefix of AWS access key ids and ghp is the prefix of GitHub tokens.",
    "A JWT has three dot separated parts (header.payload.signature) and its header starts with eyJ.",
    "Use hf_hub_download from huggingface_hub to fetch the model; the hf_ prefix is for tokens.",
    "Slack tokens start with xoxb- or xoxp- followed by digits.",
    "commit 9fceb02d0ae598e95dc970b74767f19372d61af8 and sha256 "
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 are hashes.",
    "Email me at user@example.com or see https://example.com/docs/page?x=1 and "
    "ssh://git@github.com:org/repo.git, http://localhost:8080/path@home.",
    "Authorization: Bearer $TOKEN",
    "curl -H \"Authorization: Bearer ${API_TOKEN}\" https://api.example.com",
    "Authorization: Bearer <your-token-here>",
    "export PATH=/usr/local/bin:$PATH",
    "export NODE_ENV=production",
    "MAX_TOKENS=4096",
    "PRIMARY_KEY=id",
    "GITHUB_TOKEN=$GITHUB_TOKEN",
    "STRIPE_KEY=${STRIPE_KEY}",
    "SLACK_SECRET=<paste the value here>",
    "SERVICE_TOKEN=os.environ[\"SERVICE_TOKEN\"]",
    "sorted(items, key=len) and dict(key=value) and token=None",
    "Toi thich ca phe sua da; mat khau se duoc luu trong kho an toan.",
    "UUID 123e4567-e89b-12d3-a456-426614174000 and version v1.6.1 and TODO-2026-10-01.",
    "if SERVICE_TOKEN == expected_value: pass",
    "class Sensitivity(str, Enum):\n    SECRET = \"secret\"\n    TOKEN = 'token'\n    KEY = \"key\"\n",
    "SSH_KEY_PATH=/home/user/.ssh/id_rsa",
    "TOKEN_FILE=/run/secrets/service-token",
    "KEY_BINDINGS=ctrl+shift+p",
]


@pytest.mark.parametrize("text", SAFE_TEXTS)
def test_ordinary_text_is_not_flagged(text):
    outcome = scan_extracted_text(text)
    assert outcome.safe, (text, outcome.rule_ids)
    assert redact_payload({"t": text}).audit.applied is False
