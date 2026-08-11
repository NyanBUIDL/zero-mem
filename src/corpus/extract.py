"""M10.2 — structural extraction result + error contracts (deterministic, no LLM).

These are DATA-only records describing what an adapter produced. They deliberately
carry NO semantic ontology (no fact/claim/argument). Coarse structural
``unit_kind`` values only. Extraction is a derived/rebuildable representation of
the source artifact + parser configuration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional


class ExtractionStatus(str, Enum):
    """Closed extraction-outcome status. Unknown values fail closed."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNSUPPORTED_FORMAT = "unsupported_format"
    CORRUPT_SOURCE = "corrupt_source"
    PARSER_UNAVAILABLE = "parser_unavailable"
    EMPTY_SOURCE = "empty_source"
    MISSING_SOURCE = "missing_source"
    PERMISSION_DENIED = "permission_denied"
    ADAPTER_FAILED = "adapter_failed"

    @classmethod
    def validate(cls, value: str) -> "ExtractionStatus":
        if value not in _VALID_STATUS:
            raise ValueError(f"invalid extraction status: {value!r}")
        return cls(value)

    @property
    def is_success(self) -> bool:
        return self in (ExtractionStatus.COMPLETE, ExtractionStatus.PARTIAL)

    @property
    def is_failure(self) -> bool:
        return not self.is_success


_VALID_STATUS = {s.value for s in ExtractionStatus}


# Coarse structural unit kinds only (approved plan §10.3 / §4). No semantic
# classes. Unknown structure stays a valid normal case (use ``other``).
class UnitKind(str, Enum):
    TEXT = "text"
    HEADING = "heading"
    TABLE = "table"
    CODE = "code"
    FIGURE = "figure"
    METADATA = "metadata"
    OTHER = "other"

    @classmethod
    def validate(cls, value: str) -> "UnitKind":
        if value not in _VALID_KIND:
            return cls.OTHER
        return cls(value)


_VALID_KIND = {k.value for k in UnitKind}


class ExtractionError(ValueError):
    """Typed, deterministic extraction failure. Never carries raw source text."""

    def __init__(self, status: ExtractionStatus, reason: str, *, source_ref: str | None = None):
        self.status = ExtractionStatus.validate(status.value if isinstance(status, ExtractionStatus) else status)
        self.reason = reason
        self.source_ref = source_ref
        super().__init__(f"extraction_{self.status.value}: {reason}")


@dataclass(frozen=True)
class ExtractionUnit:
    """One coarse structural unit of an extracted source. DATA-only, not memory."""

    unit_id: str
    kind: str
    text: str
    source_ref: str
    order: int
    page: Optional[int] = None
    parent_ref: Optional[str] = None
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        kind = UnitKind.validate(self.kind)
        object.__setattr__(self, "kind", kind.value)
        if not self.unit_id or not self.source_ref:
            raise ValueError("ExtractionUnit requires unit_id and source_ref")

    def as_dict(self) -> dict:
        return {
            "unit_id": self.unit_id,
            "kind": self.kind,
            "text": self.text,
            "source_ref": self.source_ref,
            "order": self.order,
            "page": self.page,
            "parent_ref": self.parent_ref,
            "meta": dict(self.meta),
        }


@dataclass(frozen=True)
class ExtractionResult:
    """Deterministic extraction outcome for one source artifact."""

    source_ref: str
    status: str
    units: tuple[ExtractionUnit, ...] = field(default_factory=tuple)
    extractor_version: str = "m10.2"
    parser_name: Optional[str] = None
    error_reason: Optional[str] = None
    byte_length: Optional[int] = None
    contained_secret: bool = False

    def __post_init__(self) -> None:
        ExtractionStatus.validate(self.status)
        if ExtractionStatus.validate(self.status).is_failure and not self.error_reason:
            raise ValueError("failed ExtractionResult requires error_reason")

    @property
    def ok(self) -> bool:
        return ExtractionStatus.validate(self.status).is_success

    def as_dict(self) -> dict:
        return {
            "source_ref": self.source_ref,
            "status": self.status,
            "units": [u.as_dict() for u in self.units],
            "extractor_version": self.extractor_version,
            "parser_name": self.parser_name,
            "error_reason": self.error_reason,
            "byte_length": self.byte_length,
            "contained_secret": self.contained_secret,
        }


__all__ = [
    "ExtractionStatus",
    "UnitKind",
    "ExtractionError",
    "ExtractionUnit",
    "ExtractionResult",
]
