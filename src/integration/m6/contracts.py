"""M6.1 — typed request/response contracts and strict validation.

READ-ONLY by construction: this module performs pure validation and shaping.
It imports NO SQLite, JSONL, projector, migration, grant, or WRITE facade.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# --- Fixed operation set: only READ is permitted on the M6 read surface. ---
class Operation(str, enum.Enum):
    READ = "READ"


# --- Resource types aligned with M5 grant resource restrictions. ---
class ResourceType(str, enum.Enum):
    EVENT = "event"
    REQUIREMENT = "requirement"
    DECISION = "decision"
    CHARTER = "charter"
    PROJECT_STATE = "project_state"
    VERIFICATION = "verification"
    ARTIFACT = "artifact"
    RELATION = "relation"


# --- Response envelope status. ---
class ResponseStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    EMPTY = "EMPTY"               # valid query, zero results (distinct from DENIED)
    POLICY_DENIED = "POLICY_DENIED"
    INVALID_REQUEST = "INVALID_REQUEST"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    UNSUPPORTED_TOOL = "UNSUPPORTED_TOOL"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    DOWNSTREAM_ERROR = "DOWNSTREAM_ERROR"


# Fields that must NEVER be accepted as caller-supplied authority. If present,
# the request is rejected at the contract layer and never reaches policy.
FORBIDDEN_AUTHORITY_FIELDS = frozenset({
    "admin", "is_admin", "trusted", "grant_admin", "grant", "verified",
    "cross_profile_allowed", "bypass_policy", "raw_sql", "authorization",
    "grant_object", "authorized_read_grant", "grant_rows",
})

# Fields that map to explicit, non-inferred identity/scope transport.
_KNOWN_FIELDS = frozenset({
    "tool", "operation", "requesting_profile_id", "target_profile_ids",
    "project_ids", "knowledge_space_ids", "isolated_mode", "include_global",
    "resource_type", "filters", "query", "search_text", "relation", "limit",
    "cursor", "include_source_event", "session_id",
})

# Limits reused from M3 conventions (no second pagination model invented).
MAX_LIMIT = 500
MAX_SEARCH_LENGTH = 4000
MAX_PAYLOAD_FIELDS = 64


class ContractError(ValueError):
    """Raised for malformed/invalid requests; mapped to a sanitized envelope."""


@dataclass(frozen=True)
class M6Request:
    """Validated, normalized M6 read request.

    Identity is explicit and never inferred. ``requesting_profile_id=None``
    means an unbound caller (valid M5 state). M6 transports identity to M5;
    it does not prove human identity.
    """

    tool: str
    operation: Operation = Operation.READ
    requesting_profile_id: Optional[str] = None
    target_profile_ids: Optional[List[str]] = None
    project_ids: Optional[List[str]] = None
    knowledge_space_ids: Optional[List[str]] = None
    isolated_mode: bool = False
    include_global: Optional[bool] = None
    resource_type: Optional[ResourceType] = None  # may be tool-fixed
    filters: Dict[str, Any] = field(default_factory=dict)
    query: Optional[str] = None
    search_text: Optional[str] = None
    relation: Optional[str] = None
    limit: Optional[int] = None
    cursor: Optional[str] = None
    include_source_event: bool = False
    session_id: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"tool": self.tool, "operation": self.operation.value}
        if self.requesting_profile_id is not None:
            out["requesting_profile_id"] = self.requesting_profile_id
        if self.target_profile_ids is not None:
            out["target_profile_ids"] = list(self.target_profile_ids)
        if self.project_ids is not None:
            out["project_ids"] = list(self.project_ids)
        if self.knowledge_space_ids is not None:
            out["knowledge_space_ids"] = list(self.knowledge_space_ids)
        out["isolated_mode"] = self.isolated_mode
        if self.include_global is not None:
            out["include_global"] = self.include_global
        if self.resource_type is not None:
            out["resource_type"] = self.resource_type.value
        if self.filters:
            out["filters"] = dict(self.filters)
        if self.query is not None:
            out["query"] = self.query
        if self.search_text is not None:
            out["search_text"] = self.search_text
        if self.relation is not None:
            out["relation"] = self.relation
        if self.limit is not None:
            out["limit"] = self.limit
        if self.cursor is not None:
            out["cursor"] = self.cursor
        if self.include_source_event:
            out["include_source_event"] = True
        if self.session_id is not None:
            out["session_id"] = self.session_id
        return out


@dataclass(frozen=True)
class M6Response:
    """Single stable sanitized response envelope.

    Never carries raw tracebacks, SQL, SQLite internals, unrestricted paths,
    secret values, raw grant records, or internal authorization details.
    """

    status: ResponseStatus
    results: List[Any] = field(default_factory=list)
    next_cursor: Optional[str] = None
    reason_code: Optional[str] = None
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"status": self.status.value}
        if self.results:
            out["results"] = self.results
        if self.next_cursor is not None:
            out["next_cursor"] = self.next_cursor
        if self.reason_code is not None:
            out["reason_code"] = self.reason_code
        out["diagnostics"] = dict(self.diagnostics)
        return out


def _as_str_list(value: Any, field_name: str) -> Optional[List[str]]:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ContractError(f"{field_name} must be a list of strings")
    # de-duplicate + order for determinism; never infer.
    return list(dict.fromkeys(value))


def validate_request(raw: Dict[str, Any]) -> M6Request:
    """Strictly validate and normalize a raw M6 request dict.

    Rejects unknown security-sensitive fields, unknown tools, non-READ
    operations, invalid enums/limits, and any caller authority fields. Pure:
    no I/O, no LLM, no network.
    """
    if not isinstance(raw, dict):
        raise ContractError("request must be an object")
    if len(raw) > MAX_PAYLOAD_FIELDS:
        raise ContractError("request too large")

    # Reject forbidden caller-authority fields outright.
    for bad in FORBIDDEN_AUTHORITY_FIELDS:
        if bad in raw:
            raise ContractError(f"field '{bad}' is not accepted on the read surface")

    # Reject unknown fields (strict contract; no silent authority leakage).
    for key in raw:
        if key not in _KNOWN_FIELDS:
            raise ContractError(f"unknown field '{key}'")

    tool = raw.get("tool")
    if not isinstance(tool, str) or not tool:
        raise ContractError("tool is required")
    # Tool allowlist is enforced by the registry; we only require a string here
    # and let the dispatcher reject unknown tools with UNSUPPORTED_TOOL.

    operation = raw.get("operation", "READ")
    if operation != Operation.READ.value:
        # Any non-READ operation is refused; never routed to WRITE authorization.
        from .errors import M6Error, M6ErrorCode
        raise M6Error(M6ErrorCode.UNSUPPORTED_OPERATION,
                      "only READ operation is supported on the M6 read surface")

    resource_type = None
    rt = raw.get("resource_type")
    if rt is not None:
        try:
            resource_type = ResourceType(rt)
        except ValueError:
            raise ContractError(f"invalid resource_type '{rt}'")

    limit = raw.get("limit")
    if limit is not None:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0 or limit > MAX_LIMIT:
            raise ContractError(f"limit must be an int in (0, {MAX_LIMIT}]")

    search_text = raw.get("search_text")
    if search_text is not None:
        if not isinstance(search_text, str) or len(search_text) > MAX_SEARCH_LENGTH:
            raise ContractError("search_text invalid or too long")

    query = raw.get("query")
    if query is not None and not isinstance(query, str):
        raise ContractError("query must be a string")

    relation = raw.get("relation")
    if relation is not None and not isinstance(relation, str):
        raise ContractError("relation must be a string")

    cursor = raw.get("cursor")
    if cursor is not None and not isinstance(cursor, str):
        raise ContractError("cursor must be a string")

    if raw.get("isolated_mode") not in (None, True, False):
        raise ContractError("isolated_mode must be a boolean")

    include_source_event = bool(raw.get("include_source_event", False))

    filters = raw.get("filters")
    if filters is not None and not isinstance(filters, dict):
        raise ContractError("filters must be an object")

    session_id = raw.get("session_id")
    if session_id is not None and not isinstance(session_id, str):
        raise ContractError("session_id must be a string")

    return M6Request(
        tool=tool,
        operation=Operation.READ,
        requesting_profile_id=raw.get("requesting_profile_id"),  # explicit only; may be None
        target_profile_ids=_as_str_list(raw.get("target_profile_ids"), "target_profile_ids"),
        project_ids=_as_str_list(raw.get("project_ids"), "project_ids"),
        knowledge_space_ids=_as_str_list(raw.get("knowledge_space_ids"), "knowledge_space_ids"),
        isolated_mode=bool(raw.get("isolated_mode", False)),
        include_global=raw.get("include_global"),
        resource_type=resource_type,
        filters=dict(filters) if filters else {},
        query=query,
        search_text=search_text,
        relation=relation,
        limit=limit,
        cursor=cursor,
        include_source_event=include_source_event,
        session_id=session_id,
    )
