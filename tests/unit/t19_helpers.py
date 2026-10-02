"""Helpers for the T19 control-panel tests: a real server on an ephemeral loopback port driven with http.client."""
from __future__ import annotations

import http.client
import re
import threading
from typing import Optional
from urllib.parse import urlencode

from zero_mem.ui import create_server

XSS = '"><script>alert(1)</script><img src=x onerror=alert(2)>&amp;\'`'


class Client:
    """``cookie=False`` means an anonymous client: it has no path secret, so every request is sent unprefixed."""

    def __init__(self, server, *, cookie: bool = True) -> None:
        self.server = server
        self.host = "127.0.0.1"
        self.port = server.port
        self.prefix: str = server.prefix if cookie else ""
        self.csrf: Optional[str] = None

    # -- raw ---------------------------------------------------------------------------------------
    def raw(self, method: str, path: str, body: Optional[bytes] = None, headers: Optional[dict] = None,
            *, host_header: Optional[str] = ..., timeout: float = 30.0):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        hdrs = dict(headers or {})
        if self.prefix and path.startswith("/") and not path.startswith(self.prefix + "/") and path != self.prefix:
            path = self.prefix + path
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        if host_header is ...:
            host_header = f"127.0.0.1:{self.port}"
        if host_header is not None:
            conn.putheader("Host", host_header)
        for key, value in hdrs.items():
            conn.putheader(key, value)
        if body is not None and "Content-Length" not in hdrs:
            conn.putheader("Content-Length", str(len(body)))
        conn.endheaders(body)
        resp = conn.getresponse()
        data = resp.read()
        out = (resp.status, {k.lower(): v for k, v in resp.getheaders()}, data.decode("utf-8", "replace"))
        conn.close()
        return out

    def _auth(self, extra: Optional[dict] = None) -> dict:
        return dict(extra or {})  # no cookie exists: authority is the path prefix only

    # -- convenience ---------------------------------------------------------------------------------
    def get(self, path: str, **kw):
        return self.raw("GET", path, headers=self._auth(kw.pop("headers", None)), **kw)

    def page(self, path: str) -> str:
        status, _h, body = self.get(path)
        assert status == 200, (path, status, body[:300])
        return body

    def token(self, path: str = "/add") -> str:
        body = self.page(path)
        return re.search(r'name="csrf" value="([^"]+)"', body).group(1)

    def post(self, path: str, fields: dict, *, csrf: Optional[str] = ..., origin: Optional[str] = ..., headers=None,
             follow: bool = True, lists: Optional[list] = None):
        data = dict(fields)
        if csrf is ...:
            csrf = self.server.csrf_token
        if csrf is not None:
            data["csrf"] = csrf
        pairs = list(data.items()) + list(lists or [])
        body = urlencode(pairs).encode("utf-8")
        hdrs = {"Content-Type": "application/x-www-form-urlencoded"}
        if origin is ...:
            origin = f"http://127.0.0.1:{self.port}"
        if origin is not None:
            hdrs["Origin"] = origin
        hdrs.update(headers or {})
        status, rh, text = self.raw("POST", path, body, self._auth(hdrs))
        if follow and status == 303:
            return self.get(rh["location"])
        return status, rh, text

    def multipart(self, path: str, fields: dict, filename: Optional[str], content: bytes = b"", *, file_field: str = "file",
                  origin: Optional[str] = ..., boundary: str = "----zmtestboundary", raw_disposition: Optional[str] = None):
        data = dict(fields)
        data["csrf"] = self.server.csrf_token
        parts = []
        for key, value in data.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode("utf-8"))
        if filename is not None:
            disp = raw_disposition or f'form-data; name="{file_field}"; filename="{filename}"'
            parts.append(f"--{boundary}\r\nContent-Disposition: {disp}\r\nContent-Type: application/octet-stream\r\n\r\n".encode("utf-8")
                         + content + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)
        hdrs = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        if origin is ...:
            origin = f"http://127.0.0.1:{self.port}"
        if origin is not None:
            hdrs["Origin"] = origin
        status, rh, text = self.raw("POST", path, body, self._auth(hdrs))
        if status == 303:
            return self.get(rh["location"])
        return status, rh, text


def start(layout=None, **kw):
    server = create_server(layout=layout, **kw)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, thread


def stop(server, thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(5)


# ---------------------------------------------------------------------------------------------------------
import pytest

from tests.unit.t6b_helpers import SECRET_TOKEN, apply_env  # noqa: E402
from zero_mem import cli  # noqa: E402
from zero_mem.memory import Memory  # noqa: E402
from zero_mem.memory_layout import Layout  # noqa: E402


class _NoTty:
    def isatty(self):
        return False

    def read(self, *_a):
        return ""


@pytest.fixture
def env(tmp_path, monkeypatch):
    apply_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ZERO_MEM_SETTINGS", str(tmp_path / "cfg" / "settings.toml"))
    monkeypatch.setattr("sys.stdin", _NoTty())
    assert cli.main(["setup"]) == 0
    return tmp_path


@pytest.fixture
def layout(env):
    return Layout.resolve(None)


def populate(env_path=None) -> dict:
    """A realistic store: an agent with write access, a shared rule, a private fact, pending and decided proposals."""
    assert cli.main(["agents", "add", "codex"]) == 0
    assert cli.main(["agents", "grant-write", "codex", "--space", "ks-shared", "--yes"]) == 0
    assert cli.main(["--profile", "codex", "add", "Never force push to main.", "--type", "rule", "--scope", "shared",
                     "--name", "nofp"]) == 0
    assert cli.main(["--profile", "codex", "add", "Alice prefers PostgreSQL.", "--scope", "private"]) == 0
    with Memory.open("codex", channel="test") as mem:
        pending = mem.propose("Run the linter before every commit.", "rule", name="lint", evidence=["PR #12", "review comment"])
        other = mem.propose("Retry when sqlite is busy.", "gotcha", name="busy", scope="shared")
    return {"pending": pending.proposal_id, "other": other.proposal_id}


@pytest.fixture
def populated(env):
    return populate()


@pytest.fixture
def panel(env):
    server, thread = start(profile="codex")
    try:
        yield Client(server)
    finally:
        stop(server, thread)


@pytest.fixture
def ppanel(populated, env):
    server, thread = start(profile="codex")
    try:
        client = Client(server)
        client.ids = populated
        yield client
    finally:
        stop(server, thread)


def state_fingerprint(layout) -> tuple:
    import os

    out = []
    for path in (layout.memory_stream, layout.corpus_root / "corpus_sources.jsonl"):
        out.append(os.stat(path).st_size if path.exists() else -1)
    settings = os.environ.get("ZERO_MEM_SETTINGS")
    out.append(os.path.getsize(settings) if settings and os.path.exists(settings) else -1)
    return tuple(out)


ROUTES = ["/", "/inbox", "/add", "/ingest", "/search", "/brief", "/agents", "/settings", "/eval", "/audit", "/sharing"]
