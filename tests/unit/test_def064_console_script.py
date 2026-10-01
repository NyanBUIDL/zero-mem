"""DEF-064 - console script for the MCP server.

``pip install zero-mem`` must expose ``zero-mem-mcp`` so agent clients can register the
server without knowing the repository layout (``claude mcp add zero-mem -- zero-mem-mcp
--profile-id claude-code --store-path <db>``).  Version is NOT bumped by this change.

The real install into a fresh venv is exercised by ``tests/packaging`` style acceptance
(see docs/defects/closures/T6a.md); here the declaration, the entry-point target and the
installed-script behaviour (same ``main`` over stdio) are pinned.
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit.t6a_mcp_helpers import REPO_ROOT, build_matrix_store

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]


def _scripts():
    document = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return document["project"]["scripts"]


def test_pyproject_declares_both_console_scripts():
    assert _scripts() == {
        "zero-mem": "zero_mem.cli:main",
        "zero-mem-mcp": "src.integration.m6.mcp_server:main",
    }


def test_version_is_not_bumped_by_this_change():
    from zero_mem.version import __version__

    assert __version__ == "1.6.1"


def test_entry_point_target_resolves_to_a_callable_main():
    module_name, _, attr = _scripts()["zero-mem-mcp"].partition(":")
    target = getattr(importlib.import_module(module_name), attr)
    assert callable(target)


def test_entry_point_main_prints_usage_and_exits_zero():
    module_name, _, attr = _scripts()["zero-mem-mcp"].partition(":")
    main = getattr(importlib.import_module(module_name), attr)
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_entry_point_speaks_initialize_and_tools_list_over_stdio(tmp_path):
    """Run exactly what the generated console script runs: ``sys.exit(main())``."""
    db = build_matrix_store(tmp_path)
    shim = ("import sys; from src.integration.m6.mcp_server import main; "
            "sys.exit(main())")
    proc = subprocess.Popen(
        [sys.executable, "-c", shim, "--store-path", str(db), "--profile-id", "claude-code"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=str(REPO_ROOT))
    try:
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ]
        out, err = proc.communicate("".join(json.dumps(r) + "\n" for r in requests), timeout=60)
    finally:
        proc.kill()
    assert proc.returncode == 0, err
    replies = [json.loads(line) for line in out.splitlines()]
    assert replies[0]["result"]["serverInfo"]["name"] == "zero-mem-m6"
    assert replies[0]["result"]["serverInfo"]["identity"] == "pinned"
    assert len(replies[1]["result"]["tools"]) == 11
