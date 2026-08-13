"""Minimal PKG-1 release CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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
    backup_parser = subparsers.add_parser("backup", help="create and recover local Zero-Mem backups")
    backup_subparsers = backup_parser.add_subparsers(dest="backup_command", required=True)
    create_parser = backup_subparsers.add_parser("create", help="create a verified local backup")
    create_parser.add_argument("--output", type=str, help="final backup directory")
    create_parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    create_parser.set_defaults(_backup_create=True)
    verify_parser = backup_subparsers.add_parser("verify", help="verify a backup without changing state")
    verify_parser.add_argument("backup", type=str)
    verify_parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    verify_parser.set_defaults(_backup_verify=True)
    restore_parser = backup_subparsers.add_parser("restore", help="restore a verified backup")
    restore_parser.add_argument("backup", type=str)
    restore_parser.add_argument("--yes", action="store_true", help="confirm replacement of active data")
    restore_parser.add_argument("--data-root", type=str, help="explicit target data root")
    restore_parser.add_argument("--corpus-root", type=str, help="explicit target corpus root")
    restore_parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    restore_parser.set_defaults(_backup_restore=True)
    upgrade_parser = subparsers.add_parser("upgrade", help="check and safely refresh disposable derived state")
    upgrade_parser.add_argument("--check", action="store_true", help="inspect upgrade compatibility without changing state")
    upgrade_parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    upgrade_parser.set_defaults(_upgrade=True)
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
    elif getattr(args, "_backup_create", False):
        from .backup import BackupError, create_backup

        try:
            path = create_backup(Path(args.output) if args.output else None)
            result = {"status": "SUCCESS", "backup": str(path)}
            print(json.dumps(result, sort_keys=True, separators=(",", ":")) if args.json else f"Backup created:\n{path}")
            return 0
        except BackupError as exc:
            print(f"zero-mem: backup create failed: {exc.code}", file=sys.stderr)
            return 2
    elif getattr(args, "_backup_verify", False):
        from .backup import BackupError, verify_backup

        try:
            result = verify_backup(Path(args.backup))
            print(json.dumps(result, sort_keys=True, separators=(",", ":")) if args.json else "Backup verification:\nVALID")
            return 0
        except BackupError as exc:
            print(f"zero-mem: backup verify failed: {exc.code}", file=sys.stderr)
            return 2
    elif getattr(args, "_backup_restore", False):
        from .backup import BackupError, restore_backup

        try:
            result = restore_backup(
                Path(args.backup),
                yes=args.yes,
                target_data_root=Path(args.data_root) if args.data_root else None,
                target_corpus_root=Path(args.corpus_root) if args.corpus_root else None,
            )
            print(json.dumps(result, sort_keys=True, separators=(",", ":")) if args.json else "Restore:\nSUCCESS")
            return 0
        except BackupError as exc:
            print(f"zero-mem: backup restore failed: {exc.code}", file=sys.stderr)
            return 2
    elif getattr(args, "_upgrade", False):
        from .upgrade import UpgradeError, check, upgrade

        try:
            result = check() if args.check else upgrade()
            print(json.dumps(result, sort_keys=True, separators=(",", ":")) if args.json else result["status"])
            return 0 if result["status"] in {"READY", "SUCCESS"} else 2
        except UpgradeError as exc:
            print(f"zero-mem: upgrade failed: {exc.code}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
