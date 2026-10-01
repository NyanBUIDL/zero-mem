"""Shared helpers for the T6b tests (MCP write/recall tools, per-agent config). Not collected: no ``test_`` prefix.

``McpProc`` drives a REAL stdio MCP server subprocess (newline-delimited JSON-RPC) with a reader thread, so a hung
server fails a test instead of hanging the suite. ``registration`` runs the real ``zero-mem mcp-config`` command in
process and returns what it prints, so the servers the e2e tests launch use EXACTLY the command/args/env a user would
paste into their agent's configuration.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import queue
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED = "ks-shared"
AGENTS = ("claude-code", "codex", "hermes", "openclaw")

# Built at runtime so this file never carries a literal credential.
SECRET_TOKEN = "sk-" + "ant-api03-" + "abcdefghijklmnopqrstuvwxyz0123456789"
SECRET_ENV = "password" + "=hunter2hunter2"

STATUS_ERRORS = {"DENIED", "REJECTED_SECRET", "REJECTED_CONTENT", "INVALID", "NOT_FOUND", "ERROR", "PARTIAL"}


def isolated_env(root: Path) -> Dict[str, str]:
    """The environment of a user whose zero-mem lives under ``root`` (nothing is read from or written to HOME)."""
    return {
        "ZERO_MEM_DATA_ROOT": str(root / "data"),
        "XDG_CONFIG_HOME": str(root / "xdg" / "config"),
        "XDG_STATE_HOME": str(root / "xdg" / "state"),
        "XDG_CACHE_HOME": str(root / "xdg" / "cache"),
    }


def apply_env(monkeypatch, root: Path) -> Dict[str, str]:
    env = isolated_env(root)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for key in ("ZERO_MEM_CORPUS_ROOT", "ZERO_MEM_PROFILE", "ZM_M6_PROFILE_ID", "ZM_M6_ENABLE_WRITE",
                "ZM_M6_ENABLE_MEMORY", "ZM_M6_ALLOW_ROOTS", "ZM_M6_STORE_PATH"):
        monkeypatch.delenv(key, raising=False)
    return env


def registration(agent: str, *extra: str) -> dict:
    """Run ``zero-mem mcp-config --agent <agent> --json ...`` in process; return the parsed output."""
    from zero_mem import cli

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(["mcp-config", "--agent", agent, "--json", *extra])
    assert code == 0, err.getvalue()
    return json.loads(out.getvalue())


class McpProc:
    """One real MCP server process: ``command args`` with ``env`` layered over a scrubbed environment."""

    def __init__(self, command: str, args: Sequence[str], env: Optional[Dict[str, str]] = None,
                 cwd: Optional[Path] = None, *, python_path: bool = True) -> None:
        base = {k: v for k, v in os.environ.items()
                if not k.startswith("ZM_M6_") and not k.startswith("ZERO_MEM_") and k != "PYTHONPATH"}
        if python_path:  # the repository is not pip-installed in the test venv
            base["PYTHONPATH"] = str(REPO_ROOT)
        base.update(env or {})
        self.proc = subprocess.Popen(
            [command, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, cwd=str(cwd) if cwd else None, env=base)
        self._lines: "queue.Queue[Optional[str]]" = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        self._next_id = 0
        self._stderr = ""

    def _pump(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def rpc(self, method: str, params: Optional[dict] = None, *, timeout: float = 90.0) -> dict:
        self._next_id += 1
        message: Dict[str, Any] = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            message["params"] = params
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            self.proc.kill()
            raise RuntimeError("MCP server did not answer within %ss" % timeout) from None
        if line is None:
            raise RuntimeError("MCP server closed stdout; stderr=" + self.close())
        reply = json.loads(line)
        assert reply["id"] == self._next_id
        return reply

    def initialize(self) -> dict:
        reply = self.rpc("initialize", {})
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.proc.stdin.flush()
        return reply["result"]

    def tools(self) -> List[dict]:
        return self.rpc("tools/list", {})["result"]["tools"]

    def tool_names(self) -> List[str]:
        return [t["name"] for t in self.tools()]

    def call_raw(self, tool: str, arguments: Optional[dict] = None) -> dict:
        return self.rpc("tools/call", {"name": tool, "arguments": arguments or {}})

    def call(self, tool: str, arguments: Optional[dict] = None) -> dict:
        """The tools/call ``result`` (``content``, ``structuredContent``, ``isError``)."""
        reply = self.call_raw(tool, arguments)
        assert "error" not in reply, reply
        return reply["result"]

    def env(self, tool: str, arguments: Optional[dict] = None) -> dict:
        """The structured envelope of a call; asserts ``isError`` agrees with the status."""
        result = self.call(tool, arguments)
        envelope = result["structuredContent"]
        failed = envelope["status"] in STATUS_ERRORS
        if not envelope.get("legacy"):
            assert result["isError"] is failed, (tool, envelope)
        return envelope

    def close(self) -> str:
        if self._stderr:
            return self._stderr
        try:
            if self.proc.stdin is not None:
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=15)
        except Exception:
            self.proc.kill()
            self.proc.wait(timeout=5)
        if self.proc.stderr is not None:
            self._stderr = self.proc.stderr.read() or " "
            self.proc.stderr.close()
        return self._stderr

    def __enter__(self) -> "McpProc":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def launch(reg: dict, cwd: Optional[Path] = None) -> McpProc:
    """Start the server exactly as the printed registration says."""
    proc = McpProc(reg["command"], reg["args"], reg["env"], cwd=cwd)
    proc.initialize()
    return proc


def grep_tree(root: Path, needle: str) -> List[Path]:
    """Every file below ``root`` whose BYTES contain ``needle`` (sqlite pages, WAL, jsonl, blobs)."""
    raw = needle.encode("utf-8")
    found = []
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            path = Path(dirpath) / name
            try:
                if raw in path.read_bytes():
                    found.append(path)
            except OSError:
                continue
    return found


def registry_lines(data_root: Path) -> List[dict]:
    path = data_root / "data" / "corpus" / "corpus_sources.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
