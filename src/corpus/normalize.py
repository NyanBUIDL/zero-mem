"""M10.3 — normalized corpus units + deterministic normalization contract.

Converts M10.2 coarse structural extraction (``ExtractionUnit`` /
``ExtractionResult``) into a stable, format-neutral normalized representation
suitable for later indexing/storage (M10.4+). It carries NO semantic ontology
and introduces NO new ``unit_kind`` values: the coarse structural ``unit_kind``
set is inherited verbatim from the VERIFIED M10.2 ``UnitKind`` enum
(``text`` / ``heading`` / ``table`` / ``code`` / ``figure`` / ``metadata`` /
``other``); any unknown extracted kind normalizes to ``other``.

Normalization is deterministic and lossless with respect to meaning:
- Unicode NFC normalization (platform/format stable).
- Newline normalization to ``\\n`` (no CRLF / CR dependence).
- Collapse runs of internal whitespace to a single space (no meaning change).
- Strip leading/trailing whitespace per unit.
- Empty units (after normalization) are dropped (they carry no retrievable
  content and would only pollute dedup).
- Ordering / structural locator (``order``, ``page``, ``parent_ref``) is
  preserved verbatim so downstream storage can rebuild position.

No summarization, paraphrasing, translation, semantic inference, or LLM/network
calls. No schema change; no derived SQLite store (that is M10.4).

Identity is intentionally NOT mixed here:
- ``content_hash`` is the CONTENT identity (what the text says, after
  normalization) and is computed in :mod:`src.corpus.dedup`.
- ``source_location_id`` is the SOURCE LOCATION identity (where the unit sits in
  its source) and is computed in :mod:`src.corpus.dedup`.

This module only produces the normalized *content* + carries the extraction's
structural provenance forward.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Mapping, Optional

from .extract import ExtractionResult, ExtractionUnit, UnitKind

#: Coarse structural unit kinds (mirrors VERIFIED M10.2 UnitKind; no additions).
#: Authoritative set — the normalized representation must not invent semantics.
VALID_NORMALIZED_KINDS: Final[frozenset[str]] = frozenset(k.value for k in UnitKind)

#: The value used when an extracted unit carries an unknown/unsupported kind.
NORMALIZED_KIND_OTHER = UnitKind.OTHER.value

#: Normalization contract version. Bump only when the canonicalization rules
#: change, so downstream rebuilds can tell "source changed" from
#: "normalization logic changed" (distinct from ``extractor_version`` which
#: covers the M10.2 extraction stage).
NORMALIZATION_VERSION: Final[str] = "m10.3"

#: Closed normalization status. Mirrors the M10.2 failure-classification
#: discipline: a non-success extraction does not yield normalized units.
class NormalizationStatus(str, Enum):
    COMPLETE = "complete"
    EMPTY = "empty"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"

    @classmethod
    def validate(cls, value: str) -> "NormalizationStatus":
        if value not in _VALID_STATUS:
            raise ValueError(f"invalid normalization status: {value!r}")
        return cls(value)


_VALID_STATUS = {s.value for s in NormalizationStatus}


class NormalizationError(ValueError):
    """Typed, deterministic normalization failure. Never carries raw text."""


def normalize_text(text: str) -> str:
    """Deterministic content normalization (meaning-preserving, format-neutral).

    Steps:
    1. Unicode NFC (canonical composition) — stable across parsers/platforms.
    2. Newline normalization to ``\\n`` (CRLF/CR collapse to LF).
    3. Collapse internal whitespace runs to a single space.
    4. Strip leading/trailing whitespace.

    This does NOT alter the meaning of the text. It makes equivalent extracted
    content byte-stable for content-hash / dedup identity.
    """
    if not isinstance(text, str):
        raise NormalizationError("normalize_text: input must be str")
    composed = unicodedata.normalize("NFC", text)
    lf = composed.replace("\r\n", "\n").replace("\r", "\n")
    collapsed = " ".join(lf.split())
    return collapsed.strip()


def is_empty_unit(kind: str, text: str) -> bool:
    """An extracted unit contributes nothing retrievable if its normalized text
    is empty (e.g. a blank separator, a figure with no caption text)."""
    return normalize_text(text) == ""


@dataclass(frozen=True)
class NormalizedUnit:
    """One format-neutral normalized corpus unit. DERIVED data; not memory.

    Carries only what later stages need:
    - ``source_location_id`` : where in the source (structural locator).
    - ``normalized_text``    : deterministic, meaning-preserving content.
    - ``kind``               : coarse structural unit_kind (inherited).
    - ``order`` / ``page`` / ``parent_ref`` : structural locator / provenance.
    - ``source_ref``         : back-reference to the originating source record.
    """

    source_location_id: str
    normalized_text: str
    kind: str
    source_ref: str
    order: int
    page: Optional[int] = None
    parent_ref: Optional[str] = None
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in VALID_NORMALIZED_KINDS:
            object.__setattr__(self, "kind", NORMALIZED_KIND_OTHER)
        if not self.source_location_id or not self.source_ref:
            raise ValueError("NormalizedUnit requires source_location_id and source_ref")

    def as_dict(self) -> dict:
        return {
            "source_location_id": self.source_location_id,
            "normalized_text": self.normalized_text,
            "kind": self.kind,
            "source_ref": self.source_ref,
            "order": self.order,
            "page": self.page,
            "parent_ref": self.parent_ref,
            "meta": dict(self.meta),
        }


@dataclass(frozen=True)
class NormalizationResult:
    """Deterministic normalization outcome for one source's extraction."""

    source_ref: str
    status: str
    units: tuple[NormalizedUnit, ...] = field(default_factory=tuple)
    normalization_version: str = NORMALIZATION_VERSION
    extractor_version: Optional[str] = None
    error_reason: Optional[str] = None
    byte_length: Optional[int] = None

    def __post_init__(self) -> None:
        NormalizationStatus.validate(self.status)
        if NormalizationStatus.validate(self.status).value in (
            NormalizationStatus.UNSUPPORTED.value,
            NormalizationStatus.FAILED.value,
        ) and not self.error_reason:
            raise ValueError("failed/unsupported NormalizationResult requires error_reason")

    @property
    def ok(self) -> bool:
        return NormalizationStatus.validate(self.status) == NormalizationStatus.COMPLETE

    @property
    def is_empty(self) -> bool:
        return NormalizationStatus.validate(self.status) == NormalizationStatus.EMPTY

    def as_dict(self) -> dict:
        return {
            "source_ref": self.source_ref,
            "status": self.status,
            "units": [u.as_dict() for u in self.units],
            "normalization_version": self.normalization_version,
            "extractor_version": self.extractor_version,
            "error_reason": self.error_reason,
            "byte_length": self.byte_length,
        }


def normalize_extraction(result: ExtractionResult) -> NormalizationResult:
    """Convert an M10.2 :class:`ExtractionResult` into normalized units.

    Determinism: identical extraction input → identical normalized output.
    Non-success extractions (unsupported/corrupt/empty/missing/...) pass through
    with a corresponding normalization status and NO normalized units — no
    partial admission of malformed content, mirroring M10.2's closed status.
    """
    status = result.status
    if status not in _M10_2_OK_STATUS:
        # Map extraction failure classes to normalization pass-through statuses.
        mapped = _M10_2_TO_NORM.get(status, NormalizationStatus.FAILED.value)
        return NormalizationResult(
            source_ref=result.source_ref,
            status=mapped,
            normalization_version=NORMALIZATION_VERSION,
            extractor_version=result.extractor_version,
            error_reason=result.error_reason or f"extraction_{status}",
            byte_length=result.byte_length,
        )

    units: list[NormalizedUnit] = []
    for eu in result.units:
        if is_empty_unit(eu.kind, eu.text):
            # Drop empty units (no retrievable content); provenance preserved
            # only where a unit actually carries meaning.
            continue
        normalized = normalize_text(eu.text)
        if not normalized:
            continue
        units.append(
            NormalizedUnit(
                source_location_id=eu.unit_id,
                normalized_text=normalized,
                kind=eu.kind,
                source_ref=eu.source_ref,
                order=eu.order,
                page=eu.page,
                parent_ref=eu.parent_ref,
                meta=dict(eu.meta),
            )
        )

    if not units:
        return NormalizationResult(
            source_ref=result.source_ref,
            status=NormalizationStatus.EMPTY.value,
            normalization_version=NORMALIZATION_VERSION,
            extractor_version=result.extractor_version,
            byte_length=result.byte_length,
        )
    return NormalizationResult(
        source_ref=result.source_ref,
        status=NormalizationStatus.COMPLETE.value,
        units=tuple(units),
        normalization_version=NORMALIZATION_VERSION,
        extractor_version=result.extractor_version,
        byte_length=result.byte_length,
    )


# m10.2 success statuses that admit normalization (COMPLETE / PARTIAL).
_M10_2_OK_STATUS = {"complete", "partial"}

# m10.2 non-success status -> normalization status (no unit admission).
_M10_2_TO_NORM = {
    "unsupported_format": NormalizationStatus.UNSUPPORTED.value,
    "corrupt_source": NormalizationStatus.FAILED.value,
    "parser_unavailable": NormalizationStatus.UNSUPPORTED.value,
    "empty_source": NormalizationStatus.EMPTY.value,
    "missing_source": NormalizationStatus.FAILED.value,
    "permission_denied": NormalizationStatus.FAILED.value,
    "adapter_failed": NormalizationStatus.FAILED.value,
}


__all__ = [
    "NORMALIZATION_VERSION",
    "VALID_NORMALIZED_KINDS",
    "NORMALIZED_KIND_OTHER",
    "NormalizationStatus",
    "NormalizationError",
    "NormalizedUnit",
    "NormalizationResult",
    "normalize_text",
    "is_empty_unit",
    "normalize_extraction",
]
