"""M6.1 — transport-independent dispatcher contract.

The dispatcher validates, resolves the tool from the allowlist, enforces the
fixed resource type, and invokes a registered READ handler. M6.1 ships NO real
handlers (M3/M4 wiring is M6.2/M6.3); when no handler is registered for a valid
tool it returns a deterministic CAPABILITY_UNAVAILABLE envelope. This proves the
surface is READ-ONLY by construction: the dispatcher never imports or invokes any
SQLite/JSONL/projector/migration/grant/WRITE path.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .contracts import (
    M6Request,
    M6Response,
    Operation,
    ResponseStatus,
    ResourceType,
    validate_request,
)
from .errors import M6ErrorCode, M6Error
from .tools import get_tool, is_forbidden_tool

# A READ handler: takes the validated request and returns raw result rows/models.
# It is provided by later increments (M6.2/M6.3). It MUST be read-only.
Handler = Callable[[M6Request], List[Any]]


class Dispatcher:
    def __init__(self) -> None:
        self._handlers: Dict[str, Handler] = {}

    def register(self, tool: str, handler: Handler) -> None:
        """Register a READ-only handler for an allowlisted tool."""
        spec = get_tool(tool)
        if spec is None:
            if is_forbidden_tool(tool):
                raise M6Error(M6ErrorCode.UNSUPPORTED_TOOL, "forbidden tool name")
            raise M6Error(M6ErrorCode.UNSUPPORTED_TOOL, f"unknown tool '{tool}'")
        self._handlers[tool] = handler

    def dispatch_raw(self, raw: Dict[str, Any]) -> M6Response:
        # 1) Strict validation (rejects unknown fields, forbidden authority
        #    fields, non-READ operation, bad enums/limits).
        try:
            req = validate_request(raw)
        except M6Error as e:
            return e.to_response()
        except Exception:  # ContractError or any unexpected -> sanitized
            return M6Response(
                status=ResponseStatus.INVALID_REQUEST,
                reason_code=M6ErrorCode.INVALID_REQUEST,
                diagnostics={"bounded": True},
            )

        # 2) Tool allowlist enforcement.
        spec = get_tool(req.tool)
        if spec is None:
            code = M6ErrorCode.UNSUPPORTED_TOOL
            return M6Response(
                status=ResponseStatus.UNSUPPORTED_TOOL,
                reason_code=code,
                diagnostics={"tool": req.tool},
            )

        # 3) Fixed resource type: caller cannot downgrade/override.
        if req.resource_type is not None and req.resource_type != spec.resource_type:
            return M6Response(
                status=ResponseStatus.INVALID_REQUEST,
                reason_code=M6ErrorCode.INVALID_REQUEST,
                diagnostics={"tool_resource_type": spec.resource_type.value},
            )

        # 4) Operation is always READ on this surface.
        if req.operation is not Operation.READ:
            return M6Response(
                status=ResponseStatus.UNSUPPORTED_OPERATION,
                reason_code=M6ErrorCode.UNSUPPORTED_OPERATION,
                diagnostics={"operation": req.operation.value},
            )

        # 5) Invoke READ handler if registered (M6.2/M6.3). Otherwise the tool
        #    contract is valid but execution is not yet wired.
        handler = self._handlers.get(req.tool)
        if handler is None:
            return M6Response(
                status=ResponseStatus.CAPABILITY_UNAVAILABLE,
                reason_code=M6ErrorCode.CAPABILITY_UNAVAILABLE,
                diagnostics={"tool": req.tool, "wired": False},
            )

        try:
            results = handler(req)
        except M6Error as e:
            return e.to_response()
        except Exception:  # downstream: never leak internals
            return M6Response(
                status=ResponseStatus.DOWNSTREAM_ERROR,
                reason_code=M6ErrorCode.DOWNSTREAM_ERROR,
                diagnostics={"bounded": True},
            )

        if not results:
            return M6Response(
                status=ResponseStatus.EMPTY,
                reason_code="EMPTY_RESULT",
                diagnostics={"tool": req.tool},
            )
        return M6Response(
            status=ResponseStatus.SUCCESS,
            results=results,
            diagnostics={"tool": req.tool},
        )


# Module-level default dispatcher (stateless; no per-client auth cache).
_default_dispatcher = Dispatcher()


def dispatch(raw: Dict[str, Any], *, dispatcher: Optional[Dispatcher] = None) -> M6Response:
    return (dispatcher or _default_dispatcher).dispatch_raw(raw)


def register(tool: str, handler: Handler) -> None:
    _default_dispatcher.register(tool, handler)
