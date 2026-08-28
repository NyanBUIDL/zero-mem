#!/usr/bin/env python3
"""Verify the release wheel/sdist license payload and core metadata."""
from __future__ import annotations

import argparse
import email
import sys
import tarfile
import zipfile
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("sdist", type=Path)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-author", required=True)
    parser.add_argument("--license", dest="license_path", type=Path, required=True)
    parser.add_argument("--notice", dest="notice_path", type=Path, required=True)
    return parser


def _require_equal(label: str, actual: bytes | str | None, expected: bytes | str) -> None:
    if actual != expected:
        raise ValueError(f"{label} mismatch")


def verify(args: argparse.Namespace) -> None:
    license_bytes = args.license_path.read_bytes()
    notice_bytes = args.notice_path.read_bytes()
    wheel_prefix = f"zero_mem-{args.expected_version}.dist-info"
    sdist_prefix = f"zero_mem-{args.expected_version}"

    with zipfile.ZipFile(args.wheel) as wheel:
        _require_equal(
            "wheel LICENSE",
            wheel.read(f"{wheel_prefix}/licenses/LICENSE"),
            license_bytes,
        )
        _require_equal(
            "wheel NOTICE",
            wheel.read(f"{wheel_prefix}/licenses/NOTICE"),
            notice_bytes,
        )
        metadata = email.message_from_bytes(wheel.read(f"{wheel_prefix}/METADATA"))
        _require_equal("wheel Name", metadata.get("Name"), "zero-mem")
        _require_equal("wheel Version", metadata.get("Version"), args.expected_version)
        _require_equal("wheel Author", metadata.get("Author"), args.expected_author)

    with tarfile.open(args.sdist, "r:gz") as sdist:
        for filename, expected in (("LICENSE", license_bytes), ("NOTICE", notice_bytes)):
            member_name = f"{sdist_prefix}/{filename}"
            member = sdist.getmember(member_name)
            extracted = sdist.extractfile(member)
            if extracted is None:
                raise ValueError(f"sdist {filename} is not a regular file")
            _require_equal(f"sdist {filename}", extracted.read(), expected)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        verify(args)
    except (OSError, KeyError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(f"release_artifact_contract=FAIL: {exc}", file=sys.stderr)
        return 1
    print("release_artifact_contract=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
