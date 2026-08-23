from __future__ import annotations

import importlib.metadata
import importlib.util

import zero_mem.version


def test_distribution_version_matches_version_module():
    """pip metadata (importlib) and zero_mem/version.py must agree.

    Regression for v1.3.0: tag v1.3.0 was published while version.py still read
    "1.2.4", so builds from the tag self-reported the wrong version. Works both
    for regular and editable installs; skips only if the distribution is not
    installed in the active environment.
    """
    if importlib.util.find_spec("zero_mem") is None:
        raise AssertionError("zero_mem package must be importable")
    try:
        dist_version = importlib.metadata.version("zero-mem")
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover
        raise AssertionError(
            "zero-mem distribution metadata not found; reinstall editable"
        )
    assert dist_version == zero_mem.version.__version__
