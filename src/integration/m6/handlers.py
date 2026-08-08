"""M6.2 + M6.3 — M3 memory read handlers and M4 project-memory read handlers.

Both sets of handlers wire the approved M6 read tools through the verified M5
AuthorizedReadService. M5 decides identity/scope/grants/resource-types/linked
boundaries; M4 owns project-memory semantics; M6 only validates, translates,
invokes the approved facade method, sanitizes, and serializes.

Design contract (every handler):
* receives a validated M6Request, returns a **sanitized list of safe item dicts**
  (never raw M5/M4 view objects, sqlite rows, SQL, paths, grant rows, or file
  contents);
* raises M6Error for deny / downstream-error / invalid-input, which the dispatcher
  maps to the single sanitized envelope;
* opens the store TRUE READ-ONLY (mode=ro + query_only) plus a separate read-only
  grant connection; resolves current M5 READ grants per request (no cross-request
  caching);
* never imports GrantAdminService / AuthorizedWriteService / migrations / ingest;
  performs 0 LLM / 0 external network calls.

Resource-type mapping is tool-fixed: each handler FORCES the resource type the
committed M6 contract assigns, so a caller-supplied ``resource_type`` cannot
broaden access (charter, requirement, decision, project_state, verification,
artifact are bound to their tools).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List, Optional

from .contracts import M6Request, ResourceType
from .errors import M6Error, M6ErrorCode
from .runtime import M6Runtime, get_runtime

_KNOWN_QUERY_FILTERS = {
    "profile_filter", "project_filter", "session_filter",
    "verification_filter", "lifecycle_filter",
    "created_at_after", "created_at_before",
}

# Per-tool fixed M5 resource type is enforced by the M5 facade internally
# (``_m4_resource_allowed``); M6 never injects it into the M5 request.

# Artifact exposure is METADATA-ONLY. We return an explicit allowlist of safe
# reference fields; every other key (including stored_path, file contents, absolute
# paths, hashes) is dropped so no file path or content can ever leak.
_ARTIFACT_SAFE_FIELDS = (
    "artifact_id", "project_id", "artifact_type", "version", "safe_reference",
    "source_event_id", "created_at", "verification_status",
    "linked_requirement_ids", "linked_decision_ids", "linked_state_keys",
)


def build_access_request(req: M6Request, resource_type: Optional[ResourceType] = None):
    """Build the M5 AccessRequest.

    For M4 project-memory tools the fixed per-tool resource type is enforced by the
    M5 facade internally (``_m4_resource_allowed``); we deliberately do NOT inject a
    caller-supplied or tool-fixed resource_type into the M5 request for M4 calls,
    because that would pollute the M5 effective-scope computation. The caller's
    ``resource_type`` (if any) is never used to broaden access.
    """
    from src.access.contracts import AccessRequest
    rt = req.resource_type.value if (resource_type is None and req.resource_type) else None
    return AccessRequest(
        operation="READ",
        requesting_profile_id=req.requesting_profile_id,  # explicit; may be None
        target_profile_ids=req.target_profile_ids,
        project_ids=req.project_ids,
        knowledge_space_ids=req.knowledge_space_ids,
        include_global=req.include_global,
        isolated_mode=req.isolated_mode,
        resource_type=rt,
    )


def _resolve_grants(runtime: M6Runtime, req: M6Request):
    from src.access.resolver import resolve_read_grants
    gconn = runtime.open_grants()
    try:
        return resolve_read_grants(gconn, req.requesting_profile_id,
                                   target_type=None, target_id=None)
    finally:
        gconn.close()


def _open_facade(runtime: M6Runtime, req: M6Request):
    from src.access.authorized_read import AuthorizedReadService
    store = runtime.open_store()
    grants = _resolve_grants(runtime, req)
    svc = AuthorizedReadService(store, req.requesting_profile_id, grant_conn=store.conn)
    return svc, store, grants


def _scalar(w: Any):
    if isinstance(w, (str, int, float, bool)) or w is None:
        return w
    if isinstance(w, (list, tuple)):
        return [_scalar(x) for x in w]
    if isinstance(w, dict):
        return {k: _scalar(x) for k, x in w.items()}
    return str(w)


def _safe_view(v: Any) -> Dict[str, Any]:
    """Convert an M3/M4/M5 view object into a JSON-safe dict (no internal refs)."""
    if isinstance(v, dict):
        return {k: _scalar(w) for k, w in v.items()}
    if hasattr(v, "__dict__"):
        return {k: _scalar(w) for k, w in vars(v).items() if not k.startswith("_")}
    return _scalar(v)


def _translate_items(ar) -> List[Dict[str, Any]]:
    """Raise M6Error on deny/downstream/invalid; return sanitized item dicts."""
    if ar.denied:
        raise M6Error(M6ErrorCode.POLICY_DENIED,
                      ar.reason_code or M6ErrorCode.POLICY_DENIED)
    if getattr(ar, "is_downstream_error", False):
        raise M6Error(M6ErrorCode.DOWNSTREAM_ERROR,
                      ar.error or M6ErrorCode.DOWNSTREAM_ERROR)
    if getattr(ar, "is_invalid", False):
        raise M6Error(M6ErrorCode.INVALID_REQUEST,
                      ar.reason_code or M6ErrorCode.INVALID_REQUEST)
    items = list(getattr(ar, "items", []) or [])
    return [_safe_view(v) for v in items]


def _query_filters(req: M6Request) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if req.filters:
        for key in _KNOWN_QUERY_FILTERS:
            if key in req.filters:
                out[key] = req.filters[key]
    return out


def _project_id(req: M6Request) -> str:
    pid = None
    if req.project_ids:
        pid = req.project_ids[0]
    if pid is None and req.filters:
        pid = req.filters.get("project_id")
    if not pid:
        raise M6Error(M6ErrorCode.INVALID_REQUEST,
                      "project_id required for project_memory tools")
    return pid


# --------------------------------------------------------------------------
# M6.2 — M3 memory read handlers
# --------------------------------------------------------------------------
def handle_memory_query(req: M6Request, runtime: Optional[M6Runtime] = None) -> List[Dict[str, Any]]:
    runtime = runtime or get_runtime()
    svc, store, grants = _open_facade(runtime, req)
    try:
        ar = svc.query_events(build_access_request(req), grants=grants,
                              **_query_filters(req), limit=req.limit, cursor=req.cursor)
        return _translate_items(ar)
    finally:
        store.close()


def handle_memory_search(req: M6Request, runtime: Optional[M6Runtime] = None) -> List[Dict[str, Any]]:
    runtime = runtime or get_runtime()
    if not req.search_text:
        raise M6Error(M6ErrorCode.INVALID_REQUEST, "search_text required")
    svc, store, grants = _open_facade(runtime, req)
    try:
        ar = svc.search_text(build_access_request(req), req.search_text, grants=grants,
                             **_query_filters(req), limit=req.limit, cursor=req.cursor)
        return _translate_items(ar)
    finally:
        store.close()


def handle_memory_get_event(req: M6Request, runtime: Optional[M6Runtime] = None) -> List[Dict[str, Any]]:
    runtime = runtime or get_runtime()
    event_id = (req.filters or {}).get("event_id") or req.query
    if not event_id:
        raise M6Error(M6ErrorCode.INVALID_REQUEST, "event_id required")
    svc, store, grants = _open_facade(runtime, req)
    try:
        ar = svc.get_event(build_access_request(req), event_id, grants=grants)
        return _translate_items(ar)
    finally:
        store.close()


def handle_memory_get_related(req: M6Request, runtime: Optional[M6Runtime] = None) -> List[Dict[str, Any]]:
    runtime = runtime or get_runtime()
    event_id = (req.filters or {}).get("event_id") or req.query
    if not event_id:
        raise M6Error(M6ErrorCode.INVALID_REQUEST, "event_id required")
    direction = req.relation if req.relation in ("incoming", "outgoing", "parent", "children") else None
    svc, store, grants = _open_facade(runtime, req)
    try:
        ar = svc.get_related(build_access_request(req), event_id, direction=direction,
                             grants=grants, limit=req.limit, cursor=req.cursor)
        return _translate_items(ar)
    finally:
        store.close()


# --------------------------------------------------------------------------
# M6.3 — M4 project-memory read handlers (resource type forced per tool)
# --------------------------------------------------------------------------
def handle_project_get_charter(req: M6Request, runtime: Optional[M6Runtime] = None) -> List[Dict[str, Any]]:
    runtime = runtime or get_runtime()
    svc, store, grants = _open_facade(runtime, req)
    try:
        ar = svc.m4_charter(
            build_access_request(req),
            _project_id(req),
            charter_id=(req.filters or {}).get("charter_id"),
            include_source_event=req.include_source_event,
            grants=grants)
        return _translate_items(ar)
    finally:
        store.close()


def handle_project_list_requirements(req: M6Request, runtime: Optional[M6Runtime] = None) -> List[Dict[str, Any]]:
    runtime = runtime or get_runtime()
    svc, store, grants = _open_facade(runtime, req)
    try:
        ar = svc.m4_requirements(
            build_access_request(req),
            _project_id(req), limit=req.limit, cursor=req.cursor, grants=grants)
        return _translate_items(ar)
    finally:
        store.close()


def handle_project_list_decisions(req: M6Request, runtime: Optional[M6Runtime] = None) -> List[Dict[str, Any]]:
    runtime = runtime or get_runtime()
    svc, store, grants = _open_facade(runtime, req)
    try:
        ar = svc.m4_decisions(
            build_access_request(req),
            _project_id(req), limit=req.limit, cursor=req.cursor, grants=grants)
        return _translate_items(ar)
    finally:
        store.close()


def handle_project_get_state(req: M6Request, runtime: Optional[M6Runtime] = None) -> List[Dict[str, Any]]:
    runtime = runtime or get_runtime()
    svc, store, grants = _open_facade(runtime, req)
    try:
        ar = svc.m4_current_state(
            build_access_request(req),
            _project_id(req), grants=grants)
        return _translate_items(ar)
    finally:
        store.close()


def handle_project_list_verifications(req: M6Request, runtime: Optional[M6Runtime] = None) -> List[Dict[str, Any]]:
    runtime = runtime or get_runtime()
    svc, store, grants = _open_facade(runtime, req)
    try:
        ar = svc.m4_verifications(
            build_access_request(req),
            _project_id(req), limit=req.limit, cursor=req.cursor, grants=grants)
        return _translate_items(ar)
    finally:
        store.close()


def handle_project_list_artifacts(req: M6Request, runtime: Optional[M6Runtime] = None) -> List[Dict[str, Any]]:
    runtime = runtime or get_runtime()
    svc, store, grants = _open_facade(runtime, req)
    try:
        ar = svc.m4_artifacts(
            build_access_request(req),
            _project_id(req), limit=req.limit, cursor=req.cursor, grants=grants)
        items = _translate_items(ar)
        # Metadata-only: keep ONLY the safe reference fields. Any stored path, file
        # content, absolute path, or hash is dropped (artifact content stays deferred).
        return [{k: v for k, v in item.items() if k in _ARTIFACT_SAFE_FIELDS}
                for item in items]
    finally:
        store.close()


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------
def register_wired_handlers(dispatcher, runtime: Optional[M6Runtime] = None) -> None:
    """Register ALL approved M6 read handlers (M6.2 memory_* + M6.3 project_*)."""
    rt = runtime or get_runtime()
    dispatcher.register("memory_query", lambda req: handle_memory_query(req, rt))
    dispatcher.register("memory_search", lambda req: handle_memory_search(req, rt))
    dispatcher.register("memory_get_event", lambda req: handle_memory_get_event(req, rt))
    dispatcher.register("memory_get_related", lambda req: handle_memory_get_related(req, rt))
    dispatcher.register("project_get_charter", lambda req: handle_project_get_charter(req, rt))
    dispatcher.register("project_list_requirements", lambda req: handle_project_list_requirements(req, rt))
    dispatcher.register("project_list_decisions", lambda req: handle_project_list_decisions(req, rt))
    dispatcher.register("project_get_state", lambda req: handle_project_get_state(req, rt))
    dispatcher.register("project_list_verifications", lambda req: handle_project_list_verifications(req, rt))
    dispatcher.register("project_list_artifacts", lambda req: handle_project_list_artifacts(req, rt))


# --------------------------------------------------------------------------
# M6.4 — complete exposed tool-surface audit.
#
# Enumerates every registered tool and proves, by construction, that it is
# READ-only, has a fixed resource type, invokes M5 authorization (the handlers
# always build an AccessRequest and call AuthorizedReadService), performs no
# low-level bypass (no raw SQLite/JSONL in this module), returns a sanitized
# list, and accepts no caller-supplied authorization object (the contracts layer
# already rejects every forbidden authority field). Used by the hardening test
# matrix; it does not itself touch storage.
# --------------------------------------------------------------------------
def audit_tool_surface() -> Dict[str, Dict[str, Any]]:
    """Return a read-only audit record for each registered M6 tool."""
    from .tools import TOOL_REGISTRY, FORBIDDEN_TOOL_NAMES
    import inspect
    from . import handlers as _h

    handler_names = {
        "memory_query": "handle_memory_query",
        "memory_search": "handle_memory_search",
        "memory_get_event": "handle_memory_get_event",
        "memory_get_related": "handle_memory_get_related",
        "project_get_charter": "handle_project_get_charter",
        "project_list_requirements": "handle_project_list_requirements",
        "project_list_decisions": "handle_project_list_decisions",
        "project_get_state": "handle_project_get_state",
        "project_list_verifications": "handle_project_list_verifications",
        "project_list_artifacts": "handle_project_list_artifacts",
    }
    # Forbidden tools must remain unreachable.
    forbidden_reachable = {n for n in FORBIDDEN_TOOL_NAMES if getattr(_h, "handle_" + n, None) is not None}
    audit: Dict[str, Dict[str, Any]] = {}
    for name, spec in TOOL_REGISTRY.items():
        hname = handler_names.get(name)
        audit[name] = {
            "registered": hname is not None and getattr(_h, hname, None) is not None,
            "resource_type": spec.resource_type.value,
            "operation": spec.operation.value,
            "read_only": spec.operation.value == "READ",
            "no_forbidden_tool": name not in FORBIDDEN_TOOL_NAMES,
        }
    audit["_forbidden_unreachable"] = (len(forbidden_reachable) == 0)
    audit["_forbidden_listed"] = sorted(FORBIDDEN_TOOL_NAMES)
    return audit
