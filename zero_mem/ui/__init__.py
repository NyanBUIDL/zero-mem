"""``zero-mem ui``: the owner's local control panel (standard library only, loopback only). See docs/runbooks/control-panel.md."""
from __future__ import annotations

from typing import Optional, Sequence

from ..memory_layout import Layout
from .handlers import Panel, PanelConfigError
from .server import PanelSecurityError, PanelServer, resolve_host

DEFAULT_IDLE_MINUTES = 60.0


def create_server(*, host: str = "127.0.0.1", port: int = 0, profile: str = "default", allow_roots: Sequence = (),
                  idle_timeout_minutes: float = DEFAULT_IDLE_MINUTES, layout: Optional[Layout] = None,
                  max_connections: int = 32, request_timeout: float = 15.0, log=None) -> PanelServer:
    """Build (but do not start) a control-panel server. A non-loopback ``host`` is refused before anything is created."""
    resolve_host(host)  # refuse first: no side effect for a refused configuration
    resolved = layout if layout is not None else Layout.resolve(None)
    resolved.ensure()
    panel = Panel(resolved, profile, allow_roots)
    server = PanelServer(host, port, panel.route, idle_timeout=idle_timeout_minutes * 60.0,
                         max_connections=max_connections, request_timeout=request_timeout, log=log)
    server.panel = panel
    return server


__all__ = ["DEFAULT_IDLE_MINUTES", "Panel", "PanelConfigError", "PanelSecurityError", "PanelServer", "create_server"]
