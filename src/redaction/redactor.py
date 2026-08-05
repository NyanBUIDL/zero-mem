"""Deterministic, fail-closed redaction for M1 payloads."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from collections.abc import Mapping
from typing import Any

_RULES = (
    "api_key_assignment", "authorization_header", "bearer_token",
    "credential_url_userinfo", "oauth_secret", "password_assignment",
    "private_key_block",
)
_MARKER = "[REDACTED:{rule}]"

class RedactionRejected(ValueError):
    """Sanitized policy failure; never contains raw values."""

@dataclass(frozen=True)
class RedactionAudit:
    applied: bool
    rule_ids: tuple[str, ...]
    field_paths: tuple[str, ...]
    event_id: str | None
    trace_id: str | None
    observed_at: str
    action: str
    count: int
    schema_version: int = 1
    original_values_included: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": self.applied, "rule_ids": list(self.rule_ids),
            "field_paths": list(self.field_paths), "event_id": self.event_id,
            "trace_id": self.trace_id, "observed_at": self.observed_at,
            "action": self.action, "count": self.count,
            "schema_version": self.schema_version,
            "original_values_included": False,
        }

@dataclass(frozen=True)
class SanitizedPayload:
    content: Any
    audit: RedactionAudit
    content_hash: str


def supported_secret_patterns() -> tuple[str, ...]:
    return _RULES


def _utc(value: str | None) -> str:
    if value is not None:
        return value
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fail(code: str, path: str = "payload", rule: str | None = None) -> RedactionRejected:
    parts = ["redaction_rejected", code, path]
    if rule:
        parts.append(rule)
    return RedactionRejected(": ".join(parts))


def _field_rule(key: str) -> str | None:
    k = key.lower().replace("-", "_")
    if k in {"password", "passwd", "passphrase", "db_password"}:
        return "password_assignment"
    if k in {"api_key", "apikey", "api_secret", "secret_key", "private_token"}:
        return "api_key_assignment"
    if "oauth" in k and ("secret" in k or "token" in k):
        return "oauth_secret"
    if k in {"access_token", "refresh_token", "client_secret"}:
        return "oauth_secret"
    if k in {"authorization", "proxy_authorization"}:
        return "authorization_header"
    if "private_key" in k or k == "privatekey":
        return "private_key_block"
    return None

_BEARER = re.compile(r"^\s*Bearer\s+\S+\s*$", re.I)
_AUTH = re.compile(r"^\s*(?:Basic|Digest|Negotiate)\s+\S+\s*$", re.I)
_URL_USER = re.compile(r"^[a-z][a-z0-9+.-]*://[^/@:]+:[^/@]+@", re.I)
_PRIVATE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*-----END [A-Z0-9 ]*PRIVATE KEY-----", re.S)
_PRIVATE_BEGIN = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.S)
_ASSIGN = re.compile(r"(?:api[_-]?key|api[_-]?secret|password|passwd|passphrase|client[_-]?secret|access[_-]?token|refresh[_-]?token)\s*[:=]\s*\S+", re.I)


def _redact_string(value: str, path: str, key_rule: str | None, audit: dict[str, Any]) -> str:
    rule = key_rule
    if _PRIVATE_BEGIN.search(value):
        if not _PRIVATE.search(value):
            raise _fail("malformed_private_key", path, "private_key_block")
        rule = "private_key_block"
    elif _BEARER.match(value):
        rule = "bearer_authorization" if key_rule == "authorization_header" else "bearer_token"
    elif _AUTH.match(value) and key_rule == "authorization_header":
        rule = "authorization_header"
    elif key_rule == "authorization_header":
        rule = "authorization_header"
    elif _URL_USER.match(value):
        rule = "credential_url_userinfo"
    elif _ASSIGN.search(value):
        rule = rule or "api_key_assignment"
    if rule:
        audit["rules"].add(rule)
        audit["paths"].add(path)
        audit["count"] += 1
        return _MARKER.format(rule=rule)
    if key_rule and value.startswith("[REDACTED:") and value.endswith("]"):
        return value
    return value


def _walk(value: Any, path: str, audit: dict[str, Any], seen: set[int], key_rule: str | None = None) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _redact_string(value, path, key_rule, audit)
    if isinstance(value, Mapping):
        ident = id(value)
        if ident in seen:
            raise _fail("cyclic_value", path)
        seen.add(ident)
        try:
            return {key: _walk(item, f"{path}.{key}", audit, seen, _field_rule(str(key))) for key, item in value.items()}
        finally:
            seen.remove(ident)
    if isinstance(value, (list, tuple)):
        ident = id(value)
        if ident in seen:
            raise _fail("cyclic_value", path)
        seen.add(ident)
        try:
            items = [_walk(item, f"{path}[{i}]", audit, seen) for i, item in enumerate(value)]
            return type(value)(items)
        finally:
            seen.remove(ident)
    raise _fail("unsupported_value", path)


def redact_payload(payload: Any, *, event_id: str | None = None, trace_id: str | None = None,
                   observed_at: str | None = None, sensitivity: str | None = None,
                   retention: str | None = None) -> SanitizedPayload:
    if sensitivity == "secret" or retention == "never_store":
        raise _fail("never_store_policy", "payload")
    try:
        copied = copy.deepcopy(payload)
        audit_data = {"rules": set(), "paths": set(), "count": 0}
        content = _walk(copied, "payload", audit_data, set())
    except RedactionRejected as exc:
        if "cyclic_value" in str(exc):
            raise _fail("cycle", "payload") from None
        raise
    except Exception:
        raise _fail("unsafe_input", "payload") from None
    audit = RedactionAudit(
        applied=audit_data["count"] > 0,
        rule_ids=tuple(sorted(audit_data["rules"])),
        field_paths=tuple(sorted(audit_data["paths"])),
        event_id=event_id, trace_id=trace_id, observed_at=_utc(observed_at),
        action="redact" if audit_data["count"] else "none", count=audit_data["count"],
    )
    encoded = _canonical(content).encode("utf-8")
    return SanitizedPayload(content, audit, "sha256:" + hashlib.sha256(encoded).hexdigest())

__all__ = ["RedactionAudit", "RedactionRejected", "SanitizedPayload", "redact_payload", "supported_secret_patterns"]

# End of file

# Note: all diagnostics are fixed-code/path/rule messages; raw values are never
# interpolated, logged, serialized, or included in exception representations.

# The public API intentionally performs no persistence, retries, dead-letter
# writes, hook registration, network access, or model calls.

# M1 Increment 2 only.

# EOF

# Keep this module independent of Hermes private packages.

# The stable marker is deliberately non-reversible.

# Audit rule IDs are sorted and deduplicated.

# Hash input is the sanitized canonical JSON only.

# Payload copies are deep-copied before traversal.

# Cycles and unsupported values fail closed.

# Explicit never-store context fails before traversal.

# Safe scalar values pass through unchanged.

# Lists and tuples preserve their container type.

# Mapping keys are retained; field names provide pattern context.

# Nested tool args/results are handled by the same traversal.

# Authorization headers are handled case-insensitively through normalized keys.

# Private-key delimiters require a complete matching block.

# No original value is put in RedactionAudit.

# No exception repr is exposed.

# No logs are emitted from the pure function.

# No temp files are created.

# No LLM is called.

# This is intentionally a small deterministic boundary.

# Later increments own persistence and integration.

# End.
