"""Shared symlink-capability guard (WP-05 / DEF-035).

Windows without Developer Mode or admin privilege raises WinError 1314 on
symlink creation. Security tests that REQUIRE a real symlink must skip there
(with reason) instead of erroring; tests that do not depend on symlinks keep
running. POSIX always returns (symlinks available).
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest


def require_symlinks() -> None:
    """pytest.skip() when the platform cannot create symlinks."""
    if os.name != "nt":
        return
    probe = Path(tempfile.mkdtemp())
    try:
        (probe / "target").touch()
        (probe / "link").symlink_to(probe / "target")
    except OSError:
        pytest.skip(
            "symlink creation unavailable on this platform "
            "(Windows requires Developer Mode or admin privilege)"
        )
    finally:
        shutil.rmtree(probe, ignore_errors=True)
