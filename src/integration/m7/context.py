"""WP-32 deterministic, bounded context assembly over authorized M7 evidence."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Final

from .budget import estimate_tokens
from .contracts import EvidenceSet, MemoryRoute
from .envelope import serialize_evidence_set


READY: Final[str] = "READY"
BUDGET_EXCEEDED: Final[str] = "BUDGET_EXCEEDED"
INVALID_INPUT: Final[str] = "INVALID_INPUT"
DEFAULT_MAX_CONTEXT_BYTES: Final[int] = 256 * 1024
DEFAULT_MAX_CONTEXT_TOKENS: Final[int] = 6000


@dataclass(frozen=True)
class ContextConfig:
    """Server-governed context limits; callers may only tighten them."""

    max_bytes: int = DEFAULT_MAX_CONTEXT_BYTES
    max_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS

    def __post_init__(self) -> None:
        for name, value in (("max_bytes", self.max_bytes), ("max_tokens", self.max_tokens)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
            ceiling = DEFAULT_MAX_CONTEXT_BYTES if name == "max_bytes" else DEFAULT_MAX_CONTEXT_TOKENS
            if value > ceiling:
                raise ValueError(f"{name} exceeds governed ceiling")


@dataclass(frozen=True)
class ContextResult:
    status: str
    context: str
    omitted_count: int
    estimated_tokens: int


def _render_with_budget(evidence: EvidenceSet, config: ContextConfig) -> ContextResult:
    """Drop only least-priority selected items until both limits fit."""
    primary = list(evidence.primary_evidence)
    supporting = list(evidence.supporting_evidence)
    dropped = 0
    if evidence.route is MemoryRoute.EXTERNAL_CURRENT:
        dropped = len(primary) + len(supporting)
        primary = []
        supporting = []
    actual_tokens = 0

    for _ in range(len(primary) + len(supporting) + 1):
        candidate = replace(
            evidence,
            primary_evidence=tuple(primary),
            supporting_evidence=tuple(supporting),
            omitted_count=evidence.omitted_count + dropped,
        )
        rendered = serialize_evidence_set(candidate)
        actual_tokens = estimate_tokens(rendered)
        actual_bytes = len(rendered.encode("utf-8"))
        if actual_bytes <= config.max_bytes and actual_tokens <= config.max_tokens:
            return ContextResult(READY, rendered, evidence.omitted_count + dropped, actual_tokens)

        # Supporting evidence is lower priority and is removed first. Keep at
        # least one primary item when one exists; if the primary item itself
        # cannot fit, fail closed instead of truncating provenance or UTF-8.
        if supporting:
            supporting.pop()
            dropped += 1
            continue
        if len(primary) > 1:
            primary.pop()
            dropped += 1
            continue
        return ContextResult(BUDGET_EXCEEDED, "", evidence.omitted_count + dropped, actual_tokens)

    return ContextResult(BUDGET_EXCEEDED, "", evidence.omitted_count + dropped, actual_tokens)


def assemble_context(evidence: EvidenceSet, *, config: ContextConfig | None = None) -> ContextResult:
    """Assemble a deterministic DATA-only envelope from authorized evidence.

    The input EvidenceSet is immutable and already authorization-filtered by M5/M7.
    This function performs no retrieval, authorization, persistence, or network I/O.
    """
    if not isinstance(evidence, EvidenceSet):
        return ContextResult(INVALID_INPUT, "", 0, 0)
    if config is not None and not isinstance(config, ContextConfig):
        return ContextResult(INVALID_INPUT, "", 0, 0)
    try:
        return _render_with_budget(evidence, config or ContextConfig())
    except (AttributeError, TypeError, ValueError):
        return ContextResult(INVALID_INPUT, "", 0, 0)


__all__ = ["BUDGET_EXCEEDED", "ContextConfig", "ContextResult", "INVALID_INPUT", "READY", "assemble_context"]
