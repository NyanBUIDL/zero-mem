"""M6.1 — thin MCP-facing wrapper foundation.

Responsibilities (transport only):
* expose typed tool schemas (name + agent-facing description + allowed input fields);
* deserialize/validate incoming arguments through the shared contracts;
* call the transport-independent dispatcher;
* serialize the sanitized response envelope.

It contains NO policy logic, NO SQL, NO JSONL logic, NO grant logic, NO M3/M4
business logic. Memory semantics live entirely behind AuthorizedReadService
(wired in M6.2/M6.3).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .contracts import M6Response, ResponseStatus, validate_request
from .dispatcher import Dispatcher, dispatch
from .errors import M6ErrorCode
from .tools import TOOL_REGISTRY, list_tool_names

# --- Agent-facing tool documentation (DEF-062) --------------------------------
# Descriptions say WHEN to call a tool, which arguments matter and what comes
# back, in as few tokens as practical: tools/list is paid for by every session.
_READ_ONLY = "Read-only; only content you are authorized to read is returned."
_PROJECT_ARGS = "Pass project_ids=[<project id>] (required). "
_EVENT_FILTERS = ("profile_filter", "project_filter", "session_filter",
                  "verification_filter", "lifecycle_filter", "created_at_after",
                  "created_at_before")

_TOOL_DOCS: Dict[str, Dict[str, Any]] = {
    "corpus_search": {
        "description": (
            "Search the shared memory and knowledge base (personas, workflows, skills, "
            "facts, dev history, ingested notes and files) by keywords. Call this first "
            "when you need background, user preferences, past decisions or reference text. "
            "Pass search_text (plain words). Keep limit small (default 20, max 500). Add "
            "knowledge_space_ids (e.g. [\"ks-shared\"]) to include a shared space you were "
            "granted; omit it for your own rows plus global ones. Narrow with "
            "filters.memory_type (persona, workflow, skill, devlog, fact, ...) and "
            "filters.external_ref_prefix (e.g. \"mem://skill/\"). Returns ranked text "
            "units with normalized_text, external_ref, memory_type and source ids. "
            + _READ_ONLY),
        "args": ("search_text", "limit", "knowledge_space_ids", "filters"),
        "required": ["search_text"],
        "filters": {
            "properties": {
                "memory_type": {"type": "string",
                                "description": "persona, workflow, skill, devlog, fact, ..."},
                "external_ref_prefix": {"type": "string", "description": "e.g. mem://skill/"},
            },
            "additionalProperties": False,
        },
    },
    "memory_search": {
        "description": (
            "Full-text search over captured conversation and tool events (event metadata, "
            "not file content). Call when you need to find past events by words. Pass "
            "search_text (required), a small limit, and cursor (a previous next_cursor) to "
            "page. Optional filters: " + ", ".join(_EVENT_FILTERS) + ". Returns event "
            "views (event_id, event_type, created_at, ids). " + _READ_ONLY),
        "args": ("search_text", "limit", "cursor", "filters"),
        "required": ["search_text"],
        "filters": {"properties": {k: {"type": "string"} for k in _EVENT_FILTERS}},
    },
    "memory_query": {
        "description": (
            "List captured events by structured filters, without a text query, in a "
            "deterministic order. Call to browse the events of a session or project. "
            "Filters: " + ", ".join(_EVENT_FILTERS) + ". Use a small limit and cursor "
            "(a previous next_cursor) to page. Returns event views (event_id, event_type, "
            "created_at, ids). " + _READ_ONLY),
        "args": ("limit", "cursor", "filters"),
        "filters": {"properties": {k: {"type": "string"} for k in _EVENT_FILTERS}},
    },
    "memory_get_event": {
        "description": (
            "Fetch one captured event by id. Call after a search or query when you need that "
            "single event. Pass the id as filters.event_id (or query). Returns one event view, "
            "or EMPTY when it does not exist or you may not read it. " + _READ_ONLY),
        "args": ("filters", "query"),
        "filters": {"properties": {"event_id": {"type": "string"}}},
    },
    "memory_get_related": {
        "description": (
            "List the events linked to one event through stored relations. Call to follow "
            "provenance from an event. Pass the id as filters.event_id (or query); optional "
            "relation = incoming, outgoing, parent or children; small limit, cursor to page. "
            "Returns relation edges with the target event view. " + _READ_ONLY),
        "args": ("filters", "query", "relation", "limit", "cursor"),
        "filters": {"properties": {"event_id": {"type": "string"}}},
    },
    "project_get_charter": {
        "description": (
            "Get the charter (purpose and scope) of one project. Call when you start work on "
            "a project. " + _PROJECT_ARGS + "Optional filters.charter_id selects a version; "
            "include_source_event=true adds the originating event reference. Returns the "
            "charter record, or EMPTY. " + _READ_ONLY),
        "args": ("project_ids", "filters", "include_source_event"),
        "filters": {"properties": {"charter_id": {"type": "string"}}},
    },
    "project_list_requirements": {
        "description": (
            "List the requirements recorded for one project. Call to check what the project "
            "must do before changing it. " + _PROJECT_ARGS + "Use a small limit and cursor "
            "(a previous next_cursor) to page. " + _READ_ONLY),
        "args": ("project_ids", "limit", "cursor"),
    },
    "project_list_decisions": {
        "description": (
            "List the decisions recorded for one project. Call to learn why the project is "
            "the way it is and to avoid contradicting an earlier decision. " + _PROJECT_ARGS
            + "Use a small limit and cursor (a previous next_cursor) to page. " + _READ_ONLY),
        "args": ("project_ids", "limit", "cursor"),
    },
    "project_get_state": {
        "description": (
            "Get the current recorded state of one project (what is done, in progress, "
            "blocked). Call to resume work. " + _PROJECT_ARGS + "Returns the state entries, "
            "or EMPTY. " + _READ_ONLY),
        "args": ("project_ids",),
    },
    "project_list_verifications": {
        "description": (
            "List the verification records of one project (what was verified, by what "
            "evidence). Call before treating a project claim as verified. " + _PROJECT_ARGS
            + "Use a small limit and cursor (a previous next_cursor) to page. " + _READ_ONLY),
        "args": ("project_ids", "limit", "cursor"),
    },
    "project_list_artifacts": {
        "description": (
            "List the artifacts of one project as metadata only (id, type, version, safe "
            "reference); file contents are never returned. " + _PROJECT_ARGS + "Use a small "
            "limit and cursor (a previous next_cursor) to page. " + _READ_ONLY),
        "args": ("project_ids", "limit", "cursor"),
    },
}

# Argument schemas. Every property the contract accepts stays declared (so existing
# clients keep validating); only the arguments that matter for a tool carry docs.
_PROP_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "requesting_profile_id": {"type": "string"},
    "target_profile_ids": {"type": "array", "items": {"type": "string"}},
    "project_ids": {"type": "array", "items": {"type": "string"}},
    "knowledge_space_ids": {"type": "array", "items": {"type": "string"}},
    "isolated_mode": {"type": "boolean"},
    "include_global": {"type": "boolean"},
    "resource_type": {"type": "string"},
    "filters": {"type": "object"},
    "query": {"type": "string"},
    "search_text": {"type": "string"},
    "relation": {"type": "string"},
    "limit": {"type": "integer"},
    "cursor": {"type": "string"},
    "include_source_event": {"type": "boolean"},
    "session_id": {"type": "string"},
}

_PROP_DOCS: Dict[str, Dict[str, Any]] = {
    "requesting_profile_id": {"description": "Your profile id; omit if the server pins it."},
    "target_profile_ids": {"description": "Another profile's rows (needs a grant)."},
    "project_ids": {"description": "Project id(s) to read."},
    "knowledge_space_ids": {"description": "Shared spaces to include, e.g. [\"ks-shared\"]."},
    "search_text": {"description": "Plain keywords; hyphenated terms are fine."},
    "query": {"description": "Event id (alternative to filters.event_id)."},
    "relation": {"enum": ["incoming", "outgoing", "parent", "children"]},
    "limit": {"minimum": 1, "maximum": 500, "description": "Max results; keep small."},
    "cursor": {"description": "next_cursor from the previous page."},
    "include_source_event": {"description": "Also return the originating event reference."},
}

# Scope arguments are documented on every tool.
_ALWAYS_DOCUMENTED = frozenset({"requesting_profile_id", "target_profile_ids",
                                "knowledge_space_ids"})


def _tool_schema(name: str, *, include_identity: bool) -> Dict[str, Any]:
    doc = _TOOL_DOCS.get(name, {})
    documented = set(doc.get("args", ())) | _ALWAYS_DOCUMENTED
    props: Dict[str, Any] = {
        "tool": {"type": "string", "const": name,
                 "description": "Optional; ignored."},
        "operation": {"type": "string", "const": "READ"},
    }
    for key, schema in _PROP_SCHEMAS.items():
        if key == "requesting_profile_id" and not include_identity:
            continue  # DEF-052: identity is pinned server-side, never caller-supplied
        entry = dict(schema)
        if key in documented:
            entry.update(_PROP_DOCS.get(key, {}))
        if key == "filters" and "filters" in doc:
            entry.update(doc["filters"])
        props[key] = entry
    spec = TOOL_REGISTRY.get(name)
    out: Dict[str, Any] = {
        "name": name,
        "description": doc.get("description") or (spec.description if spec else name),
        "inputSchema": {
            "type": "object",
            "properties": props,
            "additionalProperties": False,
        },
    }
    if doc.get("required"):
        out["inputSchema"]["required"] = list(doc["required"])
    return out


def tool_schemas(*, include_identity: bool = True) -> List[Dict[str, Any]]:
    """Return MCP-style tool definitions (name, agent-facing description, input schema).

    ``tool`` is declared (``const`` = the tool name) but never required, and the called
    tool name always wins (``handle_call``).  ``include_identity=False`` drops
    ``requesting_profile_id`` from every schema: used when the server pins the identity.
    """
    return [_tool_schema(name, include_identity=include_identity)
            for name in list_tool_names()]


def handle_call(tool_name: str, arguments: Dict[str, Any], *,
                dispatcher: Dispatcher | None = None) -> Dict[str, Any]:
    """MCP entry point: validate args, dispatch, return serialized envelope."""
    if not isinstance(arguments, dict):
        return M6Response(
            status=ResponseStatus.INVALID_REQUEST,
            reason_code=M6ErrorCode.INVALID_REQUEST,
        ).to_dict()
    payload = dict(arguments)
    # DEF-062: the called tool name is authoritative; ``arguments.tool`` is never
    # allowed to redirect the call to another tool (a per-tool client allowlist
    # would otherwise be bypassable).
    payload["tool"] = tool_name
    try:
        resp = dispatch(payload, dispatcher=dispatcher)
    except Exception:
        # Transport-level failure must never expose internals.
        return M6Response(
            status=ResponseStatus.DOWNSTREAM_ERROR,
            reason_code=M6ErrorCode.DOWNSTREAM_ERROR,
            diagnostics={"bounded": True},
        ).to_dict()
    return resp.to_dict()


def serialize(response: M6Response) -> str:
    return json.dumps(response.to_dict())
