"""M8.1 — deterministic identity primitives for derived M8 structures.

Identity must be reproducible from canonical inputs alone. A rebuild that
replays the same canonical sources must produce byte-identical identifiers.

Explicitly forbidden as identity inputs (plan-m8.md §6, §14):

- Python object identity (``id()``), memory addresses, or ``hash()``;
- insertion order, ``rowid``, or ``AUTOINCREMENT`` sequence;
- random or time-based UUIDs;
- wall-clock time at rebuild;
- string similarity, co-occurrence, or any inferred equivalence.

Only explicit canonical field values participate. Every identifier is a
domain-separated SHA-256 digest over a canonical JSON serialization, so two
different logical kinds can never collide.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any, Final, Mapping

#: Identity algorithm version. Any change to the canonicalization or digest
#: scheme MUST bump this, because it changes every derived identifier.
IDENTITY_VERSION: Final[str] = "v1"

#: Domain separators. A digest is always bound to exactly one logical kind.
_DOMAIN_ENTITY: Final[str] = "zm8.entity"
_DOMAIN_MENTION: Final[str] = "zm8.entity_mention"
_DOMAIN_EDGE: Final[str] = "zm8.graph_edge"
_DOMAIN_CONTENT: Final[str] = "zm8.content"
_DOMAIN_PROVENANCE: Final[str] = "zm8.provenance"
_DOMAIN_FINGERPRINT: Final[str] = "zm8.fingerprint"

#: Human-readable identifier prefixes (stable; part of the frozen contract).
ENTITY_ID_PREFIX: Final[str] = "ent_"
MENTION_ID_PREFIX: Final[str] = "men_"
EDGE_ID_PREFIX: Final[str] = "edg_"

#: Truncated digest length used for identifiers (full digest kept for hashes).
_ID_DIGEST_CHARS: Final[int] = 32


class IdentityError(ValueError):
    """Sanitized deterministic-identity failure.

    The message never contains raw payload text, secrets, or SQL.
    """


def canonical_json(payload: Mapping[str, Any]) -> str:
    """Serialize a mapping deterministically.

    Key order, separators, and escaping are fixed so the same logical payload
    always produces the same bytes on every platform and Python run.
    """
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise IdentityError("identity_error: non_serializable_payload") from exc


def _digest(domain: str, payload: Mapping[str, Any]) -> str:
    material = f"{domain}|{IDENTITY_VERSION}|{canonical_json(payload)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def content_hash(payload: Mapping[str, Any]) -> str:
    """Full-length deterministic content hash for a derived record."""
    return _digest(_DOMAIN_CONTENT, payload)


def provenance_hash(payload: Mapping[str, Any]) -> str:
    """Full-length deterministic hash over a provenance envelope."""
    return _digest(_DOMAIN_PROVENANCE, payload)


def source_fingerprint(payload: Mapping[str, Any]) -> str:
    """Deterministic fingerprint over a canonical-source description.

    Used by the derived-index registry to record which canonical state a
    derived index was built from. It is an integrity/rebuild marker only; it
    carries no authority and no truth semantics.
    """
    return _digest(_DOMAIN_FINGERPRINT, payload)


def normalize_name(value: str) -> str:
    """Minimal deterministic name normalization for entity identity.

    Applies ONLY Unicode NFC normalization and outer-whitespace stripping.

    Deliberately NOT applied (each would be identity *inference*, which the
    plan forbids): case folding, accent folding, punctuation removal, token
    reordering, stemming, synonym expansion, or similarity matching. ``Alice``
    and ``alice`` therefore remain distinct entities unless an explicitly
    approved later increment says otherwise.
    """
    if not isinstance(value, str):
        raise IdentityError("identity_error: name_not_a_string")
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized:
        raise IdentityError("identity_error: empty_name")
    return normalized


def _require_nonempty(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IdentityError(f"identity_error: missing_{field}")
    return value


def _scope_payload(
    profile_id: str | None,
    project_id: str | None,
    knowledge_space_id: str | None,
) -> dict[str, Any]:
    """Scope participates in identity; explicit NULL is preserved as null.

    A record scoped to a project is a DIFFERENT logical record from an
    otherwise identical unscoped one. Collapsing them would flatten profile /
    project boundaries, so the nulls are part of the hashed payload.
    """
    return {
        "profile_id": profile_id,
        "project_id": project_id,
        "knowledge_space_id": knowledge_space_id,
    }


def derive_entity_id(
    *,
    entity_type: str,
    canonical_name: str,
    profile_id: str | None = None,
    project_id: str | None = None,
    knowledge_space_id: str | None = None,
) -> str:
    """Derive a deterministic entity identifier.

    Identity = (entity_type, normalized canonical_name, explicit scope). No
    text inference, no ordering, no randomness.
    """
    payload = {
        "entity_type": _require_nonempty(entity_type, "entity_type"),
        "canonical_name": normalize_name(canonical_name),
        "scope": _scope_payload(profile_id, project_id, knowledge_space_id),
    }
    return ENTITY_ID_PREFIX + _digest(_DOMAIN_ENTITY, payload)[:_ID_DIGEST_CHARS]


def derive_mention_id(
    *,
    entity_id: str,
    source_event_id: str,
    span_start: int | None = None,
    span_end: int | None = None,
) -> str:
    """Derive a deterministic mention identifier.

    A mention is identified by its entity, its canonical source event, and the
    explicit span (when a span is known). Missing spans stay ``None``; they are
    never replaced with ``0`` or a guessed offset.
    """
    if span_start is not None and not isinstance(span_start, int):
        raise IdentityError("identity_error: invalid_span_start")
    if span_end is not None and not isinstance(span_end, int):
        raise IdentityError("identity_error: invalid_span_end")
    if span_start is not None and span_start < 0:
        raise IdentityError("identity_error: negative_span_start")
    if span_end is not None and span_end < 0:
        raise IdentityError("identity_error: negative_span_end")
    if span_start is not None and span_end is not None and span_end < span_start:
        raise IdentityError("identity_error: inverted_span")
    payload = {
        "entity_id": _require_nonempty(entity_id, "entity_id"),
        "source_event_id": _require_nonempty(source_event_id, "source_event_id"),
        "span_start": span_start,
        "span_end": span_end,
    }
    return MENTION_ID_PREFIX + _digest(_DOMAIN_MENTION, payload)[:_ID_DIGEST_CHARS]


def derive_edge_id(
    *,
    from_resource_type: str,
    from_resource_id: str,
    relation_type: str,
    to_resource_type: str,
    to_resource_id: str,
    source_ref: str,
    profile_id: str | None = None,
    project_id: str | None = None,
    knowledge_space_id: str | None = None,
) -> str:
    """Derive a deterministic edge identifier.

    ``resource_type`` is part of identity on BOTH endpoints, so an edge to an
    artifact can never be confused with an edge to an event carrying the same
    raw id (permanent M6.6 resource-type isolation invariant).

    ``source_ref`` is part of identity so two distinct canonical sources
    asserting the same logical link remain two provenance-distinct edges rather
    than being silently merged into one unattributable edge.
    """
    payload = {
        "from": {
            "resource_type": _require_nonempty(from_resource_type, "from_resource_type"),
            "resource_id": _require_nonempty(from_resource_id, "from_resource_id"),
        },
        "relation_type": _require_nonempty(relation_type, "relation_type"),
        "to": {
            "resource_type": _require_nonempty(to_resource_type, "to_resource_type"),
            "resource_id": _require_nonempty(to_resource_id, "to_resource_id"),
        },
        "source_ref": _require_nonempty(source_ref, "source_ref"),
        "scope": _scope_payload(profile_id, project_id, knowledge_space_id),
    }
    return EDGE_ID_PREFIX + _digest(_DOMAIN_EDGE, payload)[:_ID_DIGEST_CHARS]


__all__ = [
    "IDENTITY_VERSION",
    "ENTITY_ID_PREFIX",
    "MENTION_ID_PREFIX",
    "EDGE_ID_PREFIX",
    "IdentityError",
    "canonical_json",
    "content_hash",
    "provenance_hash",
    "source_fingerprint",
    "normalize_name",
    "derive_entity_id",
    "derive_mention_id",
    "derive_edge_id",
]
