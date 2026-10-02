"""``zero-mem ui``: start the owner's local control panel (see ``zero_mem.ui`` and docs/runbooks/control-panel.md).

A thin shell: the data root comes from ``Layout.resolve`` (so ``--memory`` / ``ZERO_MEM_DATA_ROOT`` just work), the acting
profile from the global ``--profile``. The panel binds to loopback only and prints its one-time URL once.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from .commands_memory import EXIT_ERROR, EXIT_OK, _common, _err

BANNER = """\
Zero-Mem control panel (owner console)
  memory      {root}
  acting as   {profile}
  allow-roots {roots}
  open        {url}
  The link works ONCE and is not saved anywhere; stop with Ctrl+C (idle timeout: {idle:g} min).

  WARNING: this panel can approve rules, grant write access to agents and ingest files. Do NOT give agents a shell on
  this machine, this URL or the browser session; anything that can reach it acts as you."""


def add_ui_parser(subparsers) -> None:
    p = subparsers.add_parser("ui", parents=[_common()], help="start the local owner control panel (loopback only)")
    p.add_argument("--port", type=int, default=0, help="port on 127.0.0.1 (default: a random free port)")
    p.add_argument("--host", default="127.0.0.1", help="loopback address to bind: 127.0.0.1 (default) or ::1; anything else is refused")
    p.add_argument("--allow-root", action="append", default=[], metavar="DIR",
                   help="folder the panel may ingest by path (repeatable; default none: uploads only)")
    p.add_argument("--open", dest="open_browser", action="store_true", help="open the one-time URL in your browser")
    p.add_argument("--no-open", dest="open_browser", action="store_false", help="do not open a browser (default)")
    p.add_argument("--idle-timeout", type=float, default=60.0, metavar="MINUTES",
                   help="stop after this many idle minutes (default 60)")
    p.set_defaults(_ui_cmd=True, open_browser=False)


def run(args) -> int:
    from .memory_layout import LayoutError
    from .ui import PanelConfigError, PanelSecurityError, create_server

    if not 0 < args.idle_timeout <= 24 * 60 * 7:
        _err("--idle-timeout must be between 0 and 10080 minutes")
        return EXIT_ERROR
    if not 0 <= args.port <= 65535:
        _err("--port must be between 0 and 65535")
        return EXIT_ERROR
    try:
        server = create_server(host=args.host, port=args.port, profile=args.profile, allow_roots=args.allow_root,
                               idle_timeout_minutes=args.idle_timeout)
    except PanelSecurityError as exc:
        _err(str(exc))
        return EXIT_ERROR
    except PanelConfigError as exc:
        _err(str(exc))
        return EXIT_ERROR
    except LayoutError as exc:
        _err(str(exc))
        return EXIT_ERROR
    except OSError:
        _err("cannot start the control panel (is the port in use?)")
        return EXIT_ERROR
    panel = server.panel
    print(BANNER.format(root=panel.layout.data_root, profile=panel.profile, idle=args.idle_timeout,
                        roots=", ".join(panel.roots) or "none (uploads only)", url=server.entry_url()), flush=True)
    if args.open_browser:
        import webbrowser

        try:
            webbrowser.open(server.entry_url())
        except Exception:  # noqa: BLE001
            _err("could not open a browser; open the link above yourself")
    try:
        server.serve()
    except KeyboardInterrupt:
        print("\nstopping", file=sys.stderr)
    finally:
        server.server_close()
    return EXIT_OK


def dispatch(args) -> Optional[int]:
    if not getattr(args, "_ui_cmd", False):
        return None
    try:
        return run(args)
    except KeyboardInterrupt:
        return 130


__all__ = ["add_ui_parser", "dispatch", "run"]
