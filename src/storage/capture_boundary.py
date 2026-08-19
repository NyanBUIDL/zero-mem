"""Stable project-owned capture boundary types."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, Mapping, Any


class CaptureRejected(ValueError):
    """Sanitized capture rejection."""


@dataclass(frozen=True)
class CaptureStoreConfig:
    root: Path
    stream_name: str = "events-v1.jsonl"

    @property
    def path(self) -> Path:
        return self.root / self.stream_name


@dataclass(frozen=True)
class AppendResult:
    status: Literal["appended", "duplicate"]
    event_id: str
    sequence: int
    content_hash: str
    duplicate_class: str | None = None

    @property
    def canonical_durable(self) -> bool:
        """The append or duplicate references durable canonical state."""
        return True

    @property
    def reason_code(self) -> str | None:
        return f"duplicate_{self.duplicate_class}" if self.duplicate_class else None


class CaptureStore(Protocol):
    def append(self, event: Mapping[str, Any]) -> AppendResult: ...
    def contains_event_id(self, event_id: str) -> bool: ...
    def contains_content_hash(self, content_hash: str) -> bool: ...
    def inspect_record(self, event_id: str) -> dict[str, Any] | None: ...
    def close(self) -> None: ...
