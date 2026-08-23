"""Shared guard for tooling-only pymupdf imports (v1.3.1 WP-2).

pymupdf is AGPL/commercial dual-licensed and is declared only as the
tooling-only optional extra ``pdf-advanced``. Scripts that need it must fail
with an actionable install hint instead of a bare ImportError.
"""
from __future__ import annotations

import importlib.util

INSTALL_HINT = "pip install zero-mem[pdf-advanced]"


def require_pymupdf():
    """Return the pymupdf module or raise SystemExit with the install hint.

    SystemExit (not ImportError) so CLI users see one clean line instead of a
    traceback; exit code 2 distinguishes tooling misconfiguration.
    """
    if importlib.util.find_spec("pymupdf") is None:
        raise SystemExit(
            "pymupdf is required for this PDF-extraction tooling script. "
            f"Install it with: {INSTALL_HINT} "
            "(AGPL/commercial dual-license; optional tooling-only extra, "
            "not a runtime dependency)."
        )
    import sys

    return sys.modules["pymupdf"]
