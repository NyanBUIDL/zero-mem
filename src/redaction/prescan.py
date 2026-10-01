"""Pre-register secret scan (DEF-049): decide BEFORE a blob is stored whether content carries a credential.

The corpus path used to store raw source bytes in the blob store first and scan extracted text
afterwards, so a rejected document still left its secret on disk. Callers run ``scan_bytes`` /
``assert_bytes_safe`` (or the text variants) on the bytes they are about to persist, and only
store them when the verdict is safe.

Verdicts come from the central redactor (``redact_payload``), so they always agree with
``src.corpus.redact.scan_extracted_text``. Bytes are decoded best-effort: a UTF-8 view (invalid
bytes replaced) and, when NUL bytes are present, a view with the NULs removed, which exposes the
ASCII content of UTF-16/UTF-32 text with or without a BOM. Credentials are ASCII, so this finds
them in any of those encodings without guessing the encoding. Compressed containers (docx/xlsx
zip members, images) are NOT opened here; scan their extracted text instead.

Nothing here logs, stores, or returns the matched value: results and errors carry fixed codes and
rule ids only. No network, no LLM, no filesystem access.
"""
from __future__ import annotations

from dataclasses import dataclass

from .redactor import RedactionRejected, redact_payload


@dataclass(frozen=True)
class PrescanResult:
    """Sanitized verdict of a pre-register scan."""

    safe: bool
    rule_ids: tuple[str, ...] = ()
    reason: str | None = None


class PrescanRejected(RedactionRejected):
    """Content carries a credential; the message holds rule ids only, never the value."""


def _verdict(text: str) -> PrescanResult:
    try:
        result = redact_payload({"text": text})
    except RedactionRejected as exc:
        return PrescanResult(safe=False, reason=str(exc))  # fixed-code message by construction
    except Exception:
        return PrescanResult(safe=False, reason="redaction_error")  # fail closed
    if result.audit.applied:
        return PrescanResult(safe=False, rule_ids=tuple(result.audit.rule_ids), reason="secret_detected")
    return PrescanResult(safe=True)


def scan_text(text: str) -> PrescanResult:
    """Scan decoded text. Does not mutate or return the input."""
    if not isinstance(text, str):
        raise TypeError("scan_text expects str")
    return _verdict(text)


def scan_bytes(content: bytes) -> PrescanResult:
    """Scan raw bytes best-effort (see module docstring). Unsafe if ANY decoded view is unsafe."""
    if not isinstance(content, (bytes, bytearray, memoryview)):
        raise TypeError("scan_bytes expects bytes-like content")
    raw = bytes(content)
    views = [raw.decode("utf-8", errors="replace")]
    if b"\x00" in raw:
        views.append(raw.replace(b"\x00", b"").decode("utf-8", errors="replace"))
    rules: set[str] = set()
    reasons: list[str] = []
    for view in views:
        verdict = _verdict(view)
        if not verdict.safe:
            rules.update(verdict.rule_ids)
            if verdict.reason and verdict.reason not in reasons:
                reasons.append(verdict.reason)
    if reasons:
        return PrescanResult(safe=False, rule_ids=tuple(sorted(rules)), reason=reasons[0])
    return PrescanResult(safe=True)


def _reject(result: PrescanResult) -> PrescanRejected:
    reason = result.reason or "secret_detected"
    if reason.startswith("redaction_rejected"):
        return PrescanRejected(reason)  # already a fixed-code redactor message
    parts = ["redaction_rejected", reason]
    if result.rule_ids:
        parts.append(",".join(result.rule_ids))
    return PrescanRejected(": ".join(parts))


def assert_text_safe(text: str) -> None:
    """Raise ``PrescanRejected`` if ``text`` carries a credential; return None when safe."""
    result = scan_text(text)
    if not result.safe:
        raise _reject(result)


def assert_bytes_safe(content: bytes) -> None:
    """Raise ``PrescanRejected`` if ``content`` carries a credential; return None when safe."""
    result = scan_bytes(content)
    if not result.safe:
        raise _reject(result)


__all__ = [
    "PrescanRejected", "PrescanResult",
    "assert_bytes_safe", "assert_text_safe", "scan_bytes", "scan_text",
]
