"""Deterministic corpus identity primitives.

Corpus identity has deliberately separate axes:

* content identity is derived from source bytes only;
* logical source identity is derived from the stable descriptor only; and
* version identity combines the logical source, content, scope, and
  normalization contract.

The registry owns the first two axes. Version-chain code consumes them without
using content as a logical-source or authorization key.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Mapping, Optional

from src.m8.identity import content_hash

_CONTENT_DOMAIN = "zm10.corpus_source_content"
_LOGICAL_SOURCE_DOMAIN = "zm10.corpus_logical_source"


class SourceLifecycle(str, Enum):
    RAW = "raw"
    OBSERVED = "observed"
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    CONFLICTED = "conflicted"
    ARCHIVED = "archived"
    DELETED = "deleted"

    @classmethod
    def validate(cls, value: str) -> str:
        if value not in _VALID_LIFECYCLE:
            raise ValueError(f"invalid corpus source lifecycle: {value!r}")
        return value


_VALID_LIFECYCLE = {s.value for s in SourceLifecycle}


def source_descriptor(
    *,
    external_ref: str,
    kind: str,
    profile_id: Optional[str] = None,
    project_id: Optional[str] = None,
    knowledge_space_id: Optional[str] = None,
    custom_meta: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Build the stable logical-source descriptor.

    ``external_ref`` is location/provenance. It therefore makes a renamed copy
    a new logical source unless a separately approved relocation operation is
    introduced. Source bytes are intentionally absent.
    """
    desc: dict = {
        "external_ref": external_ref,
        "kind": kind,
        "profile_id": profile_id,
        "project_id": project_id,
        "knowledge_space_id": knowledge_space_id,
    }
    if custom_meta:
        desc["custom_meta"] = dict(custom_meta)
    return desc


def _raw_sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def compute_content_identity(content: bytes) -> str:
    """Return content identity derived from source bytes only."""
    return content_hash({"domain": _CONTENT_DOMAIN, "bytes_sha256": _raw_sha256(content)})


def compute_source_hash(content: bytes, descriptor: Mapping[str, Any] | None = None) -> str:
    """Backward-compatible bytes-only content identity API.

    ``descriptor`` remains accepted for pre-R3 callers but is deliberately
    ignored. Location and authorization metadata must not alter content ID.
    """
    return compute_content_identity(content)


def compute_logical_source_id(descriptor: Mapping[str, Any]) -> str:
    """Derive logical source identity from the stable descriptor only."""
    return content_hash({"domain": _LOGICAL_SOURCE_DOMAIN, "descriptor": dict(descriptor)})


def derive_source_id(
    content_hash_value: str | None,
    descriptor: Mapping[str, Any],
) -> str:
    """Derive stable logical ``source_id`` from ``descriptor``.

    The first argument is retained solely for source compatibility with the
    pre-R3 function signature. It is not used in the calculation.
    """
    return compute_logical_source_id(descriptor)


__all__ = [
    "SourceLifecycle",
    "source_descriptor",
    "compute_content_identity",
    "compute_source_hash",
    "compute_logical_source_id",
    "derive_source_id",
]
