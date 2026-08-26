#!/usr/bin/env python3
"""PKG-2 safe default uninstaller; canonical user data is never purged."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from release_common import (
    absolute_path,
    cli_shim_bytes,
    cli_shim_name,
    contained,
    default_paths,
    directory_link_target,
    fail,
    is_directory_link,
    reject_home_or_root,
    remove_directory_link,
    ReleaseError,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Remove Zero-Mem runtime components without purging user data.")
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--bin-dir", type=Path)
    parser.add_argument("--non-interactive", action="store_true")
    return parser


def _paths(args: argparse.Namespace) -> tuple[Path, Path]:
    default_runtime, default_bin = default_paths()
    runtime = absolute_path(args.runtime_root or default_runtime, "runtime root")
    bindir = absolute_path(args.bin_dir or default_bin, "binary root")
    home = Path.home().resolve()
    reject_home_or_root(runtime, home, "runtime root")
    reject_home_or_root(bindir, home, "binary root")
    return runtime, bindir


def uninstall(args: argparse.Namespace) -> int:
    runtime_root, bin_dir = _paths(args)
    if not runtime_root.exists() and not is_directory_link(runtime_root):
        return 0
    if is_directory_link(runtime_root) or not runtime_root.is_dir():
        raise fail("unsafe runtime root")
    metadata_path = runtime_root / "install.json"
    metadata = None
    if metadata_path.exists() or metadata_path.is_symlink():
        if metadata_path.is_symlink() or not metadata_path.is_file():
            raise fail("unsafe installation metadata")
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise fail("invalid installation metadata") from exc
        if not isinstance(metadata, dict) or metadata.get("schema_version") != 1:
            raise fail("unsupported installation metadata")

    current = runtime_root / "current"
    if is_directory_link(current):
        target = directory_link_target(current)
        if not contained(runtime_root / "runtimes", target):
            raise fail("active runtime pointer escapes managed root")
        remove_directory_link(current)
    elif current.exists():
        raise fail("unsafe active runtime")

    runtimes = runtime_root / "runtimes"
    if is_directory_link(runtimes):
        raise fail("unsafe runtime directory")
    if runtimes.is_dir():
        for child in list(runtimes.iterdir()):
            if is_directory_link(child) or not contained(runtimes, child):
                raise fail("unsafe managed runtime entry")
            if child.name.startswith(".staging-") or (metadata and child.name == metadata.get("version")):
                shutil.rmtree(child)
            else:
                print("zero-mem: preserved an unrecognized managed runtime entry", file=sys.stderr)
        if not any(runtimes.iterdir()):
            runtimes.rmdir()
    if metadata_path.exists():
        metadata_path.unlink()

    shim = bin_dir / cli_shim_name()
    if shim.is_symlink():
        raise fail("refusing to remove symlinked CLI shim")
    if shim.is_file() and shim.read_bytes() == cli_shim_bytes(runtime_root):
        shim.unlink()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return uninstall(args)
    except ReleaseError as exc:
        print(f"zero-mem: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
