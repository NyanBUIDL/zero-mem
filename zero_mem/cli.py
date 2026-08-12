"""Minimal PKG-1 release CLI."""

from __future__ import annotations

import argparse

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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "_show_version", False):
        print(__version__)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
