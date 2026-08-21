"""Supported local public composition for generic Zero-Mem consumers."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from src.storage.capture_boundary import AppendResult
from src.integration.capture_adapter import adapt_mapped_event
from src.integration.payload_mapping import map_hook_payload
from src.integration.zero_mem_runtime import RuntimeConfig, ZeroMemRuntime

from .api import PublicClient
from .core import AppendReceipt, CoreConfig


class _RuntimeWriter:
    """Adapter owned by the public composition; callers never construct it."""

    def __init__(self, runtime: ZeroMemRuntime, *, project_id: str | None, profile_id: str | None) -> None:
        self._runtime = runtime
        self._project_id = project_id
        self._profile_id = profile_id
        self.path = runtime.writer_path

    def append(self, event: object) -> AppendReceipt:
        if not isinstance(event, Mapping):
            raise ValueError("observation_event_invalid")
        kind = event.get("kind")
        payload = event.get("payload")
        hooks = {
            "user_message": "public_user_message",
            "assistant_message": "public_assistant_message",
            "tool_call": "public_tool_call",
        }
        hook = hooks.get(kind)
        if hook is None:
            raise ValueError("observation_kind_invalid")
        if not isinstance(payload, Mapping):
            raise ValueError("observation_payload_invalid")
        mapped = map_hook_payload(
            hook,
            payload,
            project_id=self._project_id,
            profile_id=self._profile_id,
        )
        result = adapt_mapped_event(mapped, store=self._runtime.writer)
        if result.code not in {"appended", "duplicate_event_id", "duplicate_content_hash"}:
            raise ValueError(result.code)
        append = AppendResult(
            "duplicate" if result.code != "appended" else "appended",
            result.event_id or "public:unknown",
            result.sequence if result.sequence is not None else 0,
            "public-runtime",
            result.duplicate_class,
        )
        self._runtime.notify_append(append)
        return AppendReceipt(
            append.status,
            append.event_id,
            append.sequence,
            True,
            append.duplicate_class,
            "CANONICAL_DUPLICATE" if append.status == "duplicate" else None,
        )

    def sync(self) -> None:
        self._runtime.flush_projection(timeout=5.0)

    def close(self) -> None:
        self._runtime.close(timeout=5.0)


def open_local_client(
    capture_root: Path,
    *,
    project_id: str | None,
    profile_id: str | None,
    enabled: bool = True,
) -> PublicClient:
    """Open one complete local runtime through the stable ``zero_mem`` boundary.

    The runtime owns the canonical JSONL writer, derived SQLite projection and
    authorized read service. Callers provide only an explicit root and identity.
    """
    runtime = ZeroMemRuntime.open(
        RuntimeConfig(capture_root=Path(capture_root), enabled=enabled)
    )
    if not enabled:
        return PublicClient.open(CoreConfig(enabled=False, project_id=project_id, profile_id=profile_id))
    writer = _RuntimeWriter(runtime, project_id=project_id, profile_id=profile_id)
    try:
        read_service = runtime.open_read_service(requesting_profile_id=profile_id)
    except Exception:
        runtime.close(timeout=5.0)
        raise
    return PublicClient.open(
        CoreConfig(enabled=True, project_id=project_id, profile_id=profile_id),
        writer=writer,
        consistency_policy="allow_stale",
        read_service=read_service,
    )


__all__ = ["open_local_client"]
