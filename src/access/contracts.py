"""M5.1 policy contracts — typed deterministic access-request/decision models.

This module defines ONLY the data contracts and pure normalization helpers for
M5.1. It does NOT integrate with M3/M4 retrieval, does NOT implement persistent
grants, and does NOT write audit events. See the approved M5 plan (§4, §5, §8).

Authentication is explicitly out of scope: a caller supplies an explicit
`requesting_profile_id` (or ``None`` for an unbound caller). Identity is never
inferred from cwd, session text, file path, relation graph, or any other
environment signal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

# ---------------------------------------------------------------------------
# Operation + resource literals
# ---------------------------------------------------------------------------

# M5 only supports two operations (directive: "Do not use arbitrary free-form
# operations."). Any other value is an invalid request.
READ = "READ"
WRITE = "WRITE"
_VALID_OPERATIONS = (READ, WRITE)


class Operation(str, Enum):
    """Explicit operation model (READ | WRITE)."""

    READ = READ
    WRITE = WRITE

    @classmethod
    def parse(cls, value: str) -> "Operation":
        """Parse a raw operation string; raise ``ValueError`` if invalid.

        Structured failure (not a raw exception string) is surfaced by the
        policy layer as ``DENY_INVALID_REQUEST``.
        """
        if value not in _VALID_OPERATIONS:
            raise ValueError(f"invalid operation: {value!r}")
        return cls(value)


# Resource types are validated literals, not free-form. None means "all".
_VALID_RESOURCE_TYPES = {
    "event", "trace", "relation", "charter", "requirement",
    "decision", "state", "verification", "artifact", "project_artifact",
}


# ---------------------------------------------------------------------------
# Fixed reason codes (sanitized; never raw exceptions / paths / secrets)
# ---------------------------------------------------------------------------

class ReasonCode(str, Enum):
    ALLOW_LOCAL_PROFILE_READ = "ALLOW_LOCAL_PROFILE_READ"
    ALLOW_GLOBAL_READ = "ALLOW_GLOBAL_READ"
    ALLOW_LOCAL_WRITE = "ALLOW_LOCAL_WRITE"
    DENY_GLOBAL_WRITE = "DENY_GLOBAL_WRITE"
    DENY_CROSS_PROFILE_READ = "DENY_CROSS_PROFILE_READ"
    DENY_CROSS_PROFILE_WRITE = "DENY_CROSS_PROFILE_WRITE"
    DENY_CROSS_PROJECT = "DENY_CROSS_PROJECT"
    DENY_ISOLATED_SCOPE_ESCAPE = "DENY_ISOLATED_SCOPE_ESCAPE"
    DENY_UNKNOWN_PROFILE = "DENY_UNKNOWN_PROFILE"
    DENY_UNKNOWN_PROJECT = "DENY_UNKNOWN_PROJECT"
    DENY_UNKNOWN_SPACE = "DENY_UNKNOWN_SPACE"
    DENY_UNAUTHORIZED_SPACE = "DENY_UNAUTHORIZED_SPACE"
    DENY_UNBOUND_PROTECTED = "DENY_UNBOUND_PROTECTED"
    DENY_INVALID_REQUEST = "DENY_INVALID_REQUEST"

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.value


# ---------------------------------------------------------------------------
# AccessRequest
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AccessRequest:
    """Typed deterministic policy input.

    Only plan-approved fields are present. Missing identifiers stay ``None``
    (NEVER inferred). ``requesting_profile_id=None`` means an *unbound* caller.
    """

    operation: str
    requesting_profile_id: Optional[str] = None
    target_profile_ids: Optional[List[str]] = None
    project_ids: Optional[List[str]] = None
    knowledge_space_ids: Optional[List[str]] = None
    include_global: Optional[bool] = None  # None => policy default (True for READ)
    isolated_mode: bool = False
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Validation + normalization (pure; no I/O, no LLM, no network)
    # ------------------------------------------------------------------
    def validate(self) -> "AccessRequest":
        """Return a normalized copy, raising ``ValueError`` on invalid input.

        Normalization rules:
        - operation must be READ/WRITE;
        - resource_type (if given) must be a known literal;
        - profile/project/space id lists are de-duplicated, ordered, and
          copied so callers cannot mutate internal state;
        - include_global resolves to a concrete bool (default True);
        - explicit identifiers are preserved verbatim (no inference).
        """
        # 1. operation
        op = Operation.parse(self.operation).value
        # 2. resource_type
        rt = self.resource_type
        if rt is not None and rt not in _VALID_RESOURCE_TYPES:
            raise ValueError(f"invalid resource_type: {rt!r}")
        # 3. identifier lists: dedupe + stable order (deterministic)
        target_profiles = _normalize_ids(self.target_profile_ids)
        projects = _normalize_ids(self.project_ids)
        spaces = _normalize_ids(self.knowledge_space_ids)
        # 4. include_global default
        include_global = True if self.include_global is None else bool(self.include_global)
        # 5. explicit requesting profile preserved (None stays None)
        requester = self.requesting_profile_id
        return AccessRequest(
            operation=op,
            requesting_profile_id=requester,
            target_profile_ids=target_profiles,
            project_ids=projects,
            knowledge_space_ids=spaces,
            include_global=include_global,
            isolated_mode=bool(self.isolated_mode),
            resource_type=rt,
            resource_id=self.resource_id,
        )

    # Convenience accessors -------------------------------------------------
    @property
    def is_unbound(self) -> bool:
        return self.requesting_profile_id is None

    def target_profiles(self) -> List[str]:
        return list(self.target_profile_ids or [])


def _normalize_ids(ids: Optional[List[str]]) -> Optional[List[str]]:
    """De-duplicate + sort for deterministic normalization.

    Returns ``None`` when input is ``None`` (meaning "derive from operation"),
    otherwise a sorted unique list. Never infers missing ids.
    """
    if ids is None:
        return None
    return sorted(set(ids))


# ---------------------------------------------------------------------------
# AllowedScope (normalized authorization result)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AllowedScope:
    """Normalized authorized scope produced by the policy.

    Critical invariants (M5 plan §5 / directive "AllowedScope"):
    - a project permission does NOT add another profile;
    - a profile permission does NOT implicitly add every project/space;
    - relations never expand this scope;
    - ``global_read_allowed`` is set only by the global-READ rule or an
      explicit global grant (not implied by project/space/profile permission).
    """

    operation: str
    allowed_profile_ids: List[str] = field(default_factory=list)
    allowed_project_ids: List[str] = field(default_factory=list)
    allowed_knowledge_space_ids: List[str] = field(default_factory=list)
    global_read_allowed: bool = False
    resource_types: Optional[List[str]] = None
    isolated: bool = False

    def as_dict(self) -> dict:
        return {
            "operation": self.operation,
            "allowed_profile_ids": list(self.allowed_profile_ids),
            "allowed_project_ids": list(self.allowed_project_ids),
            "allowed_knowledge_space_ids": list(self.allowed_knowledge_space_ids),
            "global_read_allowed": self.global_read_allowed,
            "resource_types": (None if self.resource_types is None
                               else list(self.resource_types)),
            "isolated": self.isolated,
        }


# ---------------------------------------------------------------------------
# AccessDecision
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AccessDecision:
    """Deterministic typed policy result.

    Contains only audit-safe, non-secret metadata. No raw SQL, no unrestricted
    local paths, no raw policy internals, no exception text.
    """

    allow: bool
    normalized_scope: AllowedScope
    denied_scopes: List[str] = field(default_factory=list)
    reason_code: str = ""
    grant_refs: List[str] = field(default_factory=list)
    decision_id: Optional[str] = None  # correlation only; never affects semantics

    def as_dict(self) -> dict:
        return {
            "allow": self.allow,
            "normalized_scope": self.normalized_scope.as_dict(),
            "denied_scopes": list(self.denied_scopes),
            "reason_code": self.reason_code,
            "grant_refs": list(self.grant_refs),
            "decision_id": self.decision_id,
        }


__all__ = [
    "READ", "WRITE", "Operation", "ReasonCode",
    "AccessRequest", "AllowedScope", "AccessDecision",
]
