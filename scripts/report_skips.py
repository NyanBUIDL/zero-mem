"""V132-08 — Skip transparency report (audit P3-9).

Prints every skipped test WITH its reason at the end of a suite run, so
silent coverage loss (e.g. ZERO_MEM_V130_ARCHIVE_FIXTURE unset) is visible.

Usage (no new dependencies):
  .venv-v124/bin/python -m pytest tests/unit ... \\
      -p tests.v132_skip_report --disable-warnings -q

Or standalone after a run:
  .venv-v124/bin/python scripts/report_skips.py <pytest-output.log>

Convention (docs/v1.3.2/EVIDENCE.md): each skip must be attributable to an
environment-unavailable fixture; unexplained skips are regressions to fix,
not to normalize.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def skips_from_log(text: str) -> list[tuple[str, str]]:
    """Extract (nodeid, reason) pairs from `pytest -ra` style output."""
    out = []
    pat = re.compile(r"^(SKIPPED|FAILED|ERROR)?\s*\[?\d*\]?\s*"
                     r"(tests/[^\s]+)::(\S+)\s+-\s+(.+)$")
    for line in text.splitlines():
        m = re.match(r"^SKIPPED \[\d+\] (tests/\S+):\d+: (.+)$", line)
        if m:
            out.append((m.group(1), m.group(2)))
            continue
        m2 = re.match(r"^(tests/\S+)::(\S+) SKIPPED \(?(.*?)\)?$", line)
        if m2:
            out.append((m2.group(1) + "::" + m2.group(2), m2.group(3)))
    return out


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: report_skips.py <pytest-log>", file=sys.stderr)
        return 1
    text = Path(args[0]).read_text(encoding="utf-8", errors="replace")
    pairs = skips_from_log(text)
    print(f"skip-report: {len(pairs)} skip(s)")
    for nodeid, reason in pairs:
        print(f"  SKIP {nodeid} — reason: {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
