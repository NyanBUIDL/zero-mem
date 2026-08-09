"""M7.4 — Hermes controlled context-injection adapter.

Registers a ``pre_llm_call`` hook on the REAL Hermes plugin-context
``register_hook`` surface. When the hook fires (before model generation), it:

1. Checks the M7.1 master gate (ZERO_MEM_ENABLED). OFF -> no injection.
2. Routes the user message through the M7.2 deterministic router.
3. If memory is needed, builds an M7.3 authorized EvidenceSet.
4. M7.5 hardening: validates EvidenceSet invariants (fail closed) and
   sanitizes (escapes) all evidence fields.
5. Serializes the sanitized EvidenceSet into a safe DATA-only envelope.
6. Returns ``{"context": envelope_text}`` — injected into the user message
   API copy only (never system prompt, never the stored transcript).

The adapter performs NO new retrieval, NO authorization, NO reranking,
NO lifecycle changes, NO grant admin, NO writes, NO LLM calls, NO network.

Identity (requesting_profile_id) comes ONLY from the explicit adapter
configuration — never inferred from session_id, cwd, path, or the
pre_llm_call payload. The ``sender_id`` field from the hook payload is
NOT treated as authoritative identity (it may be a platform user, not the
agent's requesting profile).

Request-local state: the adapter holds NO mutable global last-EvidenceSet,
last-route, or last-profile. Each hook invocation is independent.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from .contracts import (
    MemoryRoute, MemoryRouteDecision, RouterRequest, EvidenceSet,
    zero_mem_runtime_enabled,
)
from .memory_router import route
from .evidence_builder import build_evidence_set
from .envelope import serialize_evidence_set
from .hardening import validate_evidence_set, sanitize_evidence_set
from ..zero_mem_runtime import get_runtime


@dataclass(frozen=True)
class InjectionResult:
    """Result of one pre_llm_call invocation. For testing/observability."""
    injected: bool
    context: str
    route: Optional[str] = None
    reason: str = ""


class InjectionAdapter:
    """Registers the pre_llm_call hook and runs the M7 pipeline on fire.

    Construct with explicit identity and optional M5 AuthorizedReadService
    factory. The adapter is request-local: no mutable global state.
    """

    def __init__(
        self,
        *,
        requesting_profile_id: Optional[str] = None,
        target_profile_ids: tuple[str, ...] = (),
        project_id: Optional[str] = None,
        session_id: Optional[str] = None,
        knowledge_space_ids: tuple[str, ...] = (),
        store_path: Optional[str | Path] = None,
        grants: Optional[list] = None,
        sensitivity_ceiling: str = "high",
    ) -> None:
        # Explicit identity only — never inferred from hook payload.
        self._requesting_profile_id = requesting_profile_id
        self._target_profile_ids = tuple(target_profile_ids)
        self._project_id = project_id
        self._session_id = session_id
        self._knowledge_space_ids = tuple(knowledge_space_ids)
        self._store_path = Path(store_path) if store_path is not None else None
        self._grants = grants
        self._sensitivity_ceiling = sensitivity_ceiling
        self._registered: bool = False

    # ------------------------------------------------------------------
    # Plugin registration (real Hermes PluginContext.register_hook)
    # ------------------------------------------------------------------
    def register(self, context: Any) -> tuple[str, ...]:
        """Register the pre_llm_call hook. Idempotent.

        Accepts any context object exposing ``register_hook(name, callback)``
        — the real Hermes PluginContext or a compatible test double.
        """
        if self._registered:
            return ("pre_llm_call",)
        if not hasattr(context, "register_hook") or not callable(context.register_hook):
            return ()
        context.register_hook("pre_llm_call", self._on_pre_llm_call)
        self._registered = True
        return ("pre_llm_call",)

    # ------------------------------------------------------------------
    # Hook callback (the real pre_llm_call entry point)
    # ------------------------------------------------------------------
    def _on_pre_llm_call(self, **kwargs: Any) -> Optional[dict[str, str]]:
        """Real pre_llm_call callback. Returns {"context": ...} or None.

        This is called by Hermes before model generation. The kwargs include:
        session_id, task_id, turn_id, user_message, conversation_history,
        is_first_turn, model, platform, parent_session_id, sender_id.

        We use ONLY the user_message for routing (M7.2). Identity comes
        from the adapter's explicit configuration, NOT from the payload.
        """
        try:
            result = self.process(
                user_message=kwargs.get("user_message", ""),
                session_id=kwargs.get("session_id"),
            )
            if result.injected and result.context:
                return {"context": result.context}
            return None
        except Exception:
            # Bounded failure isolation: never break Hermes.
            return None

    # ------------------------------------------------------------------
    # Core pipeline (testable without Hermes)
    # ------------------------------------------------------------------
    def process(
        self,
        *,
        user_message: str,
        session_id: Optional[str] = None,
    ) -> InjectionResult:
        """Run the M7.1→M7.2→M7.3 pipeline and serialize the envelope.

        This is the testable core. It does NOT touch Hermes internals.
        Returns an InjectionResult describing what happened.
        """
        # 1. M7.1 master gate
        if not get_runtime().is_enabled():
            return InjectionResult(injected=False, context="", reason="master_off")

        # 2. M7.2 deterministic router
        router_request = RouterRequest(
            normalized_text=user_message,
            project_id=self._project_id,
            session_id=session_id or self._session_id,
            requesting_profile_id=self._requesting_profile_id,
            target_profile_ids=self._target_profile_ids,
            knowledge_space_ids=self._knowledge_space_ids,
        )
        decision = route(router_request)

        # 3. no_memory -> zero retrieval, zero injection
        if not decision.requires_memory():
            return InjectionResult(
                injected=False, context="", route=decision.route.value,
                reason="no_memory",
            )

        # 4. external_current -> insufficient, no injection of stale data
        if decision.route is MemoryRoute.EXTERNAL_CURRENT:
            es = EvidenceSet(
                route=decision.route, memory_needed=True,
                insufficient_evidence=True, external_current_required=True,
                reason_code="EXTERNAL_CURRENT_REQUIRED",
            )
            envelope = serialize_evidence_set(es)
            return InjectionResult(
                injected=True, context=envelope,
                route=decision.route.value, reason="external_current",
            )

        # 5. M7.3 authorized EvidenceSet construction
        svc = self._make_service()
        if svc is None:
            # No store configured -> insufficient, no injection
            es = EvidenceSet(
                route=decision.route, memory_needed=True,
                insufficient_evidence=True,
                reason_code="NO_STORE",
            )
            envelope = serialize_evidence_set(es)
            return InjectionResult(
                injected=False, context="", route=decision.route.value,
                reason="no_store",
            )

        es = build_evidence_set(
            decision, svc, router_request,
            grants=self._grants,
            sensitivity_ceiling=self._sensitivity_ceiling,
        )

        # 5a. M7.5 hardening: validate EvidenceSet invariants (fail closed)
        validation = validate_evidence_set(es)
        if not validation:
            # Malformed/tampered EvidenceSet -> fail closed, no injection
            return InjectionResult(
                injected=False, context="", route=decision.route.value,
                reason=f"validation_failed:{validation.reason}",
            )

        # 5b. M7.5 hardening: sanitize (escape) all evidence fields
        es = sanitize_evidence_set(es)

        # 6. Serialize
        envelope = serialize_evidence_set(es)
        if not envelope:
            return InjectionResult(
                injected=False, context="", route=decision.route.value,
                reason="empty_evidence_set",
            )
        return InjectionResult(
            injected=True, context=envelope,
            route=decision.route.value, reason="evidence_ready",
        )

    # ------------------------------------------------------------------
    # M5 service factory
    # ------------------------------------------------------------------
    def _make_service(self) -> Any:
        """Build an M5 AuthorizedReadService from the configured store path.

        Returns None when no store is configured. The service is request-local:
        a fresh instance per hook fire, no shared mutable state.
        """
        if self._store_path is None:
            return None
        try:
            from src.retrieval.db import open_readonly
            from src.access import AuthorizedReadService
            ro = open_readonly(self._store_path)
            return AuthorizedReadService(ro, requesting_profile_id=self._requesting_profile_id)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Observability (content-safe)
    # ------------------------------------------------------------------
    def diagnostics(self) -> dict[str, Any]:
        """Content-safe diagnostic metadata. No raw evidence, no secrets."""
        return {
            "registered": self._registered,
            "has_store": self._store_path is not None,
            "has_profile": self._requesting_profile_id is not None,
            "master_switch": get_runtime().is_enabled(),
        }


__all__ = ["InjectionAdapter", "InjectionResult"]
