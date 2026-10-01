"""Project-owned deterministic redaction boundary."""

from .prescan import (
    PrescanRejected,
    PrescanResult,
    assert_bytes_safe,
    assert_text_safe,
    scan_bytes,
    scan_text,
)
from .redactor import (
    RedactionAudit,
    RedactionRejected,
    SanitizedPayload,
    redact_payload,
    supported_secret_patterns,
)

__all__ = [
    "PrescanRejected",
    "PrescanResult",
    "RedactionAudit",
    "RedactionRejected",
    "SanitizedPayload",
    "assert_bytes_safe",
    "assert_text_safe",
    "redact_payload",
    "scan_bytes",
    "scan_text",
    "supported_secret_patterns",
]
