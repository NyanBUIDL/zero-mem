"""T21 - ``zero-mem share ... --memory NAME``: each named memory has its own share identity, peers, grants and audit."""
from __future__ import annotations

import contextlib
import io
import json

import pytest

pytest.importorskip("cryptography")

from zero_mem import cli  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch):
    for key in ("ZERO_MEM_MEMORY", "ZERO_MEM_CORPUS_ROOT", "ZERO_MEM_CONFIG_PATH", "ZERO_MEM_PROFILE", "ZERO_MEM_DATA_ROOT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ZERO_MEM_MEMORIES", str(tmp_path / "cfg" / "memories.toml"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg" / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg" / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg" / "cache"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    return tmp_path


def run(*argv, expect=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    if expect is not None:
        assert code == expect, (argv, code, out.getvalue(), err.getvalue())
    return code, out.getvalue(), err.getvalue()


def js(*argv):
    return json.loads(run(*argv, "--json", expect=0)[1])


@pytest.fixture
def two(env):
    run("memory", "create", "alice", expect=0)
    run("memory", "create", "bob", expect=0)
    run("settings", "set", "sharing.enabled", "true", expect=0)
    return env


def test_distinct_identities_per_memory(two):
    a = js("share", "invite", "--host", "127.0.0.1", "--memory", "alice")
    b = js("--memory", "bob", "share", "invite", "--host", "127.0.0.1")
    assert a["code"] != b["code"]
    sa = js("share", "status", "--memory", "alice")
    sb = js("share", "status", "--memory", "bob")
    assert sa["peer_id"] and sb["peer_id"] and sa["peer_id"] != sb["peer_id"]
    assert sa["fingerprint"] != sb["fingerprint"]
    assert js("share", "status", "--memory", "alice")["peer_id"] == sa["peer_id"]  # stable
    # the default memory has neither
    assert js("share", "status")["peer_id"] is None


def test_peers_grants_audit_are_isolated(two):
    from zero_mem import workspaces
    from zero_mem.share.node import ShareNode

    entry = workspaces.get_entry("alice")
    with workspaces.using_memory(entry.root, True), ShareNode.open(None, label="alice") as node:
        node.audit_event("peer_add", peer_id="p" + "0" * 15, label="x", fp="f" * 8, cert_der_b64="AA==", invite_id="i")
    assert js("share", "audit", "--memory", "alice")["events"]
    assert js("share", "audit", "--memory", "bob")["events"] == []
    assert js("share", "peers", "--memory", "bob")["peers"] == []
    assert js("share", "grants", "--memory", "bob")["grants"] == []


def test_unknown_memory_is_clean_error(two):
    code, _out, err = run("share", "status", "--memory", "nope")
    assert code == 5 and "nope" in err


def test_env_memory_selects_too(two, monkeypatch):
    monkeypatch.setenv("ZERO_MEM_MEMORY", "bob")
    js("share", "invite", "--host", "127.0.0.1")
    sb = js("share", "status")
    monkeypatch.setenv("ZERO_MEM_MEMORY", "alice")
    js("share", "invite", "--host", "127.0.0.1")
    assert sb["peer_id"] and js("share", "status")["peer_id"] not in (None, sb["peer_id"])
