#!/usr/bin/env python3
"""Build a deterministic-enough PKG-2 acceptance bundle from a wheel."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    output = args.output.resolve()
    if wheel.suffix != ".whl" or not wheel.is_file():
        raise SystemExit("wheel not found")
    if output.exists():
        shutil.rmtree(output)
    (output / "wheels").mkdir(parents=True)
    shutil.copy2(wheel, output / "wheels" / wheel.name)
    for name in ("install.py", "uninstall.py", "release_common.py", "install.sh", "uninstall.sh", "README.md"):
        shutil.copy2(PACKAGING / name, output / name)
    for name in ("install.sh", "uninstall.sh"):
        (output / name).chmod(0o755)
    for bytecode in output.rglob("__pycache__"):
        shutil.rmtree(bytecode)
    payload = sorted([f"wheels/{wheel.name}", "install.py", "uninstall.py", "release_common.py", "install.sh", "uninstall.sh", "README.md"])
    checksums = "".join(f"{sha256(output / name)}  {name}\n" for name in payload).encode()
    (output / "checksums.sha256").write_bytes(checksums)
    manifest = {
        "schema_version": 1,
        "product": "zero-mem",
        "version": "1.1.0",
        "platform": "linux-x86_64",
        "bundle_status": "PKG-2 INSTALLER ACCEPTANCE BUNDLE",
        "wheel": f"wheels/{wheel.name}",
        "payload_files": payload,
        "checksums_sha256": hashlib.sha256(checksums).hexdigest(),
        "optional_components": ["pypdf wheel when explicitly selected; not mandatory"],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
