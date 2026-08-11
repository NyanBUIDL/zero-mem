"""M10.1 — deterministic corpus source identity.

Reuses ``src.m8.identity.content_hash`` so corpus hashing shares the exact
deterministic sha256 materialization already used by the verified M8 derived
store. Zero LLM, zero network.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Mapping, Optional

from src.m8.identity import content_hash

#: Corpus source descriptor domain for the shared content-hash materialization.
_DOMAIN = "corpus_source"

#: Closed lifecycle enum for corpus sources (subset of the M1 closed lifecycle;
#: corpus reuses the same permanent values so downstream authorization/graph
#: can carry them through unchanged). Unknown values fail closed.
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
    """Build the canonical, deterministic descriptor used for source identity.

    The descriptor is the identity basis only (NOT the blob bytes). It includes
    scope + a stable custom-meta map so identical external sources under the
    same scope resolve to the same identity, while unchanged-source detection
    keys off the authoritative content_hash supplied separately.
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


def compute_source_hash(content: bytes, descriptor: Mapping[str, Any]) -> str:
    """Deterministic content hash over (source bytes + descriptor).

    Identity is content-addressed: identical bytes + identical descriptor =>
    identical hash => unchanged-source detection and idempotent append.
    """
    payload = {
        "domain": _DOMAIN,
        "descriptor": dict(descriptor),
        "content_bytes_sha256": _raw_sha256(content),
    }
    return content_hash(payload)


def _raw_sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def derive_source_id(content_hash_value: str, descriptor: Mapping[str, Any]) -> str:
    """Derive a stable source_id from the content hash + scope.

    Append-only: re-registering identical (content, scope) yields the same
    source_id; a changed source later yields a new version row, never a silent
    overwrite.
    """
    scope_key = "|".join([
        descriptor.get("profile_id") or "",
        descriptor.get("project_id") or "",
        descriptor.get("knowledge_space_id") or "",
    ])
    payload = {
        "domain": _DOMAIN,
        "content_hash": content_hash_value,
        "scope": scope_key,
    }
    return content_hash(payload)
