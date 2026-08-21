"""Public read adapter: mapping-only transport boundary over AuthorizedReadService."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from src.access.authorized_read import AuthorizedReadService
from src.access.contracts import AccessRequest, READ


@dataclass(frozen=True)
class ReadResult:
    status: str
    reason_code: str
    items: tuple[Any, ...] = ()
    provenance: tuple[Mapping[str, Any], ...] = ()
    freshness: Mapping[str, Any] | None = None
    denied: bool = False
    error: str | None = None


class AuthorizedPublicReadAdapter:
    """One public-read protocol implementation; no direct SQL or transport code."""

    def __init__(self, service: AuthorizedReadService, *, requesting_profile_id: str | None,
                 freshness_provider: Any = None, wait_provider: Any = None) -> None:
        if not isinstance(service, AuthorizedReadService):
            raise TypeError("service must be AuthorizedReadService")
        self._service = service
        self._requester = requesting_profile_id
        self._freshness_provider = freshness_provider
        self._wait_provider = wait_provider

    def _request(self, raw: Mapping[str, Any] | None) -> AccessRequest:
        if raw is not None and not isinstance(raw, Mapping):
            raise ValueError("request must be a mapping")
        raw = raw or {}
        def ids(name: str) -> list[str] | None:
            value = raw.get(name)
            if value is None:
                return None
            if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
                raise ValueError(f"invalid {name}")
            return list(value)
        include_global = raw.get("include_global")
        if include_global is not None and not isinstance(include_global, bool):
            raise ValueError("invalid include_global")
        isolated_mode = raw.get("isolated_mode", False)
        if not isinstance(isolated_mode, bool):
            raise ValueError("invalid isolated_mode")
        return AccessRequest(
            operation=READ,
            requesting_profile_id=self._requester,
            target_profile_ids=ids("target_profile_ids"),
            project_ids=ids("project_ids"),
            knowledge_space_ids=ids("knowledge_space_ids"),
            include_global=include_global,
            isolated_mode=isolated_mode,
            resource_type=raw.get("resource_type"),
            resource_id=raw.get("resource_id"),
        ).validate()

    def _freshness(self, request: Mapping[str, Any] | None) -> tuple[bool, Mapping[str, Any] | None]:
        info = self._freshness_provider() if callable(self._freshness_provider) else None
        consistency = (request or {}).get("consistency", "allow_stale")
        if consistency not in {"require_current", "bounded_wait", "allow_stale"}:
            return False, {"status": "INVALID", "reason_code": "INVALID_CONSISTENCY"}
        if consistency == "bounded_wait" and info and info.get("status") != "DERIVED_CURRENT":
            timeout = (request or {}).get("deadline", 5.0)
            if (
                not isinstance(timeout, (int, float))
                or isinstance(timeout, bool)
                or not math.isfinite(float(timeout))
                or timeout < 0
            ):
                return False, {"status": "INVALID", "reason_code": "INVALID_DEADLINE"}
            if callable(self._wait_provider):
                try:
                    self._wait_provider(float(timeout))
                except Exception:
                    return False, info
                info = self._freshness_provider() if callable(self._freshness_provider) else info
            if info and info.get("status") != "DERIVED_CURRENT":
                return False, info
        if consistency == "require_current" and info and info.get("status") != "DERIVED_CURRENT":
            return False, info
        return True, info

    def _convert(self, result: Any, freshness: Mapping[str, Any] | None) -> ReadResult:
        if getattr(result, "denied", False):
            return ReadResult("DENIED", str(getattr(result, "reason_code", "READ_DENIED")), denied=True)
        if getattr(result, "error", None):
            return ReadResult("UNAVAILABLE", "READ_UNAVAILABLE", error="READ_UNAVAILABLE", freshness=freshness)
        items = tuple(getattr(result, "items", ()) or ())
        provenance = tuple({"source": "authorized_read", "item_index": i} for i, _ in enumerate(items))
        status = "READY" if items else "EMPTY"
        reason = "READ_OK" if items else "READ_EMPTY"
        return ReadResult(status, reason, items, provenance, freshness)

    def _run(self, request: Mapping[str, Any] | None, operation: Any) -> ReadResult:
        try:
            validated = self._request(request)
            decision = self._service.authorize(validated)
        except ValueError:
            return ReadResult("INVALID", "INVALID_REQUEST")
        except Exception:
            return ReadResult("UNAVAILABLE", "READ_UNAVAILABLE", error="READ_UNAVAILABLE")
        if not getattr(decision, "allow", False):
            return ReadResult("DENIED", str(getattr(decision, "reason_code", "READ_DENIED")), denied=True)
        allowed, freshness = self._freshness(request)
        if not allowed:
            reason = str((freshness or {}).get("reason_code", "REQUIRE_CURRENT_NOT_SATISFIED"))
            return ReadResult("STALE", reason, freshness=freshness)
        try:
            return self._convert(operation(validated), freshness)
        except ValueError:
            return ReadResult("INVALID", "INVALID_REQUEST")
        except TimeoutError:
            return ReadResult("TIMEOUT", "READ_TIMEOUT", freshness=freshness)
        except Exception:
            return ReadResult("UNAVAILABLE", "READ_UNAVAILABLE", error="READ_UNAVAILABLE", freshness=freshness)

    def search(self, request: Mapping[str, Any] | None = None) -> ReadResult:
        if request is not None and not isinstance(request, Mapping):
            return ReadResult("INVALID", "INVALID_REQUEST")
        text = str((request or {}).get("text", ""))
        return self._run(request, lambda req: self._service.search_text(req, text))

    def get_trace(self, request: Mapping[str, Any] | None = None) -> ReadResult:
        if request is not None and not isinstance(request, Mapping):
            return ReadResult("INVALID", "INVALID_REQUEST")
        trace_id = (request or {}).get("trace_id")
        if not isinstance(trace_id, str) or not trace_id:
            return ReadResult("INVALID", "INVALID_REQUEST")
        return self._run(request, lambda req: self._service.get_trace(req, trace_id))

    def get_task_state(self, request: Mapping[str, Any] | None = None) -> ReadResult:
        if request is not None and not isinstance(request, Mapping):
            return ReadResult("INVALID", "INVALID_REQUEST")
        project_id = (request or {}).get("project_id")
        if not isinstance(project_id, str) or not project_id:
            return ReadResult("INVALID", "INVALID_REQUEST")
        scoped = dict(request or {})
        scoped["project_ids"] = [project_id]
        if self._requester is not None:
            scoped["target_profile_ids"] = [self._requester]
        return self._run(scoped, lambda req: self._service.m4_current_state(req, project_id))

    def get_decisions(self, request: Mapping[str, Any] | None = None) -> ReadResult:
        if request is not None and not isinstance(request, Mapping):
            return ReadResult("INVALID", "INVALID_REQUEST")
        project_id = (request or {}).get("project_id")
        if not isinstance(project_id, str) or not project_id:
            return ReadResult("INVALID", "INVALID_REQUEST")
        scoped = dict(request or {})
        scoped["project_ids"] = [project_id]
        if self._requester is not None:
            scoped["target_profile_ids"] = [self._requester]
        return self._run(scoped, lambda req: self._service.m4_decisions(req, project_id))

    def close(self) -> None:
        """Release the owned strict read-only service connection."""
        close = getattr(self._service, "close", None)
        if callable(close):
            close()


__all__ = ["AuthorizedPublicReadAdapter", "ReadResult"]
