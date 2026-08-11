"""M10.1 — closed corpus source record contract.

A ``CorpusSourceRecord`` is the registry entry for one corpus source version.
It is DATA, not authority, and never enters memory JSONL (MEMORY != CORPUS).
The contract is CLOSED: an unknown lifecycle status or resource_type is
rejected (fails closed), never coerced.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from .identity import SourceLifecycle

#: The single resource_type a source record carries at the M5 authorization
#: boundary. Per owner decision Q1, corpus sources and units are distinct
#: resource types; this record is the source side (the unit side is M10.3+).
CORPUS_SOURCE_RESOURCE_TYPE = "corpus_source"

#: Closed sensitivity ceiling for corpus sources (mirrors M1/M9; secret is
#: withheld, never stored/projected by the corpus path).
class SourceSensitivity(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PRIVATE = "private"
    SECRET = "secret"

    @classmethod
    def validate(cls, value: str) -> str:
        if value not in _VALID_SENSITIVITY:
            raise ValueError(f"invalid corpus source sensitivity: {value!r}")
        return value


_VALID_SENSITIVITY = {s.value for s in SourceSensitivity}


class ValidationError(ValueError):
    """Closed-contract validation failure (fail closed)."""


@dataclass(frozen=True)
class CorpusSourceRecord:
    """One append-only corpus source version identity + provenance.

    No document bytes are stored here (blob store is M10.2/M10.4). ``blob_ref``
    is declared but remains None in M10.1; it is populated only by later
    increments that actually persist the source artifact.
    """

    source_id: str
    content_hash: str
    external_ref: str
    kind: str
    created_at: str
    profile_id: Optional[str] = None
    project_id: Optional[str] = None
    knowledge_space_id: Optional[str] = None
    sensitivity: str = SourceSensitivity.INTERNAL.value
    lifecycle_status: str = SourceLifecycle.OBSERVED.value
    resource_type: str = CORPUS_SOURCE_RESOURCE_TYPE
    blob_ref: Optional[str] = None
    provenance: Mapping[str, Any] = field(default_factory=dict)
    custom_meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Closed-contract validation (fail closed). Surface a contract-specific
        # ValidationError (subclass of ValueError) so callers get a clean signal.
        try:
            if self.resource_type != CORPUS_SOURCE_RESOURCE_TYPE:
                raise ValueError(
                    f"corpus source resource_type must be {CORPUS_SOURCE_RESOURCE_TYPE!r}, got {self.resource_type!r}"
                )
            SourceLifecycle.validate(self.lifecycle_status)
            SourceSensitivity.validate(self.sensitivity)
            if not self.source_id or not self.content_hash:
                raise ValueError("source_id and content_hash are required")
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

    def as_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "content_hash": self.content_hash,
            "external_ref": self.external_ref,
            "kind": self.kind,
            "resource_type": self.resource_type,
            "profile_id": self.profile_id,
            "project_id": self.project_id,
            "knowledge_space_id": self.knowledge_space_id,
            "sensitivity": self.sensitivity,
            "lifecycle_status": self.lifecycle_status,
            "blob_ref": self.blob_ref,
            "provenance": dict(self.provenance),
            "custom_meta": dict(self.custom_meta),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CorpusSourceRecord":
        return cls(
            source_id=data["source_id"],
            content_hash=data["content_hash"],
            external_ref=data["external_ref"],
            kind=data["kind"],
            created_at=data["created_at"],
            profile_id=data.get("profile_id"),
            project_id=data.get("project_id"),
            knowledge_space_id=data.get("knowledge_space_id"),
            sensitivity=data.get("sensitivity", SourceSensitivity.INTERNAL.value),
            lifecycle_status=data.get("lifecycle_status", SourceLifecycle.OBSERVED.value),
            resource_type=data.get("resource_type", CORPUS_SOURCE_RESOURCE_TYPE),
            blob_ref=data.get("blob_ref"),
            provenance=data.get("provenance") or {},
            custom_meta=data.get("custom_meta") or {},
        )


__all__ = [
    "CorpusSourceRecord",
    "ValidationError",
    "SourceSensitivity",
    "SourceLifecycle",
    "CORPUS_SOURCE_RESOURCE_TYPE",
]
