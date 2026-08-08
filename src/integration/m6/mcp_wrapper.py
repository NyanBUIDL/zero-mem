"""M6.1 — thin MCP-facing wrapper foundation.

Responsibilities (transport only):
* expose typed tool schemas (name + allowed input fields);
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

from .contracts import M6Response, validate_request
from .dispatcher import Dispatcher, dispatch
from .errors import M6ErrorCode
from .tools import list_tool_names


def tool_schemas() -> List[Dict[str, Any]]:
    """Return minimal MCP-style tool definitions (name + input schema)."""
    props = {
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
    return [
        {
            "name": name,
            "description": f"Zero-Mem read tool: {name}",
            "inputSchema": {
                "type": "object",
                "properties": {"tool": {"type": "string", "const": name}, "operation": {"type": "string", "const": "READ"}, **props},
                "required": ["tool"],
                "additionalProperties": False,
            },
        }
        for name in list_tool_names()
    ]


def handle_call(tool_name: str, arguments: Dict[str, Any], *,
                dispatcher: Dispatcher | None = None) -> Dict[str, Any]:
    """MCP entry point: validate args, dispatch, return serialized envelope."""
    if not isinstance(arguments, dict):
        return M6Response(
            status=__import__("src.integration.m6.contracts", fromlist=["ResponseStatus"]).ResponseStatus.INVALID_REQUEST,
            reason_code=M6ErrorCode.INVALID_REQUEST,
        ).to_dict()
    payload = dict(arguments)
    payload.setdefault("tool", tool_name)
    try:
        resp = dispatch(payload, dispatcher=dispatcher)
    except Exception:
        # Transport-level failure must never expose internals.
        return M6Response(
            status=__import__("src.integration.m6.contracts", fromlist=["ResponseStatus"]).ResponseStatus.DOWNSTREAM_ERROR,
            reason_code=M6ErrorCode.DOWNSTREAM_ERROR,
            diagnostics={"bounded": True},
        ).to_dict()
    return resp.to_dict()


def serialize(response: M6Response) -> str:
    return json.dumps(response.to_dict())
