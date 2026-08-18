"""WP-05 benchmark wrapper for the real authorized retrieval/evidence path."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    if not os.environ.get("ZERO_MEM_M10_DB"):
        raise SystemExit("ZERO_MEM_M10_DB is required")
    script = Path(__file__).with_name("run_m10_e2e.py")
    return subprocess.run([sys.executable, str(script)], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
