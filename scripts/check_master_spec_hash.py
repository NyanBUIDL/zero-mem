"""V132-06 — Master spec .docx freeze hash check (D-03 Option A).

The .docx master spec is THE authority (AGENTS.md). docs/MASTER-SPEC.md is a
controlled projection. This script fail-closes when the live .docx SHA-256
no longer matches the anchor recorded in
docs/v1.3.2/decisions/ADR-V132-02-MASTER-SPEC-FREEZE.md — i.e. the docx was
edited without regenerating the projection.

Usage:  .venv-v124/bin/python scripts/check_master_spec_hash.py [--repo ROOT]
Exit 0 = anchored; exit 1 = drift (reconcile before merging spec-touching WPs).
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

DOCX_NAME = "Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx"
ADR_REL = Path("docs/v1.3.2/decisions/ADR-V132-02-MASTER-SPEC-FREEZE.md")
ANCHOR_RE = re.compile(r"SHA-256:\s*`([0-9a-f]{64})`")


def _docx_hash(docx_path: Path) -> str:
    return hashlib.sha256(docx_path.read_bytes()).hexdigest()


def _anchored_hash(repo_root: Path) -> str | None:
    adr = repo_root / ADR_REL
    if not adr.is_file():
        return None
    m = ANCHOR_RE.search(adr.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def check_master_spec(repo_root: Path) -> tuple[str, str | None]:
    """Return (live_sha256, anchored_sha256_or_None)."""
    docx = repo_root / DOCX_NAME
    if not docx.is_file():
        raise FileNotFoundError(f"master spec not found: {docx}")
    return _docx_hash(docx), _anchored_hash(repo_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args(argv)
    try:
        live, anchored = check_master_spec(Path(args.repo))
    except FileNotFoundError as exc:
        print(f"MASTER_SPEC_ERROR: {exc}", file=sys.stderr)
        return 1
    if not anchored:
        print("MASTER_SPEC_VIOLATION: no SHA-256 anchor in "
              f"{ADR_REL.as_posix()}", file=sys.stderr)
        return 1
    if live != anchored:
        print("MASTER_SPEC_DRIFT: live .docx sha256 does not match the ADR "
              "anchor — regenerate MASTER-SPEC.md projection and update the "
              "anchor via a new ADR BEFORE merging any spec-touching WP.",
              file=sys.stderr)
        return 1
    print(f"master spec anchored OK ({live[:16]}…)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
