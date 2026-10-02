"""T22 findings 4a/4b - invite code off the command line; `share identity rotate`."""
from __future__ import annotations

import contextlib
import io
import json
import os

import pytest

pytest.importorskip("cryptography")

from tests.unit.t20_helpers import Site  # noqa: E402
from zero_mem import cli  # noqa: E402
from zero_mem.share.server import ShareServer  # noqa: E402


def run(site, *argv, stdin=None, monkeypatch=None):
    env_keys = {"ZERO_MEM_DATA_ROOT": str(site.root), "ZERO_MEM_SETTINGS": str(site.settings),
                "XDG_CONFIG_HOME": str(site.root.parent / (site.root.name + "-xdg")), "ZERO_MEM_CORPUS_ROOT": ""}
    old = {k: os.environ.get(k) for k in env_keys}
    os.environ.update(env_keys)
    out, err = io.StringIO(), io.StringIO()
    old_stdin = __import__("sys").stdin
    if stdin is not None:
        __import__("sys").stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(list(argv))
    finally:
        __import__("sys").stdin = old_stdin
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return rc, out.getvalue(), err.getvalue()


@pytest.fixture
def world(tmp_path):
    owner, peer = Site(tmp_path, "o"), Site(tmp_path, "p")
    server = ShareServer(owner.node, bind="127.0.0.1", port=0, duration=60).start()
    yield owner, peer, server, tmp_path
    server.stop()
    owner.close()
    peer.close()


def _invite(owner, server):
    rc, out, err = run(owner, "share", "invite", "--host", "127.0.0.1", "--port", str(server.port), "--json")
    assert rc == 0, err
    return json.loads(out)["code"]


def test_join_from_a_code_file_and_from_stdin_do_not_warn(world):
    owner, peer, server, tmp = world
    code_file = tmp / "invite.txt"
    code_file.write_text(_invite(owner, server) + "\n", encoding="utf-8")
    rc, out, err = run(peer, "share", "join", "--code-file", str(code_file), "--name", "p1")
    assert rc == 0, err
    assert "warning" not in err.lower()
    rc, out, err = run(peer, "share", "join", "-", "--name", "p2", stdin=_invite(owner, server) + "\n")
    assert rc == 0, err
    assert "warning" not in err.lower()


def test_positional_code_still_works_but_warns_without_echoing_the_code(world):
    owner, peer, server, _tmp = world
    code = _invite(owner, server)
    rc, out, err = run(peer, "share", "join", code, "--name", "p")
    assert rc == 0, err
    assert "warning" in err.lower() and "--code-file" in err
    assert code not in out + err


@pytest.mark.parametrize("argv", [[], ["zm1:x", "--code-file", "x"], ["--code-file", "does-not-exist.txt"]])
def test_join_code_source_errors_are_clean(world, argv):
    _owner, peer, _server, _tmp = world
    rc, out, err = run(peer, "share", "join", *argv)
    assert rc == 2 and err.strip() and "Traceback" not in err


def test_join_with_empty_file_or_stdin_is_a_clean_error(world):
    _owner, peer, _server, tmp = world
    empty = tmp / "empty.txt"
    empty.write_text("  \n", encoding="utf-8")
    assert run(peer, "share", "join", "--code-file", str(empty))[0] == 2
    assert run(peer, "share", "join", "-", stdin="")[0] == 2


def test_identity_rotate_ends_every_pairing_and_is_audited(world):
    owner, peer, server, _tmp = world
    code = _invite(owner, server)
    assert run(peer, "share", "join", "-", stdin=code)[0] == 0
    open_code = _invite(owner, server)  # an open invite must be burned
    old_owner = owner.node.identity()
    old_peer_id = old_owner.peer_id
    key_before = old_owner.key_path.read_bytes()
    rc, out, err = run(owner, "share", "identity", "rotate", "--yes", "--json")
    assert rc == 0, err
    doc = json.loads(out)
    assert doc["old_peer_id"] == old_peer_id and doc["new_peer_id"] != old_peer_id
    assert doc["peers_revoked"] == 1 and doc["invites_burned"] == 1
    # new files on disk; status shows the new id
    rc, out, _ = run(owner, "share", "status", "--json")
    assert json.loads(out)["peer_id"] == doc["new_peer_id"]
    assert (owner.root / "share" / "identity.key").read_bytes() != key_before
    # the paired peer is revoked on the owner
    peers = json.loads(run(owner, "share", "peers", "--json")[1])["peers"]
    assert [p["status"] for p in peers] == ["revoked"]
    audit = json.loads(run(owner, "share", "audit", "--json")[1])["events"]
    rot = [e for e in audit if e["op"] == "identity_rotate"]
    assert len(rot) == 1 and rot[0]["old_peer_id"] == old_peer_id and rot[0]["new_peer_id"] == doc["new_peer_id"]
    assert "BEGIN" not in json.dumps(audit)
    # an old invite no longer redeems and the peer cannot pull from the (restartable) owner under the old pin
    assert run(peer, "share", "join", "-", stdin=open_code)[0] != 0


def test_identity_rotate_on_the_joiner_forgets_owners_and_needs_confirmation(world):
    owner, peer, server, _tmp = world
    assert run(peer, "share", "join", "-", stdin=_invite(owner, server))[0] == 0
    assert len(json.loads(run(peer, "share", "peers", "--json")[1])["owners"]) == 1
    rc, _out, err = run(peer, "share", "identity", "rotate")  # no --yes and no terminal: refused, nothing changes
    assert rc == 2 and "--yes" in err
    assert len(json.loads(run(peer, "share", "peers", "--json")[1])["owners"]) == 1
    before = peer.node.identity().peer_id
    assert run(peer, "share", "identity", "rotate", "--yes")[0] == 0
    assert json.loads(run(peer, "share", "peers", "--json")[1])["owners"] == []
    assert json.loads(run(peer, "share", "status", "--json")[1])["peer_id"] != before


def test_identity_rotate_without_an_identity_is_a_clean_error(tmp_path):
    site = Site(tmp_path, "fresh")
    try:
        rc, _out, err = run(site, "share", "identity", "rotate", "--yes")
        assert rc != 0 and "no sharing identity" in err and "Traceback" not in err
    finally:
        site.close()


def test_a_rotated_owner_cannot_be_pulled_with_the_old_pin_then_repairs(world):
    owner, peer, server, _tmp = world
    assert run(peer, "share", "join", "-", stdin=_invite(owner, server))[0] == 0
    owner_id = json.loads(run(peer, "share", "peers", "--json")[1])["owners"][0]["peer_id"]
    assert run(owner, "share", "identity", "rotate", "--yes")[0] == 0
    server.stop()
    from zero_mem.share.node import ShareNode

    fresh = ShareNode.open(owner.root, settings_path=owner.settings, label="o")  # a restarted `share serve`
    server2 = ShareServer(fresh, bind="127.0.0.1", port=0, duration=60).start()
    try:
        rc, _o, err = run(peer, "share", "pull", owner_id, "--yes")
        assert rc != 0 and "Traceback" not in err  # pinned certificate no longer matches
        # re-pair: new invite, join again (the peer removes the stale owner first)
        assert run(peer, "share", "unpair", owner_id)[0] == 0
        rc, out, err = run(owner, "share", "invite", "--host", "127.0.0.1", "--port", str(server2.port), "--json")
        rc, _o, err = run(peer, "share", "join", "-", stdin=json.loads(out)["code"])
        assert rc == 0, err
    finally:
        server2.stop()
        fresh.close()
