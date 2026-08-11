"""M10.2 — corpus redaction/sensitivity boundary (fail-closed).

Distinguishes three representations and never lets a secret escape the storage
boundary into a searchable/rendered/projected representation:

- SOURCE BYTES      : the raw artifact (stored in the blob store; access-gated).
- EXTRACTED TEXT    : coarse structural units (derived from source + parser).
- SEARCHABLE/RENDERED: any downstream representation (M10.5+; NOT built here).

Authorization (M5) controls *whether* a resource may influence a request.
Redaction (here) controls *what representation* may leave the boundary.

This module reuses the existing M1 fail-closed ``redact_payload`` so corpus
redaction inherits the same non-disableable secret backstop as memory. Secret
text is NEVER stored in a derived extraction representation and is never exposed
to Hermes/EvidenceSet in M10.2 (ingestion/extraction only).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from src.redaction import RedactionRejected, redact_payload


@dataclass(frozen=True)
class RedactionOutcome:
    """Result of scanning an extracted representation for secrets."""

    safe: bool
    contained_secret: bool
    reason: Optional[str] = None
    rule_ids: tuple[str, ...] = ()


class CorpusRedactionError(RuntimeError):
    """Raised when a secret/shielded value is found and the caller requested
    fail-closed rejection (default). Never carries the raw matched value."""


def scan_extracted_text(text: str) -> RedactionOutcome:
    """Scan extracted text for secrets using the M1 fail-closed redactor.

    Returns a non-throwing outcome describing whether the text is safe to place
    into a derived/searchable representation. Does NOT mutate the input.
    """
    try:
        result = redact_payload({"text": text})
    except RedactionRejected as exc:
        msg = str(exc)
        return RedactionOutcome(safe=False, contained_secret=True, reason=msg)
    except Exception:
        # Any unexpected redactor failure fails closed.
        return RedactionOutcome(safe=False, contained_secret=True, reason="redaction_error")
    applied = bool(result.audit.applied)
    return RedactionOutcome(
        safe=not applied,
        contained_secret=applied,
        reason=None if not applied else "secret_detected",
        rule_ids=tuple(result.audit.rule_ids),
    )


def require_safe(text: str) -> str:
    """Fail closed if ``text`` contains a secret. Returns the original text when
    safe; raises ``CorpusRedactionError`` otherwise. Never returns redacted text
    silently into a derived representation in M10.2 — secret sources are
    rejected at the boundary, not quietly scrubbed-and-stored.
    """
    outcome = scan_extracted_text(text)
    if not outcome.safe:
        raise CorpusRedactionError(f"corpus_redaction_rejected: {outcome.reason}")
    return text


__all__ = ["RedactionOutcome", "CorpusRedactionError", "scan_extracted_text", "require_safe"]
