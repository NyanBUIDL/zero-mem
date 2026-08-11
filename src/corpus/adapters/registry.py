"""M10.2 — adapter registry + deterministic format selection.

Adding a future adapter (Markdown, HTML, DOCX, CSV, JSON, source code, logs)
requires NO core redesign: instantiate it and register it here. Selection is
deterministic and adapter-choice grants nothing (authorization is separate).
"""
from __future__ import annotations

from typing import Iterable, Optional

from .base import FormatAdapter, FormatKind


#: Registry of available adapters. Extended by registering new instances.
ADAPTER_REGISTRY: list[FormatAdapter] = []


def register_adapter(adapter: FormatAdapter) -> None:
    if not any(a.format == adapter.format for a in ADAPTER_REGISTRY):
        ADAPTER_REGISTRY.append(adapter)


def select_adapter(kind_hint: str) -> Optional[FormatAdapter]:
    """Return the first registered adapter that supports ``kind_hint``.

    Deterministic: iterates the registry in registration order. If no adapter
    supports the hint, returns None (caller treats as unsupported_format).
    """
    for adapter in ADAPTER_REGISTRY:
        try:
            if adapter.supports(kind_hint):
                return adapter
        except Exception:
            continue
    return None


def available_adapters() -> list[FormatAdapter]:
    return [a for a in ADAPTER_REGISTRY if a.is_available()]


def _default_registry() -> list[FormatAdapter]:
    from .pdf import PdfAdapter
    from .txt import TxtAdapter

    return [TxtAdapter(), PdfAdapter()]


# Populate the default registry once at import (idempotent).
for _a in _default_registry():
    register_adapter(_a)


__all__ = ["ADAPTER_REGISTRY", "register_adapter", "select_adapter", "available_adapters"]
