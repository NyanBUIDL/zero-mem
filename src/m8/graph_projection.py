"""M8.2 — deterministic graph projection (pure functions only).

Converts EXPLICIT typed source records into the derived M8.1 contracts:

    approved canonical/project source record
      -> typed M8.1 contract (GraphEdge / EntityRecord / MentionProjection)

This module performs no I/O. It reads no database, opens no file, and knows
nothing about SQLite. Reading approved sources is ``graph_sources``; writing
derived rows is ``projection_store``. Keeping projection pure is what makes
determinism testable: the same source record always yields the same derived
record, byte for byte.

Boundaries deliberately preserved:

- **Graph is not truth.** ``lifecycle_status`` and ``verification_status`` are
  carried through from the source unchanged. A projected ``verifies`` edge does
  not verify anything, and an ``assistant_claim``-derived source never becomes
  a confirmed or active derived record.
- **Closed relation vocabulary only.** A source relation name with no approved
  mapping is NOT projected under a nearest-neighbour name. It is reported as an
  unmapped source relation and dropped from the derived index. In particular
  the M2 ``child_of`` class has no approved M8 counterpart (docs/plans/plan-m8.md §7
  freezes the vocabulary and M8-OQ-3 defers new mappings to explicit approval),
  so mapping it to ``related_to`` or ``references`` would be inventing
  semantics.
- **No conflict resolution.** Supersession links are projected as edges exactly
  as recorded. No winner is chosen, nothing is flattened, and no competing
  supersession model is introduced.
- **No authorization.** Scope is copied as metadata for a later M5 check. This
  module makes no access decision and derives no access from graph shape.
- **No inference.** No text matching, no similarity, no co-occurrence, no
  entity merging, no timestamps invented, no wall-clock read.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final, Mapping, Optional

from .graph_contract import EntityRecord, GraphEdge, ResourceRef, ScopeMetadata
from .identity import content_hash, derive_mention_id
from .provenance import Provenance
from .vocabulary import (
    RelationSource,
    RelationType,
    validate_entity_type,
    validate_lifecycle_status,
    validate_relation_source,
    validate_resource_type,
    validate_verification_status,
)

#: Frozen projector contract version for M8.2. Stamped into every derived row's
#: provenance so a rebuild can be attributed to the exact projector that made
#: it. Distinct from the M8.1 foundation constant, which is left untouched.
GRAPH_PROJECTION_VERSION: Final[str] = "m8.2"

#: Approved mapping from the explicit M2 ``zm_relations.relation`` vocabulary to
#: the closed M8 relation vocabulary. Only these are projected; anything else is
#: reported as unmapped and dropped (never coerced).
M2_RELATION_TYPE_MAP: Final[Mapping[str, str]] = {
    "derived_from": RelationType.DERIVED_FROM.value,
    "supersedes": RelationType.SUPERSEDES.value,
}

#: M4 verification ``subject_type`` values that name an authorizable resource
#: type. A subject type outside this map has no typed endpoint and is not
#: projected.
M4_VERIFICATION_SUBJECT_MAP: Final[Mapping[str, str]] = {
    "requirement": "requirement",
    "decision": "decision",
    "state": "state",
    "artifact": "artifact",
    "project_artifact": "project_artifact",
}

#: Stable, sanitized reason codes for a source record that is not projected.
#: These describe the projector's decision. They carry no payload text.
REASON_UNMAPPED_RELATION_TYPE: Final[str] = "unmapped_source_relation_type"
REASON_UNMAPPED_SUBJECT_TYPE: Final[str] = "unmapped_verification_subject_type"
REASON_MISSING_ENDPOINT: Final[str] = "missing_endpoint_identity"
REASON_SELF_LINK: Final[str] = "self_link_rejected"


class ProjectionError(ValueError):
    """Sanitized projection failure.

    Raised for MALFORMED source data: a missing required identity, an invalid
    closed-vocabulary value, or a structurally invalid link list. Raising (as
    opposed to skipping) is deliberate — the caller runs projection inside one
    transaction, so malformed input aborts the build rather than partially
    promoting untrusted rows into the derived index.

    The message never contains payload text, SQL, or secrets.
    """

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"projection_error: {reason}: {field}")
        self.field = field
        self.reason = reason


def _require(value: Optional[str], field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectionError(field, "missing_required_field")
    return value


def _optional(value: Optional[str], field: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProjectionError(field, "invalid_optional_field")
    text = value.strip()
    # An empty/whitespace string is an absent value in the M2/M4 substrate.
    # It is normalized to None here rather than stored as a forgeable ""
    # scope coordinate. A non-empty value is preserved exactly as stored.
    return value if text else None


def parse_link_list(raw: Optional[str], field: str) -> tuple[str, ...]:
    """Parse an explicit M4 ``linked_*_ids`` column into ordered ids.

    Two explicit encodings are accepted, matching what the M4 projector stores:
    a JSON array, or a comma-separated list. Nothing is inferred: an entry is
    used verbatim after whitespace stripping, duplicates collapse (the same
    link asserted twice is one link), and order is preserved so projection is
    reproducible.

    A structurally invalid value (JSON that is not an array of strings) is
    malformed source data and fails closed.
    """
    if raw is None:
        return ()
    if not isinstance(raw, str):
        raise ProjectionError(field, "invalid_link_list")
    text = raw.strip()
    if not text:
        return ()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except ValueError:
            raise ProjectionError(field, "malformed_link_list") from None
        if not isinstance(parsed, list):
            raise ProjectionError(field, "malformed_link_list")
        items = []
        for entry in parsed:
            if not isinstance(entry, str):
                raise ProjectionError(field, "malformed_link_list")
            items.append(entry)
    else:
        items = text.split(",")
    seen: list[str] = []
    for item in items:
        candidate = item.strip()
        if candidate and candidate not in seen:
            seen.append(candidate)
    return tuple(seen)


# ---------------------------------------------------------------------------
# Typed source records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EdgeSourceRecord:
    """One explicit link asserted by an approved canonical/project source.

    This is the ONLY shape the edge projector accepts. It names both typed
    endpoints, the source substrate that asserted the link, and the explicit
    reference within that substrate, so every derived edge is traceable and
    reproducible.

    ``relation_type`` is already in the closed M8 vocabulary: mapping from a
    source-specific name happens in the reader, where the approved mapping
    table lives, so an unmapped name can be reported rather than smuggled in.
    """

    from_resource_type: str
    from_resource_id: str
    relation_type: str
    to_resource_type: str
    to_resource_id: str
    relation_source: str
    source_ref: str
    profile_id: Optional[str] = None
    project_id: Optional[str] = None
    knowledge_space_id: Optional[str] = None
    lifecycle_status: str = "candidate"
    verification_status: Optional[str] = None
    source_event_id: Optional[str] = None
    trace_id: Optional[str] = None
    created_at: Optional[str] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None


@dataclass(frozen=True)
class EntitySourceRecord:
    """One explicitly supplied structured entity.

    Entities are created ONLY from explicit structured input (docs/plans/plan-m8.md §7,
    M8-OQ-2). There is no text extractor and no linker here: if a caller does
    not explicitly assert an entity, no entity exists.
    """

    entity_type: str
    canonical_name: str
    relation_source: str
    source_ref: str
    profile_id: Optional[str] = None
    project_id: Optional[str] = None
    knowledge_space_id: Optional[str] = None
    lifecycle_status: str = "candidate"
    source_event_id: Optional[str] = None
    trace_id: Optional[str] = None
    created_at: Optional[str] = None


@dataclass(frozen=True)
class MentionSourceRecord:
    """One explicitly supplied structured mention of an entity in a source.

    ``mention_text_hash`` is supplied pre-hashed, or computed here from
    ``mention_text`` which is then discarded. Raw span text is never carried
    into the derived index, so a redacted or secret-bearing span cannot be
    reconstructed from the graph.
    """

    entity: EntitySourceRecord
    source_event_id: str
    span_start: Optional[int] = None
    span_end: Optional[int] = None
    mention_text: Optional[str] = None
    mention_text_hash: Optional[str] = None
    trace_id: Optional[str] = None
    created_at: Optional[str] = None


@dataclass(frozen=True)
class MentionProjection:
    """A derived entity mention, ready for persistence.

    Deterministic: identity comes from the entity, the canonical source event,
    and the explicit span. A missing span stays ``None`` and is never guessed.
    """

    mention_id: str
    entity_id: str
    source_event_id: str
    mention_text_hash: str
    scope: ScopeMetadata
    provenance: Provenance
    trace_id: Optional[str] = None
    span_start: Optional[int] = None
    span_end: Optional[int] = None
    created_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mention_id": self.mention_id,
            "entity_id": self.entity_id,
            "source_event_id": self.source_event_id,
            "mention_text_hash": self.mention_text_hash,
            "span_start": self.span_start,
            "span_end": self.span_end,
            "scope": self.scope.to_dict(),
            "provenance": self.provenance.to_dict(),
        }

    def compute_content_hash(self) -> str:
        return content_hash(self.to_dict())


# ---------------------------------------------------------------------------
# Pure projection functions
# ---------------------------------------------------------------------------


def _build_provenance(
    *,
    relation_source: str,
    source_ref: str,
    source_event_id: Optional[str],
    trace_id: Optional[str],
    profile_id: Optional[str],
    project_id: Optional[str],
    knowledge_space_id: Optional[str],
) -> Provenance:
    try:
        return Provenance(
            relation_source=validate_relation_source(relation_source),
            source_ref=_require(source_ref, "source_ref"),
            projection_version=GRAPH_PROJECTION_VERSION,
            source_event_id=_optional(source_event_id, "source_event_id"),
            trace_id=_optional(trace_id, "trace_id"),
            profile_id=_optional(profile_id, "profile_id"),
            project_id=_optional(project_id, "project_id"),
            knowledge_space_id=_optional(knowledge_space_id, "knowledge_space_id"),
        )
    except ProjectionError:
        raise
    except ValueError as exc:  # VocabularyError / ProvenanceError
        raise ProjectionError("provenance", "invalid_provenance") from exc


def project_edge(record: EdgeSourceRecord) -> GraphEdge:
    """Project one explicit link into a derived ``GraphEdge``.

    Pure and deterministic. The resulting ``edge_id`` depends only on the typed
    endpoints, the relation type, the source reference, and the explicit scope
    — never on insertion order, rebuild time, or randomness.

    Lifecycle and verification are copied verbatim from the source. Projection
    is not a promotion path.
    """
    if not isinstance(record, EdgeSourceRecord):
        raise ProjectionError("record", "invalid_source_record")
    provenance = _build_provenance(
        relation_source=record.relation_source,
        source_ref=record.source_ref,
        source_event_id=record.source_event_id,
        trace_id=record.trace_id,
        profile_id=record.profile_id,
        project_id=record.project_id,
        knowledge_space_id=record.knowledge_space_id,
    )
    try:
        return GraphEdge(
            from_ref=ResourceRef(
                resource_type=validate_resource_type(record.from_resource_type),
                resource_id=_require(record.from_resource_id, "from_resource_id"),
            ),
            relation_type=record.relation_type,
            to_ref=ResourceRef(
                resource_type=validate_resource_type(record.to_resource_type),
                resource_id=_require(record.to_resource_id, "to_resource_id"),
            ),
            scope=ScopeMetadata(
                profile_id=_optional(record.profile_id, "profile_id"),
                project_id=_optional(record.project_id, "project_id"),
                knowledge_space_id=_optional(record.knowledge_space_id, "knowledge_space_id"),
            ),
            lifecycle_status=validate_lifecycle_status(record.lifecycle_status),
            provenance=provenance,
            verification_status=validate_verification_status(record.verification_status),
        )
    except ProjectionError:
        raise
    except ValueError as exc:  # VocabularyError / GraphContractError
        raise ProjectionError("edge", "invalid_edge_source") from exc


def project_entity(record: EntitySourceRecord) -> EntityRecord:
    """Project one explicitly supplied structured entity.

    Identity is ``(entity_type, normalized name, explicit scope)`` from the
    frozen M8.1 contract. The same textual name under a different profile,
    project, or knowledge space is a DIFFERENT entity and is never merged:
    flattening them would erase a scope boundary that authorization depends on.
    """
    if not isinstance(record, EntitySourceRecord):
        raise ProjectionError("record", "invalid_source_record")
    provenance = _build_provenance(
        relation_source=record.relation_source,
        source_ref=record.source_ref,
        source_event_id=record.source_event_id,
        trace_id=record.trace_id,
        profile_id=record.profile_id,
        project_id=record.project_id,
        knowledge_space_id=record.knowledge_space_id,
    )
    try:
        return EntityRecord(
            entity_type=validate_entity_type(record.entity_type),
            canonical_name=_require(record.canonical_name, "canonical_name"),
            scope=ScopeMetadata(
                profile_id=_optional(record.profile_id, "profile_id"),
                project_id=_optional(record.project_id, "project_id"),
                knowledge_space_id=_optional(record.knowledge_space_id, "knowledge_space_id"),
            ),
            lifecycle_status=validate_lifecycle_status(record.lifecycle_status),
            provenance=provenance,
        )
    except ProjectionError:
        raise
    except ValueError as exc:
        raise ProjectionError("entity", "invalid_entity_source") from exc


def project_mention(record: MentionSourceRecord) -> MentionProjection:
    """Project one explicitly supplied entity mention.

    The mention inherits its entity's scope, so a mention can never widen the
    scope of the entity it points at.
    """
    if not isinstance(record, MentionSourceRecord):
        raise ProjectionError("record", "invalid_source_record")
    entity = project_entity(record.entity)
    if record.mention_text_hash is not None:
        mention_hash = _require(record.mention_text_hash, "mention_text_hash")
    elif record.mention_text is not None:
        if not isinstance(record.mention_text, str):
            raise ProjectionError("mention_text", "invalid_mention_text")
        # Hash immediately; the raw span text is never returned or stored.
        mention_hash = content_hash({"mention_text": record.mention_text})
    else:
        raise ProjectionError("mention_text_hash", "missing_required_field")
    source_event_id = _require(record.source_event_id, "source_event_id")
    try:
        mention_id = derive_mention_id(
            entity_id=entity.entity_id,
            source_event_id=source_event_id,
            span_start=record.span_start,
            span_end=record.span_end,
        )
    except ValueError as exc:
        raise ProjectionError("span", "invalid_mention_span") from exc
    provenance = _build_provenance(
        relation_source=record.entity.relation_source,
        source_ref=record.entity.source_ref,
        source_event_id=source_event_id,
        trace_id=record.trace_id,
        profile_id=record.entity.profile_id,
        project_id=record.entity.project_id,
        knowledge_space_id=record.entity.knowledge_space_id,
    )
    return MentionProjection(
        mention_id=mention_id,
        entity_id=entity.entity_id,
        source_event_id=source_event_id,
        mention_text_hash=mention_hash,
        scope=entity.scope,
        provenance=provenance,
        trace_id=_optional(record.trace_id, "trace_id"),
        span_start=record.span_start,
        span_end=record.span_end,
        created_at=_optional(record.created_at, "created_at"),
    )


def map_m2_relation_type(source_relation: str) -> Optional[str]:
    """Map an M2 relation name to the closed M8 vocabulary, or ``None``.

    ``None`` means "no approved mapping exists". The caller reports it and
    drops the record; it must never fall back to a generic relation type.
    """
    if not isinstance(source_relation, str):
        return None
    return M2_RELATION_TYPE_MAP.get(source_relation)


def map_verification_subject_type(subject_type: Optional[str]) -> Optional[str]:
    """Map an M4 verification subject type to a typed resource type, or ``None``."""
    if not isinstance(subject_type, str):
        return None
    return M4_VERIFICATION_SUBJECT_MAP.get(subject_type)


def describe_projection() -> dict[str, Any]:
    """Introspectable description of what M8.2 projection does and does not do."""
    return {
        "graph_projection_version": GRAPH_PROJECTION_VERSION,
        "schema_version": 13,
        "relation_sources": sorted(member.value for member in RelationSource),
        "m2_relation_map": dict(sorted(M2_RELATION_TYPE_MAP.items())),
        "verification_subject_map": dict(sorted(M4_VERIFICATION_SUBJECT_MAP.items())),
        "graph_is_derived": True,
        "graph_is_truth": False,
        "makes_authorization_decisions": False,
        "resolves_conflicts": False,
        # M8.4 (introduced after M8.2) implements bounded authorization-first
        # temporal as-of/history reads over the derived temporal index; M8.5
        # implements the approved deterministic calibration engine. Neither is
        # reachable from the projector: projection scores nothing.
        "temporal_query_implemented": True,
        "calibration_scoring_implemented": True,
    }


__all__ = [
    "GRAPH_PROJECTION_VERSION",
    "M2_RELATION_TYPE_MAP",
    "M4_VERIFICATION_SUBJECT_MAP",
    "REASON_UNMAPPED_RELATION_TYPE",
    "REASON_UNMAPPED_SUBJECT_TYPE",
    "REASON_MISSING_ENDPOINT",
    "REASON_SELF_LINK",
    "ProjectionError",
    "EdgeSourceRecord",
    "EntitySourceRecord",
    "MentionSourceRecord",
    "MentionProjection",
    "parse_link_list",
    "project_edge",
    "project_entity",
    "project_mention",
    "map_m2_relation_type",
    "map_verification_subject_type",
    "describe_projection",
]
