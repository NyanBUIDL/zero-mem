"""Shared fixtures for the T6a (MCP read-side) tests.

Builds a real derived store (production corpus projection + persistent READ
grants) holding the section-3 matrix of docs/design/SHARED-MEMORY-RUNTIME.md,
and drives the MCP server both in-process and as a real stdio subprocess
(JSON-RPC over pipes).  Not collected by pytest (no ``test_`` prefix).

Unit matrix (every unit contains the token ``zebra`` plus a unique marker):

    A  claude-code / ks-shared        B  codex / ks-shared
    C  claude-code / private (no ks)  D  codex / private (no ks)
    E  all-NULL scope                 F  profile NULL / ks-shared
    G  codex / ks-other               H  claude-code / ks-other
    I  hermes / ks-hermes-only        (a space nobody else has a grant on)

READ grants (knowledge_space): claude-code -> ks-shared, codex -> ks-shared.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from src.access import grant_events
from src.corpus.blob_store import CorpusBlobStore
from src.corpus.derived_store import project_corpus
from src.corpus.registry import CorpusSourceRegistry
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_SCRIPT = REPO_ROOT / "src" / "integration" / "m6" / "mcp_server.py"

# marker -> (profile, project, knowledge space, memory_type)
UNITS = {
    "A": ("claude-code", None, "ks-shared", "persona"),
    "B": ("codex", None, "ks-shared", "workflow"),
    "C": ("claude-code", None, None, "persona"),
    "D": ("codex", None, None, "persona"),
    "E": (None, None, None, "fact"),
    "F": (None, None, "ks-shared", "fact"),
    "G": ("codex", None, "ks-other", "fact"),
    "H": ("claude-code", None, "ks-other", "fact"),
    "I": ("hermes", None, "ks-hermes-only", "fact"),
}


def marker_of(item: Dict[str, Any]) -> str:
    """``normalized_text`` is ``zebra marker-X`` -> ``X``."""
    return item["normalized_text"].rsplit("marker-", 1)[1].strip()


def markers(results: Iterable[Dict[str, Any]]) -> List[str]:
    return sorted(marker_of(item) for item in results)


def _add_read_grant(conn, grant_id: str, subject: str, space: str) -> None:
    grant_events.project_grant_event(
        conn,
        grant_events.AccessGrantEvent(
            grant_id=grant_id,
            subject_profile=subject,
            operation="READ",
            target_type="knowledge_space",
            target_id=space,
            op="create",
        ),
    )


def build_matrix_store(tmp_path: Path, *, grants: Optional[List[tuple]] = None) -> Path:
    """Project the A..I matrix and the given (grant_id, subject, space) grants.

    Default grants: claude-code and codex may READ ``ks-shared``.
    Returns the derived database path (closed, journal mode DELETE).
    """
    if grants is None:
        grants = [("g-cc-shared", "claude-code", "ks-shared"),
                  ("g-codex-shared", "codex", "ks-shared")]
    uid = uuid.uuid4().hex[:8]
    root = tmp_path / f"corpus_{uid}"
    root.mkdir(parents=True, exist_ok=True)
    registry = CorpusSourceRegistry(root=root)
    blobs = CorpusBlobStore(root=root)
    db_path = tmp_path / f"matrix_{uid}.sqlite"
    writer = SQLiteStore(SQLiteStoreConfig(path=db_path))
    writer.ensure_schema()
    writer._conn.execute("PRAGMA journal_mode=DELETE")
    for marker, (profile, project, space, memory_type) in UNITS.items():
        registry.register_source_with_blob(
            content=f"zebra marker-{marker}\n".encode("utf-8"),
            external_ref=f"mem://{memory_type}/{marker.lower()}",
            kind="txt",
            profile_id=profile,
            project_id=project,
            knowledge_space_id=space,
            custom_meta={"memory_type": memory_type},
            blob_store=blobs,
        )
    project_corpus(writer._conn, registry, blob_store=blobs)
    for grant_id, subject, space in grants:
        _add_read_grant(writer._conn, grant_id, subject, space)
    writer._conn.commit()
    writer.close()
    return db_path


def configure_inprocess(db_path: Path):
    """Configure the in-process MCP server on ``db_path`` (unpinned)."""
    from src.integration.m6 import mcp_server

    mcp_server.configure(db_path)
    return mcp_server


def call_tool(server_module, tool: str, arguments: Dict[str, Any], rid: int = 1) -> Dict[str, Any]:
    """In-process ``tools/call``; returns the JSON-RPC response dict."""
    return server_module._handle_rpc(
        "tools/call", {"name": tool, "arguments": arguments}, rid)


def envelope_of(resp: Dict[str, Any]) -> Dict[str, Any]:
    return resp["result"]["structuredContent"]


class StdioServer:
    """A real MCP server subprocess speaking newline-delimited JSON-RPC."""

    def __init__(self, args: List[str], *, cwd: Optional[Path] = None,
                 env: Optional[Dict[str, str]] = None, script: bool = False) -> None:
        base_env = {k: v for k, v in os.environ.items()
                    if not k.startswith("ZM_M6_") and k != "PYTHONPATH"}
        if env:
            base_env.update(env)
        if script:
            cmd = [sys.executable, str(SERVER_SCRIPT), *args]
            run_cwd = cwd
        else:
            cmd = [sys.executable, "-m", "src.integration.m6.mcp_server", *args]
            run_cwd = cwd or REPO_ROOT
            # ``-m`` resolves ``src`` from the working directory; make that explicit
            # when a different cwd is requested.
            if cwd is not None:
                base_env["PYTHONPATH"] = str(REPO_ROOT)
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, cwd=str(run_cwd) if run_cwd else None, env=base_env)
        self._next_id = 0
        self._stderr_cache: Optional[str] = None

    # -- protocol -----------------------------------------------------------
    def rpc(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self._next_id += 1
        msg: Dict[str, Any] = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            msg["params"] = params
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("server closed stdout; stderr=" + self.stderr_text())
        return json.loads(line)

    def initialize(self) -> Dict[str, Any]:
        return self.rpc("initialize", {})

    def tools_list(self) -> List[Dict[str, Any]]:
        return self.rpc("tools/list", {})["result"]["tools"]

    def call(self, tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return self.rpc("tools/call", {"name": tool, "arguments": arguments})

    # -- lifecycle ----------------------------------------------------------
    def stderr_text(self) -> str:
        if self.proc.poll() is None:
            return ""
        assert self.proc.stderr is not None
        return self.proc.stderr.read()

    def close(self) -> str:
        """Close stdin, wait, and return everything the server wrote to stderr (idempotent)."""
        if self._stderr_cache is not None:
            return self._stderr_cache
        try:
            if self.proc.stdin is not None:
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()
            self.proc.wait(timeout=5)
        err = ""
        if self.proc.stderr is not None:
            err = self.proc.stderr.read()
            self.proc.stderr.close()
        if self.proc.stdout is not None:
            self.proc.stdout.close()
        self._stderr_cache = err
        return err

    def __enter__(self) -> "StdioServer":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
