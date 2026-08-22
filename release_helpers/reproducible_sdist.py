#!/usr/bin/env python3
"""Create a deterministic gzip sdist from an extracted source directory."""
from __future__ import annotations

import argparse
import gzip
import tarfile
from pathlib import Path

SOURCE_DATE_EPOCH = 315532800


def _tar_info(root: Path, path: Path) -> tarfile.TarInfo:
    info = tarfile.TarInfo(str(path.relative_to(root.parent)))
    if path.is_dir():
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
    else:
        info.type = tarfile.REGTYPE
        info.mode = 0o644
        info.size = path.stat().st_size
    info.mtime = SOURCE_DATE_EPOCH
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def build(source_root: Path, output: Path) -> None:
    source_root = source_root.resolve()
    if not source_root.is_dir() or source_root.is_symlink():
        raise ValueError("source_root_must_be_real_directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    members = [source_root] + sorted(source_root.rglob("*"), key=lambda p: str(p.relative_to(source_root)))
    for member in members:
        if member.is_symlink():
            raise ValueError("source_tree_symlink_not_allowed")
    with output.open("xb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=SOURCE_DATE_EPOCH, filename="") as gz:
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.GNU_FORMAT) as archive:
                for member in members:
                    info = _tar_info(source_root, member)
                    if member.is_file():
                        with member.open("rb") as handle:
                            archive.addfile(info, handle)
                    else:
                        archive.addfile(info)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.source_root, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
