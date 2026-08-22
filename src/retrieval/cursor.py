"""M3.2 — versioned, query-bound pagination cursor.

Deterministic, safe, and read-only:

- **Query fingerprint** ``qf``: SHA-256 over the canonical (sorted-key, None-excluded)
  JSON of the normalized filter set plus a constant deleted-exclusion marker. Equivalent
  structured queries produce the same ``qf``; different filter sets produce different
  ``qf`` with practical determinism. No raw SQL, FTS content, secrets, or paths are
  included.
- **Cursor**: base64url(JSON) carrying only ``v`` (version), ``qf`` (fingerprint),
  ``sort`` (last row's stable sort tuple ``[created_at, event_id]``), and ``lim``
  (the limit this cursor is bound to). The encoding is transport-only; the cursor is
  safe because of its contained fields and strict validation, not because of secrecy.
- **Validation**: malformed / unsupported version / missing sort → ``invalid_cursor``;
  fingerprint mismatch → ``cursor_query_mismatch``; limit mismatch → ``cursor_limit_mismatch``.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Optional

from .models import (
    CURSOR_LIMIT_MISMATCH,
    CURSOR_QUERY_MISMATCH,
    INVALID_CURSOR,
    QueryError,
    QueryRequest,
)

CURSOR_VERSION = 1
DEFAULT_LIMIT = 50
MAX_LIMIT = 500

# Constant folded into the fingerprint so a cursor is bound to the actual query shape
# (all M3 queries exclude deleted; this marker makes that explicit and stable).
_DELETED_EXCLUSION_MARKER = {"_deleted_excluded": True}


def make_fingerprint(req: QueryRequest, text: Optional[str] = None,
                     match_mode: Optional[str] = None) -> str:
    """SHA-256 of the canonical normalized filter set (+ optional FTS text/mode).

    Normalization: sorted keys, None values excluded, deterministic separators, a
    constant deleted-exclusion marker, the normalized FTS ``text`` when present, and
    the FTS ``match_mode`` ("and" | "or_fallback") when present (V130-01: a cursor is
    bound to the MATCH strategy that produced it — cross-mode reuse is rejected).
    Equivalent structured queries (and equivalent text + mode) produce the same ``qf``;
    different filter sets, text, or mode produce different ``qf`` with practical
    determinism. No raw SQL, FTS internals, secrets, or paths are included.
    """
    if not isinstance(req, QueryRequest):
        raise QueryError(code="invalid_query", message="not_a_query_request")
    normalized = dict(req.to_dict())
    normalized.update(_DELETED_EXCLUSION_MARKER)
    if text is not None:
        if not isinstance(text, str) or not text:
            raise QueryError(code="invalid_query", message="empty_fts_text")
        # Normalize the FTS text deterministically: collapse runs of whitespace, strip.
        normalized["text"] = " ".join(text.split())
    if match_mode is not None:
        if match_mode not in ("and", "or_fallback"):
            raise QueryError(code="invalid_query", message="invalid_match_mode")
        normalized["match_mode"] = match_mode
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def make_artifact_fingerprint(origin_event_id: str) -> str:
    """SHA-256 of the canonical normalized artifact-reference query (origin_event_id)."""
    if not isinstance(origin_event_id, str) or not origin_event_id:
        raise QueryError(code="invalid_query", message="non_string_event_id")
    normalized = {"kind": "artifact", "origin_event_id": origin_event_id}
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def make_relation_fingerprint(event_id: str, direction: Optional[str], relation_type: Optional[str]) -> str:
    """SHA-256 of the canonical normalized relation query (event_id + direction + relation_type).

    Equivalent relation queries → identical fingerprint; different event/direction/type → different.
    No raw SQL, secrets, or paths are included.
    """
    if not isinstance(event_id, str) or not event_id:
        raise QueryError(code="invalid_query", message="non_string_event_id")
    direction = direction or "both"
    if direction not in ("outgoing", "incoming", "both"):
        raise QueryError(code="invalid_direction", message=direction)
    normalized = {
        "kind": "related",
        "event_id": event_id,
        "direction": direction,
        "relation_type": relation_type or "",
    }
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def encode_cursor(qf: str, created_at: str, event_id: str, limit: int) -> str:
    """Encode a versioned, query-bound cursor. Safe fields only."""
    payload = {
        "v": CURSOR_VERSION,
        "qf": qf,
        "sort": [created_at, event_id],
        "lim": int(limit),
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _is_b64(text: str) -> bool:
    try:
        base64.urlsafe_b64decode(text.encode("ascii") + b"=" * (-len(text) % 4))
        return True
    except Exception:
        return False


def decode_cursor(token: str) -> dict:
    """Decode and structurally validate a cursor.

    Raises fixed sanitized errors on any problem:
    - malformed (not base64url / not JSON / missing fields) → ``invalid_cursor``
    - unsupported version → ``invalid_cursor``
    - missing sort fields → ``invalid_cursor``
    """
    if not isinstance(token, str) or not token:
        raise QueryError(code=INVALID_CURSOR, message="empty_cursor")
    if not _is_b64(token):
        raise QueryError(code=INVALID_CURSOR, message="not_base64url")
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii") + b"=" * (-len(token) % 4))
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        raise QueryError(code=INVALID_CURSOR, message="not_json")
    if not isinstance(data, dict):
        raise QueryError(code=INVALID_CURSOR, message="not_object")
    if data.get("v") != CURSOR_VERSION:
        raise QueryError(code=INVALID_CURSOR, message="unsupported_version")
    qf = data.get("qf")
    sort = data.get("sort")
    lim = data.get("lim")
    if not isinstance(qf, str) or not qf:
        raise QueryError(code=INVALID_CURSOR, message="missing_qf")
    if not isinstance(sort, list) or len(sort) != 2 or not all(isinstance(s, str) for s in sort):
        raise QueryError(code=INVALID_CURSOR, message="missing_sort")
    if not isinstance(lim, int) or isinstance(lim, bool):
        raise QueryError(code=INVALID_CURSOR, message="missing_lim")
    return data


def validate_cursor_binding(token: str, qf: str, limit: int) -> dict:
    """Decode a cursor and enforce query/limit binding.

    Returns the decoded cursor dict on success. Raises:
    - ``cursor_query_mismatch`` if the cursor's fingerprint differs from ``qf``
    - ``cursor_limit_mismatch`` if the cursor's bound limit differs from ``limit``
    - ``invalid_cursor`` for any structural problem (delegated to ``decode_cursor``)
    """
    data = decode_cursor(token)
    if data["qf"] != qf:
        raise QueryError(code=CURSOR_QUERY_MISMATCH, message="query_fingerprint_mismatch")
    if data["lim"] != limit:
        raise QueryError(code=CURSOR_LIMIT_MISMATCH, message="limit_mismatch")
    return data
