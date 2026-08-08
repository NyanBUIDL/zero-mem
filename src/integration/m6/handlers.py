"""M6.2 — M3 authorized memory read tool handlers.

Wires the approved M3-oriented M6 tools (memory_query, memory_search,
memory_get_event, memory_get_related) through the verified M5 AuthorizedReadService.

Design contract:
* A handler receives a validated M6Request and returns a **sanitized list of safe
  item dicts** (never raw M5/M3 view objects, sqlite rows, SQL, paths, or grant
  rows). Denials / downstream errors are signalled by raising M6Error, which the
  dispatcher maps to the sanitized envelope.
* The dispatcher (M6.1) owns envelope construction; handlers never return an
  M6Response.

This module is transport/integration only. It builds an M5 AccessRequest from the
validated M6 request (explicit identity), resolves current M5 READ grants
(read-only), invokes the M5 facade (which enforces policy + M5.5 linked
boundaries), and sanitizes the view objects. It performs 0 LLM/network calls and
never opens raw SQLite for queries, never reads JSONL, never touches
GrantAdminService/AuthorizedWriteService.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .contracts import M6Request
from .errors import M6Error, M6ErrorCode
from .runtime import M6Runtime, get_runtime

_KNOWN_QUERY_FILTERS = {
    "profile_filter", "project_filter", "session_filter",
    "verification_filter", "lifecycle_filter",
    "created_at_after", "created_at_before",
}


def build_access_request(req: M6Request):
    from src.access.contracts import AccessRequest
    return AccessRequest(
        operation="READ",
        requesting_profile_id=req.requesting_profile_id,  # explicit; may be None
        target_profile_ids=req.target_profile_ids,
        project_ids=req.project_ids,
        knowledge_space_ids=req.knowledge_space_ids,
        include_global=req.include_global,
        isolated_mode=req.isolated_mode,
        resource_type=req.resource_type.value if req.resource_type else None,
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
    """Convert an M3/M5 view object into a JSON-safe dict (no internal refs)."""
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
    event_id = (req.filters or {}).get("event_id") or req.query or req.resource_id
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
    event_id = (req.filters or {}).get("event_id") or req.query or req.resource_id
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


def register_m3_handlers(dispatcher, runtime: Optional[M6Runtime] = None) -> None:
    """Register the approved M3-oriented handlers on a Dispatcher."""
    rt = runtime or get_runtime()
    dispatcher.register("memory_query", lambda req: handle_memory_query(req, rt))
    dispatcher.register("memory_search", lambda req: handle_memory_search(req, rt))
    dispatcher.register("memory_get_event", lambda req: handle_memory_get_event(req, rt))
    dispatcher.register("memory_get_related", lambda req: handle_memory_get_related(req, rt))
