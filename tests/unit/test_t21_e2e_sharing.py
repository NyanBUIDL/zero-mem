"""T21 - end-to-end cross-memory sharing through the real CLI: two named memories ('alice' serves in a subprocess, 'bob' joins and
pulls), real TLS 1.3 on an ephemeral loopback port.

Needs the optional ``cryptography`` package (the ``test`` extra installs it)."""
from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import queue
import subprocess
import sys
import threading

import pytest

pytest.importorskip("cryptography")

from tests.unit.t6b_helpers import REPO_ROOT  # noqa: E402
from zero_mem import cli, workspaces  # noqa: E402
from zero_mem.memory import Memory  # noqa: E402
from zero_mem.memory_layout import Layout  # noqa: E402
from zero_mem.provisioning import Provisioner  # noqa: E402

TIMEOUT = 60


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
    monkeypatch.setenv("PYTHONUNBUFFERED", "1")
    return tmp_path


def run(*argv, expect=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    if expect is not None:
        assert code == expect, (argv, code, out.getvalue(), err.getvalue())
    return code, out.getvalue(), err.getvalue()


def js(*argv, expect=0):
    return json.loads(run(*argv, "--json", expect=expect)[1])


class Knowledge:
    """An agent profile that can write ks-shared in one named memory (stands in for the agent that fills alice)."""

    def __init__(self, name):
        self.root = workspaces.get_entry(name).root
        layout = Layout.resolve(self.root)
        prov = Provisioner(layout, operator="tester")
        prov.add_agent("claude")
        prov.grant_write("claude", space="ks-shared", basis="test")
        self.mem = Memory.open("claude", data_root=self.root)

    def add(self, text, mtype, name):
        res = self.mem._owner_add(text, mtype, name=name, scope="shared")
        assert res.status in ("created", "updated", "unchanged"), res
        return res

    def close(self):
        self.mem.close()


class Serve:
    """``zero-mem share serve`` as a real subprocess on an ephemeral loopback port."""

    def __init__(self, memory):
        code = "import sys; from zero_mem.cli import main; sys.exit(main(sys.argv[1:]))"
        self.proc = subprocess.Popen(
            [sys.executable, "-c", code, "share", "serve", "--memory", memory, "--bind", "127.0.0.1", "--port", "0",
             "--for", "10m", "--json"],
            cwd=str(REPO_ROOT), env=dict(os.environ), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        lines: queue.Queue = queue.Queue()
        threading.Thread(target=lambda: lines.put(self.proc.stdout.readline()), daemon=True).start()
        try:
            first = lines.get(timeout=TIMEOUT)
        except queue.Empty:
            self.stop()
            raise AssertionError("share serve did not start")
        if not first:
            err = self.proc.stderr.read()
            self.stop()
            raise AssertionError("share serve exited: " + err)
        self.port = int(json.loads(first)["listening"].rsplit(":", 1)[1])

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=15)
        for stream in (self.proc.stdout, self.proc.stderr):
            with contextlib.suppress(Exception):
                stream.close()


@pytest.fixture
def world(env):
    run("memory", "create", "alice", expect=0)
    run("memory", "create", "bob", expect=0)
    run("settings", "set", "sharing.enabled", "true", expect=0)
    know = Knowledge("alice")
    server = Serve("alice")
    yield env, know, server
    server.stop()
    know.close()


def bob_records():
    mem = Memory.open("operator", data_root=workspaces.get_entry("bob").root)
    try:
        registry, _b = mem._corpus()
        registry.refresh()
        return [r for r in registry.all_records() if r.external_ref.startswith("peer://")]
    finally:
        mem.close()


def test_two_named_memories_share_end_to_end(world):
    _env, know, server = world
    rule = know.add("Never deploy on Fridays without a rollback plan", "rule", "no-friday")
    know.add("Prefer boring technology for the data layer", "decision", "boring")
    know.add("The staging cluster orchid lives in region north", "file", "notes.txt")
    know.add("An unrelated fact that was never granted to bob", "fact", "ungranted")

    invite = js("share", "invite", "--memory", "alice", "--host", "127.0.0.1", "--port", str(server.port), "--label", "alice")
    joined = js("share", "join", invite["code"], "--memory", "bob", "--name", "bob")
    alice_id = js("share", "status", "--memory", "alice")["peer_id"]
    bob_id = js("share", "status", "--memory", "bob")["peer_id"]
    assert joined["owner_peer_id"] == alice_id and bob_id != alice_id

    # nothing is granted yet: bob can read nothing
    assert js("share", "pull", "alice", "--dry-run", "--memory", "bob")["plan"]["rows"] == []

    # alice grants ONLY rules under one ref prefix
    grant = js("share", "grant", bob_id, "--space", "ks-shared", "--type", "rule", "--ref-prefix", "mem://rule/no-",
               "--yes", "--memory", "alice")
    assert grant["now_readable"]["sources"] == 1
    plan = js("share", "pull", "alice", "--dry-run", "--memory", "bob")["plan"]
    assert [r["ref"] for r in plan["rows"]] == ["mem://rule/no-friday"]
    assert bob_records() == []  # a dry run imported nothing

    report = js("share", "pull", "alice", "--yes", "--memory", "bob")
    assert (report["stored"], report["proposed"], report["rejected"]) == (0, 1, [])
    assert bob_records() == []  # the rule is a PROPOSAL, not active memory
    bob = Memory.open("peer-import", data_root=workspaces.get_entry("bob").root)
    pending = bob.proposals("pending")
    bob.close()
    assert len(pending) == 1 and pending[0]["source"] == "peer" and pending[0]["text"].startswith("Never deploy")

    # the file only arrives once alice grants type=file
    js("share", "grant", bob_id, "--space", "ks-shared", "--type", "file", "--yes", "--memory", "alice")
    report = js("share", "pull", "alice", "--yes", "--memory", "bob")
    assert (report["stored"], report["proposed"]) == (1, 0)
    refs = [r.external_ref for r in bob_records()]
    assert refs == [f"peer://{alice_id}/file/notes.txt"]  # the ungranted fact and the decision never came

    # recall: only after import_into_recall AND a read grant of the quarantine space
    bob_root = workspaces.get_entry("bob").root
    prov = Provisioner(Layout.resolve(bob_root), operator="tester")
    prov.add_agent("coder")
    prov.grant_read("coder", space="ks-peer-" + alice_id)
    coder = Memory.open("coder", data_root=bob_root)
    try:
        assert coder.recall("orchid staging cluster").status == "empty"
        run("settings", "set", "sharing.import_into_recall", "true", expect=0)
        hit = coder.recall("orchid staging cluster")
        assert hit.status == "ok" and "untrusted reference" in hit.hits[0].text
        assert coder.recall("unrelated fact never granted").status == "empty"
    finally:
        coder.close()

    # alice forgets the file: the tombstone arrives on bob's next pull
    assert know.mem.forget(know.add("The staging cluster orchid lives in region north", "file", "notes.txt").source_id).status \
        == "forgotten"
    report = js("share", "pull", "alice", "--yes", "--memory", "bob")
    assert report["tombstoned"] == 1

    # ... and a forgotten rule withdraws bob's pending proposal
    assert know.mem.forget(rule.source_id).status == "forgotten"
    report = js("share", "pull", "alice", "--yes", "--memory", "bob")
    assert report["withdrawn"] == 1
    # revoke: the next pull fails
    js("share", "revoke", bob_id, "--memory", "alice")
    code, _out, err = run("share", "pull", "alice", "--yes", "--memory", "bob")
    assert code != 0 and err.strip()
    audit = js("share", "audit", "--memory", "alice")["events"]
    assert {"invite_create", "peer_add", "grant_create", "peer_revoke"} <= {e["op"] for e in audit}


def test_invite_failures_are_clean_and_leak_nothing(world):
    _env, _know, server = world
    invite = js("share", "invite", "--memory", "alice", "--host", "127.0.0.1", "--port", str(server.port))
    code = invite["code"]
    body = code.split(":", 1)[1]
    assert code.startswith("zm1:")
    secret_parts = [body[i:i + 24] for i in range(8, len(body) - 24, 24)]

    def check(argv, *, memory="bob"):
        rc, out, err = run("share", "join", *argv, "--memory", memory)
        assert rc != 0, (argv, out, err)
        assert "Traceback" not in err and "unexpected error" not in err, err
        assert err.strip(), "a clear message is required"
        text = out + err
        assert not any(part in text for part in secret_parts), "the invite leaked into the output"
        return err

    check([code[:-12]])                         # truncated
    check([code[: len(code) // 2]])             # cut in half
    check([code[:20] + "!" + code[21:]])        # a character outside the alphabet
    doc = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))

    def retype(field):                          # one mistyped character inside one field, re-encoded
        bad = dict(doc)
        bad[field] = bad[field][:-1] + ("A" if bad[field][-1] != "A" else "B")
        raw = json.dumps(bad, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return "zm1:" + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    check([retype("token")])                    # wrong token: refused by the owner
    check([retype("server_fp")])                # wrong pin: the certificate does not match
    check(["zm1:" + "x" * 40])                  # garbage with the right prefix
    check(["hello"])                            # not an invite at all
    check([""])                                 # empty
    check([code.replace("zm1:", "zm2:", 1)])    # wrong version
    assert js("share", "peers", "--memory", "bob")["owners"] == []
    assert js("share", "peers", "--memory", "alice")["peers"] == []   # nothing was paired by any failure

    # the good invite still works once ...
    js("share", "join", code, "--memory", "bob", "--name", "bob")
    # ... and then is spent: another memory pasting it again is refused
    run("memory", "create", "carol", expect=0)
    err = check([code], memory="carol")
    assert "refused" in err.lower() or "invite" in err.lower()
    assert len(js("share", "peers", "--memory", "alice")["peers"]) == 1


def test_join_into_a_memory_with_sharing_off_is_refused_clearly(world, monkeypatch):
    _env, _know, server = world
    invite = js("share", "invite", "--memory", "alice", "--host", "127.0.0.1", "--port", str(server.port))
    run("settings", "set", "sharing.enabled", "false", expect=0)
    rc, _out, err = run("share", "join", invite["code"], "--memory", "bob")
    assert rc == 2 and "sharing is off" in err
