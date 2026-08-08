"""M6.1 — sanitized error mapping.

Maps internal contract/transport errors to the stable response envelope.
Never exposes tracebacks, SQL, SQLite internals, paths, secrets, or grant rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .contracts import M6Response, ResponseStatus


class M6ErrorCode(str):
    """Safe, stable error codes (no internal detail)."""

    INVALID_REQUEST = "INVALID_REQUEST"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    UNSUPPORTED_TOOL = "UNSUPPORTED_TOOL"
    INVALID_CURSOR = "INVALID_CURSOR"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    DOWNSTREAM_ERROR = "DOWNSTREAM_ERROR"
    POLICY_DENIED = "POLICY_DENIED"


@dataclass(frozen=True)
class M6Error(Exception):
    code: str
    safe_message: str
    reason_code: Optional[str] = None

    def to_response(self, *, diagnostics: Optional[Dict[str, Any]] = None) -> M6Response:
        status = {
            M6ErrorCode.INVALID_REQUEST: ResponseStatus.INVALID_REQUEST,
            M6ErrorCode.UNSUPPORTED_OPERATION: ResponseStatus.UNSUPPORTED_OPERATION,
            M6ErrorCode.UNSUPPORTED_TOOL: ResponseStatus.UNSUPPORTED_TOOL,
            M6ErrorCode.INVALID_CURSOR: ResponseStatus.INVALID_REQUEST,
            M6ErrorCode.CAPABILITY_UNAVAILABLE: ResponseStatus.CAPABILITY_UNAVAILABLE,
            M6ErrorCode.DOWNSTREAM_ERROR: ResponseStatus.DOWNSTREAM_ERROR,
            M6ErrorCode.POLICY_DENIED: ResponseStatus.POLICY_DENIED,
        }.get(self.code, ResponseStatus.INVALID_REQUEST)
        return M6Response(
            status=status,
            reason_code=self.reason_code or self.code,
            diagnostics=diagnostics or {},
        )
