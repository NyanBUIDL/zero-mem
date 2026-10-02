"""Dependency-free peer label lookup for the core read path (``Memory.recall`` labels peer-imported hits)."""
from __future__ import annotations

import re

_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@-]{0,39}$")


def peer_label(layout, peer_id: str) -> str:
    """The label of owner ``peer_id`` as recorded at join time, else the id itself. Never raises."""
    try:
        from .events import ShareLog

        record = ShareLog.for_layout(layout).owner(peer_id)
        label = record.get("label") if record else None
        if isinstance(label, str) and _SAFE.fullmatch(label):
            return f"{label} ({peer_id[:8]})"
    except Exception:
        pass
    return str(peer_id)[:20]
