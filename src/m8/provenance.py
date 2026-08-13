"""M8.1 — frozen relation/record provenance contract.

Every derived M8 record must be traceable back to the canonical substrate that
produced it, and must be reproducible by replaying that substrate. A record
whose provenance is incomplete is NOT eligible to exist in the derived index
(docs/plans/plan-m8.md §7 "An edge without sufficient provenance is not eligible").

Required provenance fields (frozen):

- ``relation_source`` — which canonical substrate asserted this (closed enum);
- ``source_ref`` — the explicit canonical/resource identity within it;
- ``projection_version`` — the projector contract version that produced it;
- ``identity_version`` — the identity algorithm version used for its ID;
- scope metadata — ``profile_id`` / ``project_id`` / ``knowledge_space_id``,
  with explicit ``None`` preserved as ``None``.

Optional-but-preserved: ``source_event_id``, ``trace_id``, and temporal
metadata where the canonical source legitimately carries them.

Nothing here is fabricated. If a source has no ``trace_id``, the field stays
``None``; it is never backfilled from a sibling record, a scope id, or the
source event id.

Provenance is DESCRIPTIVE. It records where a derived record came from. It
confers no verification, no authorization, and no truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Optional

from .identity import canonical_json, provenance_hash
from .identity import IDENTITY_VERSION
from .temporal_contract import TemporalMetadata
from .vocabulary import validate_relation_source

#: Frozen provenance-contract version.
PROVENANCE_CONTRACT_VERSION: Final[str] = "v1"

#: Fields that MUST be present and non-empty on every provenance envelope.
REQUIRED_PROVENANCE_FIELDS: Final[tuple[str, ...]] = (
    "relation_source",
    "source_ref",
    "projection_version",
    "identity_version",
)

#: Scope fields that must be explicitly represented (``None`` is a valid,
#: meaningful value meaning "unscoped"; a MISSING key is not).
SCOPE_PROVENANCE_FIELDS: Final[tuple[str, ...]] = (
    "profile_id",
    "project_id",
    "knowledge_space_id",
)


class ProvenanceError(ValueError):
    """Sanitized provenance-contract violation."""

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"provenance_error: {reason}: {field}")
        self.field = field
        self.reason = reason


@dataclass(frozen=True)
class Provenance:
    """Frozen provenance envelope for one derived M8 record.

    Immutable and deterministically serializable: the same canonical inputs
    always produce the same ``to_dict()`` payload and the same
    ``provenance_hash()``, which is what makes derived rebuild verifiable.
    """

    relation_source: str
    source_ref: str
    projection_version: str
    identity_version: str = IDENTITY_VERSION
    source_event_id: Optional[str] = None
    trace_id: Optional[str] = None
    profile_id: Optional[str] = None
    project_id: Optional[str] = None
    knowledge_space_id: Optional[str] = None
    temporal: Optional[TemporalMetadata] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "relation_source", validate_relation_source(self.relation_source)
        )
        for field in ("source_ref", "projection_version", "identity_version"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ProvenanceError(field, "missing_required_field")
        for field in ("source_event_id", "trace_id", *SCOPE_PROVENANCE_FIELDS):
            value = getattr(self, field)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                # An empty string is not a valid identifier and must not be
                # normalized into None (that would erase a malformed record
                # instead of rejecting it).
                raise ProvenanceError(field, "invalid_optional_field")
        if self.temporal is not None and not isinstance(self.temporal, TemporalMetadata):
            raise ProvenanceError("temporal", "invalid_temporal_metadata")

    def to_dict(self) -> dict[str, Any]:
        """Deterministic serialization. Key order is fixed by canonical JSON."""
        return {
            "relation_source": self.relation_source,
            "source_ref": self.source_ref,
            "projection_version": self.projection_version,
            "identity_version": self.identity_version,
            "provenance_contract_version": PROVENANCE_CONTRACT_VERSION,
            "source_event_id": self.source_event_id,
            "trace_id": self.trace_id,
            "profile_id": self.profile_id,
            "project_id": self.project_id,
            "knowledge_space_id": self.knowledge_space_id,
            "temporal": self.temporal.to_dict() if self.temporal is not None else None,
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def compute_hash(self) -> str:
        """Deterministic hash over the full provenance envelope."""
        return provenance_hash(self.to_dict())


def validate_provenance(provenance: Provenance) -> Provenance:
    """Re-validate a provenance envelope at an index boundary.

    ``Provenance`` validates on construction; this is the explicit fail-closed
    gate used by the derived-index layer so an object built by an older or
    hand-rolled path cannot slip past the contract.
    """
    if not isinstance(provenance, Provenance):
        raise ProvenanceError("provenance", "not_a_provenance_envelope")
    payload = provenance.to_dict()
    for field in REQUIRED_PROVENANCE_FIELDS:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ProvenanceError(field, "missing_required_field")
    for field in SCOPE_PROVENANCE_FIELDS:
        if field not in payload:
            raise ProvenanceError(field, "missing_scope_field")
    return provenance


__all__ = [
    "PROVENANCE_CONTRACT_VERSION",
    "REQUIRED_PROVENANCE_FIELDS",
    "SCOPE_PROVENANCE_FIELDS",
    "ProvenanceError",
    "Provenance",
    "validate_provenance",
]
