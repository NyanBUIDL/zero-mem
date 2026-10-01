"""DEF-066 - a bad / missing configured ``corpus-store-path`` must not abort the
MCP server start.

Corpus search reads the main derived store (``handlers._open_facade``);
``open_corpus_conn`` has no caller.  The vestigial setting used to raise from
``M6Runtime.__init__`` (``_validate_corpus_store_path``), so one stale line in the
user config (or ``ZM_M6_CORPUS_STORE_PATH``) took the whole server down.  T3 made the
doctor advice honest; this closes the server-start half.  Real stdio subprocess.
"""
from __future__ import annotations

import sqlite3

import pytest

from tests.unit.t6a_mcp_helpers import StdioServer, build_matrix_store, markers

BAD_PATHS = {
    "missing": lambda tmp: str(tmp / "no-such-corpus.sqlite"),
    "relative": lambda tmp: "relative/corpus.sqlite",
}


def _not_a_corpus_store(tmp_path) -> str:
    path = tmp_path / "not-a-corpus.sqlite"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE unrelated (x)")
    conn.commit()
    conn.close()
    return str(path)


@pytest.mark.parametrize("kind", ["missing", "relative", "not_a_corpus"])
def test_server_starts_and_searches_with_a_bad_configured_corpus_path(tmp_path, kind):
    db = build_matrix_store(tmp_path)
    bad = (_not_a_corpus_store(tmp_path) if kind == "not_a_corpus"
           else BAD_PATHS[kind](tmp_path))
    server = StdioServer(["--store-path", str(db)], env={"ZM_M6_CORPUS_STORE_PATH": bad})
    try:
        info = server.initialize()
        assert info["result"]["serverInfo"]["name"] == "zero-mem-m6"
        resp = server.call("corpus_search", {
            "search_text": "zebra", "requesting_profile_id": "claude-code", "limit": 20})
        env = resp["result"]["structuredContent"]
        assert env["status"] == "SUCCESS"
        assert markers(env["results"]) == ["A", "C", "E", "H"]
    finally:
        err = server.close()
    # One-line diagnostic with the stable code, and never the configured path.
    assert "corpus" in err.lower()
    assert bad not in err
    assert "Traceback" not in err


def test_valid_configured_corpus_path_is_still_used(tmp_path):
    from src.integration.m6 import runtime as rt

    db = build_matrix_store(tmp_path)
    try:
        r = rt.configure(db, corpus_store_path=db)
        assert r.corpus_store_path == db
        assert r.corpus_store_config_error is None
    finally:
        rt.close_default()
