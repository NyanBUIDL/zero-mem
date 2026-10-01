"""Pre-register secret scan (DEF-049): decide BEFORE a blob is stored whether content carries a credential.

The corpus path used to store raw source bytes in the blob store first and scan extracted text
afterwards, so a rejected document still left its secret on disk. Callers run ``scan_bytes`` /
``assert_bytes_safe`` (or the text variants) on the bytes they are about to persist, and only
store them when the verdict is safe.

Verdicts come from the central redactor (``redact_payload``), so they always agree with
``src.corpus.redact.scan_extracted_text``. Bytes are decoded best-effort: a UTF-8 view (invalid
bytes replaced) and, when NUL bytes are present, a view with the NULs removed, which exposes the
ASCII content of UTF-16/UTF-32 text with or without a BOM. Credentials are ASCII, so this finds
them in any of those encodings without guessing the encoding. Zip containers (docx/xlsx/pptx and
anything else with a zip signature) are opened by ``scan_zip_members``, which scans EVERY member
(and nested zips) under bounded limits and fails closed when it cannot finish; PDFs and images are
scanned as raw bytes only.

Nothing here logs, stores, or returns the matched value: results and errors carry fixed codes and
rule ids only. No network, no LLM, no filesystem access.
"""
from __future__ import annotations

import io
import zipfile
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


MAX_ZIP_DEPTH = 3
_ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06")
_UNSCANNABLE = PrescanResult(safe=False, reason="container_unscannable")


def looks_like_zip(content: bytes) -> bool:
    return bytes(content[:4]) in _ZIP_MAGICS


def scan_zip_members(
    content: bytes,
    *,
    max_entries: int | None = None,
    max_total_uncompressed: int | None = None,
    max_member_bytes: int | None = None,
    _depth: int = 0,
    _budget: list | None = None,
) -> PrescanResult:
    """Scan EVERY member of a zip container (decompressed; nested zips recursively).

    Bounds are the OOXML adapters' (entry count, total/member uncompressed size) plus a nesting
    depth. Anything that cannot be scanned completely (unreadable, encrypted, over a bound, too
    deep) is UNSAFE with reason ``container_unscannable``: the caller must not store it.
    """
    from src.corpus.adapters import _ooxml

    max_entries = _ooxml.DEFAULT_MAX_ENTRIES if max_entries is None else max_entries
    max_total = _ooxml.DEFAULT_MAX_TOTAL_UNCOMPRESSED if max_total_uncompressed is None else max_total_uncompressed
    max_member = _ooxml.DEFAULT_MAX_MEMBER_BYTES if max_member_bytes is None else max_member_bytes
    if _depth > MAX_ZIP_DEPTH:
        return _UNSCANNABLE
    budget = _budget if _budget is not None else [max_entries, max_total]  # shared across nesting levels
    try:
        zf = _ooxml.open_package(bytes(content), max_entries=budget[0], max_total_uncompressed=budget[1])
        infos = zf.infolist()
    except Exception as exc:
        if str(exc).startswith("not a readable zip"):
            # Not a zip at all (corrupt/truncated): there are no compressed members to hide anything in, the raw
            # bytes were already scanned, and the format adapter rejects it as a corrupt source.
            return PrescanResult(safe=True)
        return _UNSCANNABLE
    budget[0] -= len(infos)
    budget[1] -= sum(max(i.file_size, 0) for i in infos)
    if budget[0] < 0 or budget[1] < 0:
        return _UNSCANNABLE
    rules: set[str] = set()
    secret = False
    with zf:
        for info in infos:
            if info.is_dir():
                continue
            try:
                data = _ooxml.read_member(zf, info.filename, max_bytes=max_member)
            except Exception:
                return _UNSCANNABLE
            verdict = scan_bytes(data)
            if not verdict.safe:
                secret = True
                rules.update(verdict.rule_ids)
                continue
            if looks_like_zip(data):
                inner = scan_zip_members(data, max_entries=max_entries, max_total_uncompressed=max_total,
                                         max_member_bytes=max_member, _depth=_depth + 1, _budget=budget)
                if not inner.safe:
                    if inner.reason == "container_unscannable":
                        return inner
                    secret = True
                    rules.update(inner.rule_ids)
    if secret:
        return PrescanResult(safe=False, rule_ids=tuple(sorted(rules)), reason="secret_detected")
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
    "MAX_ZIP_DEPTH", "assert_bytes_safe", "assert_text_safe", "looks_like_zip", "scan_bytes", "scan_text",
    "scan_zip_members",
]
