"""M8.1 — frozen graph node/edge contracts (structure only, no traversal).

This module freezes the SHAPE of derived graph records. It deliberately
implements no projection (M8.2), no traversal, no neighbour lookup, and no
authorization checking (M8.3). There is intentionally no ``degree()``,
``neighbors()``, ``centrality()``, or ``rank()`` anywhere in this package.

Authority boundaries baked into these contracts:

- **Graph is not truth.** A ``GraphEdge`` asserts that a canonical source
  recorded a link. It does not assert the link is correct, verified, or
  current. ``lifecycle_status`` and ``verification_status`` are carried through
  from the source unchanged; the edge never upgrades them.
- **Nodes are typed resources, never generic blobs.** Every endpoint carries an
  explicit ``resource_type``, preserving the permanent M6.6 isolation invariant
  (artifact-only grant != event access != relation access).
- **Scope is metadata for a later authorization check, not a decision.** Each
  record carries ``profile_id`` / ``project_id`` / ``knowledge_space_id`` so
  M8.3 can hand each endpoint to M5 independently. Nothing here evaluates,
  caches, or infers access. M5 remains the sole authority.
- **No authorization inheritance.** An edge's own scope grants nothing about
  its endpoints; ``authorization_metadata()`` emits one independent descriptor
  per endpoint precisely so a later traversal cannot inherit a decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Optional

from .identity import canonical_json, content_hash, derive_edge_id, derive_entity_id
from .provenance import Provenance, validate_provenance
from .temporal_contract import TemporalMetadata
from .vocabulary import (
    validate_entity_type,
    validate_lifecycle_status,
    validate_relation_type,
    validate_resource_type,
    validate_verification_status,
)

#: Frozen graph-contract version. Participates in provenance/rebuild identity.
GRAPH_CONTRACT_VERSION: Final[str] = "v1"


class GraphContractError(ValueError):
    """Sanitized graph-contract violation."""

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"graph_contract_error: {reason}: {field}")
        self.field = field
        self.reason = reason


def _require_id(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GraphContractError(field, "missing_required_field")
    return value


def _optional_id(value: Optional[str], field: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise GraphContractError(field, "invalid_optional_field")
    return value


@dataclass(frozen=True)
class ResourceRef:
    """A typed reference to one authorizable resource.

    ``resource_type`` is mandatory and never erased. Two references with the
    same ``resource_id`` but different ``resource_type`` are DIFFERENT
    resources and must be authorized independently.
    """

    resource_type: str
    resource_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "resource_type", validate_resource_type(self.resource_type))
        object.__setattr__(self, "resource_id", _require_id(self.resource_id, "resource_id"))

    def to_dict(self) -> dict[str, str]:
        return {"resource_type": self.resource_type, "resource_id": self.resource_id}


@dataclass(frozen=True)
class ScopeMetadata:
    """Explicit scope descriptor used later for authorization-first reads.

    This is INPUT to M5, never a substitute for it. ``None`` means "not scoped
    to one", which is a real, distinct state — never a wildcard, and never a
    reason to widen a read.
    """

    profile_id: Optional[str] = None
    project_id: Optional[str] = None
    knowledge_space_id: Optional[str] = None

    def __post_init__(self) -> None:
        for field in ("profile_id", "project_id", "knowledge_space_id"):
            object.__setattr__(self, field, _optional_id(getattr(self, field), field))

    def to_dict(self) -> dict[str, Optional[str]]:
        return {
            "profile_id": self.profile_id,
            "project_id": self.project_id,
            "knowledge_space_id": self.knowledge_space_id,
        }


@dataclass(frozen=True)
class GraphNode:
    """A derived, typed graph node.

    Not a fact. A node's presence means a canonical record exists with this
    identity and scope, nothing more.
    """

    ref: ResourceRef
    scope: ScopeMetadata
    lifecycle_status: str
    provenance: Provenance
    verification_status: Optional[str] = None
    temporal: Optional[TemporalMetadata] = None

    def __post_init__(self) -> None:
        if not isinstance(self.ref, ResourceRef):
            raise GraphContractError("ref", "invalid_resource_ref")
        if not isinstance(self.scope, ScopeMetadata):
            raise GraphContractError("scope", "invalid_scope_metadata")
        object.__setattr__(
            self, "lifecycle_status", validate_lifecycle_status(self.lifecycle_status)
        )
        object.__setattr__(
            self, "verification_status", validate_verification_status(self.verification_status)
        )
        validate_provenance(self.provenance)
        if self.temporal is not None and not isinstance(self.temporal, TemporalMetadata):
            raise GraphContractError("temporal", "invalid_temporal_metadata")

    @property
    def node_key(self) -> tuple[str, str]:
        """Visited-set key for a later bounded traversal: (type, id)."""
        return (self.ref.resource_type, self.ref.resource_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_contract_version": GRAPH_CONTRACT_VERSION,
            "ref": self.ref.to_dict(),
            "scope": self.scope.to_dict(),
            "lifecycle_status": self.lifecycle_status,
            "verification_status": self.verification_status,
            "temporal": self.temporal.to_dict() if self.temporal else None,
            "provenance": self.provenance.to_dict(),
        }

    def compute_content_hash(self) -> str:
        return content_hash(self.to_dict())

    def authorization_metadata(self) -> dict[str, Any]:
        """Descriptor a later increment hands to M5 for THIS node alone.

        Contains no decision, no grant, and no allow/deny field — only the
        typed identity and explicit scope M5 needs as input.
        """
        return {
            "resource_type": self.ref.resource_type,
            "resource_id": self.ref.resource_id,
            **self.scope.to_dict(),
        }


@dataclass(frozen=True)
class GraphEdge:
    """A derived, typed, provenance-bearing graph edge.

    The edge is metadata about an explicitly recorded link. Its existence is
    not evidence that the link is true, verified, or current.
    """

    from_ref: ResourceRef
    relation_type: str
    to_ref: ResourceRef
    scope: ScopeMetadata
    lifecycle_status: str
    provenance: Provenance
    verification_status: Optional[str] = None
    temporal: Optional[TemporalMetadata] = None

    def __post_init__(self) -> None:
        if not isinstance(self.from_ref, ResourceRef):
            raise GraphContractError("from_ref", "invalid_resource_ref")
        if not isinstance(self.to_ref, ResourceRef):
            raise GraphContractError("to_ref", "invalid_resource_ref")
        if not isinstance(self.scope, ScopeMetadata):
            raise GraphContractError("scope", "invalid_scope_metadata")
        object.__setattr__(self, "relation_type", validate_relation_type(self.relation_type))
        object.__setattr__(
            self, "lifecycle_status", validate_lifecycle_status(self.lifecycle_status)
        )
        object.__setattr__(
            self, "verification_status", validate_verification_status(self.verification_status)
        )
        validate_provenance(self.provenance)
        if self.temporal is not None and not isinstance(self.temporal, TemporalMetadata):
            raise GraphContractError("temporal", "invalid_temporal_metadata")

    @property
    def edge_id(self) -> str:
        """Deterministic edge identity, including both endpoint resource types."""
        return derive_edge_id(
            from_resource_type=self.from_ref.resource_type,
            from_resource_id=self.from_ref.resource_id,
            relation_type=self.relation_type,
            to_resource_type=self.to_ref.resource_type,
            to_resource_id=self.to_ref.resource_id,
            source_ref=self.provenance.source_ref,
            profile_id=self.scope.profile_id,
            project_id=self.scope.project_id,
            knowledge_space_id=self.scope.knowledge_space_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_contract_version": GRAPH_CONTRACT_VERSION,
            "edge_id": self.edge_id,
            "from": self.from_ref.to_dict(),
            "relation_type": self.relation_type,
            "to": self.to_ref.to_dict(),
            "scope": self.scope.to_dict(),
            "lifecycle_status": self.lifecycle_status,
            "verification_status": self.verification_status,
            "temporal": self.temporal.to_dict() if self.temporal else None,
            "provenance": self.provenance.to_dict(),
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def compute_content_hash(self) -> str:
        return content_hash(self.to_dict())

    def authorization_metadata(self) -> dict[str, Any]:
        """Independent authorization descriptors for edge and BOTH endpoints.

        Three separate descriptors are emitted on purpose. A later traversal
        must authorize each one against M5 separately; authorizing the edge
        must never imply authorization of either endpoint.
        """
        return {
            "edge": {"relation_type": self.relation_type, **self.scope.to_dict()},
            "from": {
                "resource_type": self.from_ref.resource_type,
                "resource_id": self.from_ref.resource_id,
                **self.scope.to_dict(),
            },
            "to": {
                "resource_type": self.to_ref.resource_type,
                "resource_id": self.to_ref.resource_id,
                **self.scope.to_dict(),
            },
        }


@dataclass(frozen=True)
class EntityRecord:
    """A derived typed entity.

    Entities are created ONLY from explicit structured input in a later
    approved increment. This contract exists so that when they are, their
    identity and scope are already frozen and deterministic.
    """

    entity_type: str
    canonical_name: str
    scope: ScopeMetadata
    lifecycle_status: str
    provenance: Provenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "entity_type", validate_entity_type(self.entity_type))
        object.__setattr__(
            self, "canonical_name", _require_id(self.canonical_name, "canonical_name")
        )
        if not isinstance(self.scope, ScopeMetadata):
            raise GraphContractError("scope", "invalid_scope_metadata")
        object.__setattr__(
            self, "lifecycle_status", validate_lifecycle_status(self.lifecycle_status)
        )
        validate_provenance(self.provenance)

    @property
    def entity_id(self) -> str:
        return derive_entity_id(
            entity_type=self.entity_type,
            canonical_name=self.canonical_name,
            profile_id=self.scope.profile_id,
            project_id=self.scope.project_id,
            knowledge_space_id=self.scope.knowledge_space_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_contract_version": GRAPH_CONTRACT_VERSION,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "canonical_name": self.canonical_name,
            "scope": self.scope.to_dict(),
            "lifecycle_status": self.lifecycle_status,
            "provenance": self.provenance.to_dict(),
        }

    def compute_content_hash(self) -> str:
        return content_hash(self.to_dict())


__all__ = [
    "GRAPH_CONTRACT_VERSION",
    "GraphContractError",
    "ResourceRef",
    "ScopeMetadata",
    "GraphNode",
    "GraphEdge",
    "EntityRecord",
]
