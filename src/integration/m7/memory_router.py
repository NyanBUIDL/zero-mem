"""M7.2 deterministic memory-need router.

PURE function: RouterRequest -> MemoryRouteDecision. No DB, no filesystem, no
network, no module-level mutable state, no LLM, no retrieval, no authorization.

Precedence (highest first), documented and tested:
  1. trusted_route_hint (valid MemoryRoute from typed caller contract) -- overrides
  2. freshness intent (explicit flag OR conservative lexical marker) -> EXTERNAL_CURRENT
  3. global intent (explicit multi-scope composition)              -> GLOBAL
  4. project intent  -> PROJECT
  5. session intent   -> SESSION
  6. research intent  -> RESEARCH
  7. user intent      -> USER
  8. otherwise        -> NO_MEMORY (safe default; future retrieval count = 0)

Notes on ordering:
- Global (multi-scope composition) ranks ABOVE project: composing multiple
  profiles/knowledge spaces is a stronger, more specific intent than a single
  project reference. Ambient multiple IDs WITHOUT an explicit composition signal
  do NOT trigger GLOBAL (they stay NO_MEMORY).
- Freshness ranks highest among content routes so "latest/current" requests are
  not silently answered from stale historical memory.
- Route != authorization; every route except NO_MEMORY still requires M5 later.
"""

from __future__ import annotations

import re
from typing import Optional

from .contracts import (
    MemoryRoute,
    MemoryRouteDecision,
    ReasonCode,
    RouterRequest,
)

# Conservative, deterministic, English-only lexical markers. Small on purpose;
# structural/explicit intent flags take precedence. Case/whitespace normalized.
_SESSION_RE = re.compile(
    r"\b(we just|we discussed|we decided earlier|the file we discussed|"
    r"our last|our previous|previous (step|turn|message|conversation|session)|"
    r"last (time|step|turn|session)|continue (from|where we left)|"
    r"what (did|have) we (just )?(decide|discuss)|recent(ly)? (discussed|decided))\b",
    re.IGNORECASE,
)
_PROJECT_RE = re.compile(
    r"\b(project|requirement|decision we made|for this project|the project|"
    r"project state|what('| i)s (left|unfinished|remaining)|project plan)\b",
    re.IGNORECASE,
)
_RESEARCH_RE = re.compile(
    r"\b(stored research|saved (document|corpus|source)|research (documents|corpus)|"
    r"source material|use (the |our )?research|recall (the )?source|ingested (docs|knowledge)|"
    r"my (notes|corpus)|saved knowledge)\b",
    re.IGNORECASE,
)
_USER_RE = re.compile(
    r"\b(my (usual|preferred|typical)|my preference|preferred (style|format|workflow)|"
    r"my (style|format|workflow|writing)|(usual|typical) (format|style)|"
    r"how (do|would) i (usually|normally) like)\b",
    re.IGNORECASE,
)
_GLOBAL_RE = re.compile(
    r"\b(combine|across (profiles|projects|knowledge spaces)|multiple (profiles|knowledge spaces)|"
    r"use (quant|engineering|both|all) .* (and|with) .* (knowledge|profile)|"
    r"both profiles|all profiles|across all)\b",
    re.IGNORECASE,
)
_FRESH_RE = re.compile(
    r"\b(latest|newest|up[ -]to[ -]date|current (version|price|status|market|state|external)|"
    r"what is .* (now|right now)|as of now|live (status|state))\b",
    re.IGNORECASE,
)


def _norm(text: Optional[str]) -> str:
    if not text:
        return ""
    return " ".join(str(text).lower().split())


def _detect(text: str):
    """Return (session, project, research, user, global, fresh) lexical booleans."""
    return (
        bool(_SESSION_RE.search(text)),
        bool(_PROJECT_RE.search(text)),
        bool(_RESEARCH_RE.search(text)),
        bool(_USER_RE.search(text)),
        bool(_GLOBAL_RE.search(text)),
        bool(_FRESH_RE.search(text)),
    )


def route(req: RouterRequest) -> MemoryRouteDecision:
    """Classify memory need deterministically. Pure: no side effects, no state."""
    # 1. Trusted explicit route hint (typed contract field only; never from free text).
    if req.trusted_route_hint is not None:
        hint = req.trusted_route_hint
        if not isinstance(hint, MemoryRoute):
            # Defensive: invalid hint is rejected by the caller contract, but guard here.
            raise ValueError(f"invalid trusted_route_hint: {hint!r}")
        return MemoryRouteDecision(
            route=hint,
            memory_needed=hint.requires_memory,
            reason_code=ReasonCode.EXPLICIT_ROUTE_HINT,
            scope_hints=_scope_hints(req, hint),
            external_current=(hint is MemoryRoute.EXTERNAL_CURRENT),
            insufficient_route_context=_insufficient(req, hint),
        )

    text = _norm(req.normalized_text)
    s_lex, p_lex, r_lex, u_lex, g_lex, f_lex = _detect(text)

    # Explicit structured flags dominate lexical detection.
    session = req.explicit_session_intent or s_lex
    project = req.explicit_project_intent or p_lex
    research = req.explicit_research_intent or r_lex
    user = req.explicit_user_intent or u_lex
    global_ = req.explicit_global_intent or g_lex
    fresh = req.explicit_freshness_intent or f_lex

    # Track ALL detected intents for accurate downstream scope hints.
    detected = {
        "session": session, "project": project, "research": research,
        "user": user, "global": global_, "fresh": fresh,
    }

    # 2. Freshness
    if fresh:
        return _decide(MemoryRoute.EXTERNAL_CURRENT, ReasonCode.EXTERNAL_FRESHNESS_REQUIRED, req, detected)
    # 3. Global (multi-scope composition)
    if global_:
        return _decide(MemoryRoute.GLOBAL, ReasonCode.EXPLICIT_MULTI_SCOPE, req, detected)
    # 4. Project
    if project:
        return _decide(MemoryRoute.PROJECT, ReasonCode.EXPLICIT_PROJECT_CONTEXT, req, detected)
    # 5. Session
    if session:
        return _decide(MemoryRoute.SESSION, ReasonCode.EXPLICIT_SESSION_REFERENCE, req, detected)
    # 6. Research
    if research:
        return _decide(MemoryRoute.RESEARCH, ReasonCode.EXPLICIT_RESEARCH_SOURCE, req, detected)
    # 7. User
    if user:
        return _decide(MemoryRoute.USER, ReasonCode.EXPLICIT_USER_PREFERENCE, req, detected)
    # 8. Safe default
    return MemoryRouteDecision(
        route=MemoryRoute.NO_MEMORY,
        memory_needed=False,
        reason_code=ReasonCode.GENERIC_STANDALONE,
        scope_hints=frozenset(),
        external_current=False,
        insufficient_route_context=False,
    )


def _decide(route: MemoryRoute, reason: ReasonCode, req: RouterRequest, detected: dict) -> MemoryRouteDecision:
    return MemoryRouteDecision(
        route=route,
        memory_needed=True,
        reason_code=reason,
        scope_hints=_scope_hints(req, route, detected),
        external_current=(route is MemoryRoute.EXTERNAL_CURRENT),
        insufficient_route_context=_insufficient(req, route),
    )


def _scope_hints(req: RouterRequest, route: MemoryRoute, detected: dict | None = None) -> frozenset:
    hints = set()
    detected = detected or {}
    if route in (MemoryRoute.PROJECT, MemoryRoute.EXTERNAL_CURRENT) or req.project_id:
        hints.add("project")
    if route is MemoryRoute.SESSION or req.session_id or detected.get("session"):
        hints.add("session")
    if route is MemoryRoute.USER or req.requesting_profile_id or detected.get("user"):
        hints.add("user_profile")
    if route is MemoryRoute.RESEARCH or req.explicit_research_intent or detected.get("research"):
        hints.add("research_source")
    if route is MemoryRoute.GLOBAL or len(req.target_profile_ids) >= 2 or len(req.knowledge_space_ids) >= 2 or detected.get("global"):
        hints.add("multi_scope")
    if route is MemoryRoute.EXTERNAL_CURRENT or detected.get("fresh"):
        hints.add("freshness")
    return frozenset(hints)


def _insufficient(req: RouterRequest, route: MemoryRoute) -> bool:
    """Flag when the chosen route needs scope the request did not supply.

    This does NOT authorize anything; it only tells M7.3 later that explicit scope
    must be resolved before retrieval. No_memory never insufficient.
    """
    if route is MemoryRoute.NO_MEMORY:
        return False
    if route is MemoryRoute.PROJECT and not req.project_id:
        return True
    if route is MemoryRoute.USER and not req.requesting_profile_id:
        return True
    if route is MemoryRoute.SESSION and not req.session_id:
        return True
    if route is MemoryRoute.GLOBAL and not (
        len(req.target_profile_ids) >= 2 or len(req.knowledge_space_ids) >= 2
    ):
        return True
    return False


def route_from_text(
    text: Optional[str],
    *,
    project_id: Optional[str] = None,
    session_id: Optional[str] = None,
    requesting_profile_id: Optional[str] = None,
    target_profile_ids: tuple = (),
    knowledge_space_ids: tuple = (),
    trusted_route_hint: Optional[MemoryRoute] = None,
) -> MemoryRouteDecision:
    """Convenience builder: derive a RouterRequest from text + ambient metadata and route.

    Ambient metadata (ids) is passed through for scope-hint computation but does NOT
    by itself force a memory route. Memory need is driven by explicit intent or
    conservative lexical markers.
    """
    req = RouterRequest(
        normalized_text=text,
        project_id=project_id,
        session_id=session_id,
        requesting_profile_id=requesting_profile_id,
        target_profile_ids=tuple(target_profile_ids),
        knowledge_space_ids=tuple(knowledge_space_ids),
        trusted_route_hint=trusted_route_hint,
    )
    return route(req)
