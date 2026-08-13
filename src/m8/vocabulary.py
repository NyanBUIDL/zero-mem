"""M8.1 — closed vocabularies for derived M8 structures.

Every vocabulary here is CLOSED. An unknown value fails closed: it is rejected,
never coerced, never mapped to a nearest neighbour, and never admitted as a
trusted graph semantic. Arbitrary caller- or content-controlled strings must not
become graph vocabulary (docs/plans/plan-m8.md §7 "Unsupported relation types fail closed").

The lifecycle and verification vocabularies are NOT redefined here. They are
imported from the existing authoritative M1 contract
(``src/capture/event_types.py``) so M8 can never drift from the closed lifecycle
enum already enforced by migrations v7/v8.
"""

from __future__ import annotations

import enum
from typing import Final, FrozenSet

from src.capture.event_types import LifecycleStatus, VerificationStatus

# ---------------------------------------------------------------------------
# Resource types
# ---------------------------------------------------------------------------

#: The authoritative M5 resource-type literals, mirrored as the M8 node-type
#: vocabulary. M8 introduces NO new resource type and NO generic "node" type:
#: erasing resource-type identity would break the permanent M6.6 isolation
#: invariant (artifact-only grant != event access != relation access).
#:
#: Kept in exact sync with ``src/access/contracts.py::_VALID_RESOURCE_TYPES``;
#: a focused test asserts equality so the two can never diverge.
RESOURCE_TYPES: Final[FrozenSet[str]] = frozenset({
    "event",
    "trace",
    "relation",
    "charter",
    "requirement",
    "decision",
    "state",
    "verification",
    "artifact",
    "project_artifact",
    "corpus_source",
    "corpus_unit",
})


class EntityType(str, enum.Enum):
    """Closed entity-type vocabulary (docs/plans/plan-m8.md §6, M8-OQ-2).

    Entities are created ONLY from explicit structured input in later approved
    increments. No deterministic text rule, NLP extractor, or LLM may mint an
    entity type.
    """

    PERSON = "person"
    ORGANIZATION = "organization"
    PROJECT = "project"
    COMPONENT = "component"
    ARTIFACT = "artifact"
    CONCEPT = "concept"
    SOURCE = "source"
    TOOL = "tool"


class RelationType(str, enum.Enum):
    """Closed relation vocabulary approved in docs/plans/plan-m8.md §7 (M8-OQ-3).

    Every member must be materialized from an explicit canonical source record
    or an approved deterministic projection. None of these may be inferred from
    co-occurrence, centrality, string similarity, or recency.
    """

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    VERIFIES = "verifies"
    SUPERSEDES = "supersedes"
    DERIVED_FROM = "derived_from"
    REFERENCES = "references"
    RELATED_TO = "related_to"
    BELONGS_TO_PROJECT = "belongs_to_project"
    BELONGS_TO_PROFILE = "belongs_to_profile"
    BELONGS_TO_KNOWLEDGE_SPACE = "belongs_to_knowledge_space"
    ARTIFACT_OF = "artifact_of"
    SOURCE_OF = "source_of"
    DECISION_FOR = "decision_for"
    REQUIREMENT_FOR = "requirement_for"


class RelationSource(str, enum.Enum):
    """Closed vocabulary describing WHERE a derived relation came from.

    Provenance must identify the canonical substrate that asserted the link, so
    a derived edge can always be traced back and rebuilt. There is deliberately
    no ``inferred`` / ``heuristic`` / ``llm`` member: an edge with no explicit
    canonical source is not eligible to exist.
    """

    #: Explicit stored edge in the M2 ``zm_relations`` substrate.
    M2_RELATION = "m2_relation"
    #: Explicit scope mapping in the M2 ``zm_scopes`` substrate.
    M2_SCOPE = "m2_scope"
    #: Explicit artifact registry linkage in the M2 ``zm_artifacts`` substrate.
    M2_ARTIFACT = "m2_artifact"
    #: Explicit typed M4 project-memory operation record / stored link field.
    M4_PROJECT_LINK = "m4_project_link"
    #: Explicit M4 supersession field (``supersedes`` / ``replaced_by``).
    M4_SUPERSESSION = "m4_supersession"
    #: Explicit M4 verification record subject linkage.
    M4_VERIFICATION = "m4_verification"
    #: Explicit M10 corpus-extraction structural link (source_ref / duplicate_of).
    #: Authoritative per docs/plans/plan-m10.md §4 ("RelationSource gains a corpus_extraction
    #: member"); the v10 migration's zm_corpus_relations CHECK already hard-codes
    #: 'corpus_extraction'. Deterministic, never inferred/LLM.
    CORPUS_EXTRACTION = "corpus_extraction"


#: Closed lifecycle vocabulary, re-exported from the authoritative M1 contract.
LIFECYCLE_STATUSES: Final[FrozenSet[str]] = frozenset(
    member.value for member in LifecycleStatus
)

#: Closed verification vocabulary, re-exported from the authoritative contract.
VERIFICATION_STATUSES: Final[FrozenSet[str]] = frozenset(
    member.value for member in VerificationStatus
)


class VocabularyError(ValueError):
    """Sanitized closed-vocabulary violation.

    The message names the offending field and a truncated, newline-free echo of
    the rejected token only — never payload text, SQL, or secrets.
    """

    def __init__(self, field: str, value: object) -> None:
        token = str(value).replace("\n", " ").replace("\r", " ")
        if len(token) > 64:
            token = token[:64] + "...(truncated)"
        super().__init__(f"vocabulary_error: invalid_{field}: {token!r}")
        self.field = field


def validate_resource_type(value: str) -> str:
    """Return ``value`` if it is a known resource type, else fail closed."""
    if not isinstance(value, str) or value not in RESOURCE_TYPES:
        raise VocabularyError("resource_type", value)
    return value


def validate_entity_type(value: str) -> str:
    """Return ``value`` if it is a known entity type, else fail closed."""
    try:
        return EntityType(value).value
    except ValueError:
        raise VocabularyError("entity_type", value) from None


def validate_relation_type(value: str) -> str:
    """Return ``value`` if it is in the closed relation vocabulary.

    An unknown relation name is rejected outright. It is never stored as
    ``related_to``, never passed through as free text, and never treated as a
    trusted graph semantic.
    """
    try:
        return RelationType(value).value
    except ValueError:
        raise VocabularyError("relation_type", value) from None


def validate_relation_source(value: str) -> str:
    """Return ``value`` if it names an approved canonical relation source."""
    try:
        return RelationSource(value).value
    except ValueError:
        raise VocabularyError("relation_source", value) from None


def validate_lifecycle_status(value: str) -> str:
    """Return ``value`` if it is in the closed lifecycle enum, else fail closed."""
    if not isinstance(value, str) or value not in LIFECYCLE_STATUSES:
        raise VocabularyError("lifecycle_status", value)
    return value


def validate_verification_status(value: str | None) -> str | None:
    """Return ``value`` if it is a known verification status, or ``None``.

    ``None`` means "no verification recorded" and is preserved as ``None``. It
    is never upgraded to a positive verification value.
    """
    if value is None:
        return None
    if not isinstance(value, str) or value not in VERIFICATION_STATUSES:
        raise VocabularyError("verification_status", value)
    return value


__all__ = [
    "RESOURCE_TYPES",
    "EntityType",
    "RelationType",
    "RelationSource",
    "LIFECYCLE_STATUSES",
    "VERIFICATION_STATUSES",
    "VocabularyError",
    "validate_resource_type",
    "validate_entity_type",
    "validate_relation_type",
    "validate_relation_source",
    "validate_lifecycle_status",
    "validate_verification_status",
]
