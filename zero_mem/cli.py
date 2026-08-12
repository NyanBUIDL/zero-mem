"""Minimal PKG-1 release CLI."""

from __future__ import annotations

import argparse
import sys

from .version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zero-mem",
        description="Zero-Mem local-first evidence and memory sidecar.",
    )
    parser.add_argument("--version", action="version", version=f"zero-mem {__version__}")
    subparsers = parser.add_subparsers(dest="command")
    version_parser = subparsers.add_parser("version", help="show the installed Zero-Mem version")
    version_parser.set_defaults(_show_version=True)
    setup_parser = subparsers.add_parser("setup", help="initialize an empty user-local Zero-Mem installation")
    setup_parser.set_defaults(_setup=True)
    doctor_parser = subparsers.add_parser("doctor", help="check runtime and optional integration health")
    doctor_parser.add_argument("--json", action="store_true", help="emit stable machine-readable results")
    doctor_parser.set_defaults(_doctor=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "_show_version", False):
        print(__version__)
    elif getattr(args, "_setup", False):
        from .commands_setup import run
        from .paths import ConfigurationError, SetupError

        try:
            run()
        except (ConfigurationError, SetupError) as exc:
            print(f"zero-mem: {exc}", file=sys.stderr)
            return 2
        except Exception:
            print("zero-mem: setup failed", file=sys.stderr)
            return 2
        print("READY")
    elif getattr(args, "_doctor", False):
        from .commands_doctor import run

        return run(as_json=args.json)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
