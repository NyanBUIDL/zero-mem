"""M8.3 static security tests.

Enforces, without execution, the hard boundaries from the M8.3 directive:

- graph_access.py must not import / reference GrantAdminService,
  AuthorizedWriteService, any HTTP client, any LLM SDK, or any embedding
  client;
- no hardcoded HOME path;
- the service must accept ONLY an AuthorizedReadService (M5 remains the sole
  authorization authority; no second policy engine, no graph-derived auth);
- the module must not implement a new Hermes/M6 tool surface (no
  tool-name registration, no MCP surface).
"""

from __future__ import annotations

import ast
import pathlib

import pytest

MODULE = pathlib.Path("src/m8/graph_access.py")
SOURCE = MODULE.read_text()
TREE = ast.parse(SOURCE)

FORBIDDEN_MODULES = {
    "openai", "anthropic", "http", "requests", "urllib", "socket",
    "aiohttp", "httpx", "embedding", "llm", "openai",
    "src.access.grant_admin", "src.access.authorized_write",
    "GrantAdminService", "AuthorizedWriteService",
    "grant_admin", "authorized_write",
}

FORBIDDEN_TOKENS = {
    "write_service",
    "grant_admin",
    "mcp",
    "tool_name",
    "register_tool",
    "HERMES_HOME",
    "home()",
    "Path.home()",
    "os.environ",
}


def _imported_names() -> set[str]:
    names: set[str] = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            for n in node.names:
                names.add(n.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
            for n in node.names:
                names.add(n.name)
    return names


def test_no_forbidden_module_imports():
    names = _imported_names()
    lower = {n.lower() for n in names}
    assert FORBIDDEN_MODULES.isdisjoint(lower), names & FORBIDDEN_MODULES


def test_no_forbidden_tokens():
    low = SOURCE.lower()
    hits = {t for t in FORBIDDEN_TOKENS if t.lower() in low}
    assert not hits, hits


def test_no_hardcoded_home():
    # No literal reference to the operator's real home directory.
    assert "/home/brian-nguyen" not in SOURCE


def test_service_accepts_only_authorized_read_service():
    # GraphAccessService.__init__ must type-check that its dependency is an
    # AuthorizedReadService and raise otherwise (no alternate auth path).
    import sqlite3

    import pytest as _pytest

    from src.m8.graph_access import GraphAccessService, M8GraphAccessError

    with _pytest.raises(M8GraphAccessError):
        GraphAccessService(object())  # not an AuthorizedReadService

    # A raw connection must also be rejected (M5 facade is mandatory).
    conn = sqlite3.connect(":memory:")
    with _pytest.raises(M8GraphAccessError):
        GraphAccessService(conn)


def test_module_exposes_no_tool_surface():
    # M6 tool surface unchanged: the module must not register a Hermes/MCP
    # read tool. Confirm by absence of a tool-surface symbol in __all__/exports.
    tree = ast.parse(SOURCE)
    exported = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    exported.add(t.id)
    assert "register_tool" not in exported
    assert "mcp_tool" not in exported
