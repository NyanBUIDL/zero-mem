"""Minimal PKG-1 release CLI."""

from __future__ import annotations

import argparse
import json
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
    integrate_parser = subparsers.add_parser("integrate", help="configure an optional external integration")
    integrate_subparsers = integrate_parser.add_subparsers(dest="integration", required=True)
    hermes_parser = integrate_subparsers.add_parser("hermes", help="configure the optional Hermes boundary")
    hermes_parser.add_argument("--project-id", help="explicit Zero-Mem project identifier")
    hermes_parser.add_argument("--profile-id", help="explicit Zero-Mem profile identifier")
    hermes_parser.add_argument("--check", action="store_true", help="inspect without changing state")
    hermes_parser.add_argument("--remove", action="store_true", help="remove only Zero-Mem-owned integration state")
    hermes_parser.set_defaults(_integrate_hermes=True)
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
    elif getattr(args, "_integrate_hermes", False):
        from .hermes_integration import command

        code, result = command(
            project_id=args.project_id,
            profile_id=args.profile_id,
            check=args.check,
            remove=args.remove,
        )
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return code
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
