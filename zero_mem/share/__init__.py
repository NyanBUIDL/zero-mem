"""Peer sharing over the LAN (ADR-V170-05): publish / pull, read-only, pinned mutual TLS 1.3.

The package is import-safe without the optional ``cryptography`` dependency (extra ``share``): only
:mod:`zero_mem.share.identity` needs it, and it imports it lazily with a clear error. Nothing here is imported by the
core (``Memory``, the CLI) except the tiny, dependency-free :mod:`zero_mem.share.labels`.
"""
from __future__ import annotations

EXTRA_HINT = 'install the optional extra: pip install "zero-mem[share]"'
PROTOCOL_VERSION = 1
INVITE_PREFIX = "zm1:"
DEFAULT_PORT = 47890
DISCOVERY_PORT = 47891
SERVICE_NAME = "zero-mem-share"
SNI_PAIR = "zm-pair"
SNI_PEER = "zm-peer"


class ShareError(Exception):
    """A sharing failure with a stable ``code`` and a message that is safe to show (never a token, key or content)."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        self.message = message or code
        super().__init__(f"{code}: {self.message}")


class ShareDependencyError(ShareError):
    """The optional ``cryptography`` package is not installed."""

    def __init__(self) -> None:
        super().__init__("missing_dependency", "peer sharing needs the 'cryptography' package; " + EXTRA_HINT)


class ShareDisabledError(ShareError):
    """Sharing is off (default), the kill switch is on, or the settings file is unusable."""

    def __init__(self, reason: str) -> None:
        super().__init__("sharing_disabled", reason)
