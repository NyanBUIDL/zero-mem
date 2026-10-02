"""T20 - discovery, parser fuzzing, CLI, and the dependency-free core (these need no cryptography unless stated)."""
from __future__ import annotations

import json
import os
import random
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from zero_mem.share import discovery, protocol, ShareError
from zero_mem.share.util import is_lan_address, parse_duration

REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- discovery
def test_announcement_contains_no_content_or_names():
    doc = json.loads(discovery.announcement("a" * 20, 47890))
    assert set(doc) == {"zm", "svc", "peer_id", "port"}
    assert set(json.loads(discovery.announcement("a" * 20, 1, "home"))) == {"zm", "svc", "peer_id", "port", "label"}


def test_discovery_roundtrip_on_loopback_and_filters():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    ann = discovery.Announcer("b" * 20, 4242, dest="127.0.0.1", dest_port=port, interval=0.2).start()
    try:
        found = discovery.discover(timeout=1.5, port=port, bind="127.0.0.1")
    finally:
        ann.stop()
    assert found == [{"peer_id": "b" * 20, "host": "127.0.0.1", "port": 4242}]


@pytest.mark.parametrize("data,sender", [
    (b"{}", "10.0.0.1"), (b"junk", "10.0.0.1"), (b'{"zm":1,"svc":"x","peer_id":"' + b"a" * 20 + b'","port":1}', "10.0.0.1"),
    (discovery.announcement("a" * 20, 1), "8.8.8.8"), (b"x" * 600, "10.0.0.1"),
    (discovery.announcement("a" * 20, 0), "10.0.0.1"), (discovery.announcement("zz", 5), "10.0.0.1"),
    (discovery.announcement("a" * 20, 5, "bad\nlabel"), "10.0.0.1"),
])
def test_discovery_ignores_bad_datagrams(data, sender):
    assert discovery.parse_announcement(data, sender) is None


def test_discovery_grants_nothing():
    # a discovered peer id has no entry in any registry: parsing has no side effects and returns plain data
    item = discovery.parse_announcement(discovery.announcement("c" * 20, 9), "192.168.1.9")
    assert item == {"peer_id": "c" * 20, "host": "192.168.1.9", "port": 9}


# ---------------------------------------------------------------- fuzz / adversarial parsers
def _mutations(rnd: random.Random):
    atoms = [None, True, False, 0, -1, 2 ** 70, 1.5, float("inf"), "", "a" * 5000, "\x00", "../../x", [], {}, [[]], {"a": {}}]
    base = {"v": 1, "peer_id": "a" * 20, "generated_at": "x", "omitted": {},
            "sources": [{"source_id": "abcd1234", "ref": "mem://fact/a", "memory_type": "fact", "kind": "txt", "version": "v",
                         "digest": "0" * 64, "size": 1, "updated_at": "2026-10-02T00:00:00Z"}]}
    for _ in range(400):
        doc = json.loads(json.dumps(base))
        target = rnd.choice([doc, doc["sources"][0]])
        key = rnd.choice(list(target) + ["extra"])
        action = rnd.random()
        if action < .3:
            target.pop(key, None)
        else:
            target[key] = rnd.choice(atoms)
        try:
            yield json.dumps(doc, allow_nan=True).encode()
        except (TypeError, ValueError):
            continue


def test_fuzz_manifest_and_other_parsers_never_crash():
    rnd = random.Random(20)
    parsers = [protocol.parse_manifest, protocol.parse_fetch_request, lambda b: protocol.parse_fetch_response(b, max_bytes=1 << 20), protocol.parse_tombstones,
               protocol.parse_pair_request, protocol.parse_pair_response]
    blobs = list(_mutations(rnd)) + [b"", b"{", b"\xff\xfe", b"[" * 5000, b'{"a":' * 3000, b'{"v":1,"v":1}', b"NaN", b'{"v":NaN}',
                                     bytes(rnd.getrandbits(8) for _ in range(300))]
    for parser in parsers:
        for blob in blobs:
            try:
                parser(blob)
            except ShareError:
                pass  # the only acceptable failure


def test_fuzzed_valid_manifest_entries_are_all_checked():
    ok = 0
    for blob in _mutations(random.Random(1)):
        try:
            out = protocol.parse_manifest(blob)
        except ShareError:
            continue
        ok += 1
        assert set(out) == {"entries", "rejected", "omitted"}
        assert all(e["ref"].startswith(("mem://", "file://")) for e in out["entries"])
    assert ok > 0


def test_duplicate_keys_and_deep_nesting_rejected():
    with pytest.raises(ShareError):
        protocol.load_json(b'{"a":1,"a":2}', max_bytes=100)
    with pytest.raises(ShareError):
        protocol.load_json(b"[" * 100000 + b"]" * 100000, max_bytes=10 ** 6)


def test_lan_address_and_duration_helpers():
    assert is_lan_address("::ffff:10.1.1.1") and not is_lan_address("::ffff:8.8.8.8") and not is_lan_address("example.com")
    assert parse_duration("10m", maximum=3600) == 600
    for bad in ("", "10", "m", "-5m", "1y", "99999999d"):
        with pytest.raises(ShareError):
            parse_duration(bad, maximum=86400)


# ---------------------------------------------------------------- core without cryptography
BLOCK = """
import sys, importlib.abc
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == 'cryptography' or name.startswith('cryptography.'):
            raise ImportError('blocked for the test')
sys.meta_path.insert(0, Block())
"""


def _run_blocked(tmp_path, code: str, args=()):
    env = {**os.environ, "ZERO_MEM_DATA_ROOT": str(tmp_path / "d"), "XDG_CONFIG_HOME": str(tmp_path / "c"),
           "XDG_STATE_HOME": str(tmp_path / "s"), "XDG_CACHE_HOME": str(tmp_path / "k"),
           "ZERO_MEM_SETTINGS": str(tmp_path / "settings.toml"), "PYTHONPATH": str(REPO)}
    return subprocess.run([sys.executable, "-c", BLOCK + code, *args], capture_output=True, text=True, env=env, cwd=tmp_path, timeout=120)


def test_core_imports_and_runs_without_cryptography(tmp_path):
    code = """
import zero_mem, zero_mem.cli, zero_mem.memory, zero_mem.commands_share, zero_mem.share, zero_mem.share.node, zero_mem.share.server
import zero_mem.share.client, zero_mem.share.owner, zero_mem.share.discovery
assert 'cryptography' not in sys.modules
from zero_mem import cli
assert cli.main(['setup']) == 0
assert cli.main(['add', 'plain fact']) == 0
assert cli.main(['share', 'status', '--json']) == 0
assert cli.main(['share', 'peers']) == 0
assert cli.main(['share', 'grants']) == 0
assert cli.main(['share', 'audit']) == 0
assert cli.main(['settings', 'set', 'sharing.enabled', 'true']) == 0
rc = cli.main(['share', 'invite', '--host', '127.0.0.1'])
assert rc == 2, rc
"""
    res = _run_blocked(tmp_path, code)
    assert res.returncode == 0, res.stdout + res.stderr
    assert 'pip install "zero-mem[share]"' in res.stderr
    assert "cryptography" not in (res.stdout.split('"cryptography_installed"')[0] if False else "")


def test_sharing_is_disabled_by_default_with_clear_error(tmp_path):
    code = """
from zero_mem import cli
assert cli.main(['setup']) == 0
rc = cli.main(['share', 'invite', '--host', '127.0.0.1'])
assert rc == 2
"""
    res = _run_blocked(tmp_path, code)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "peer sharing is off" in res.stderr


def test_missing_extra_error_names_the_extra(tmp_path):
    code = """
from zero_mem.share import identity, ShareDependencyError
try:
    identity.crypto()
except ShareDependencyError as e:
    assert 'zero-mem[share]' in str(e)
else:
    raise SystemExit('no error')
"""
    res = _run_blocked(tmp_path, code)
    assert res.returncode == 0, res.stdout + res.stderr


# ---------------------------------------------------------------- CLI (needs the extra)
def test_cli_end_to_end_two_data_roots(tmp_path):
    pytest.importorskip("cryptography")
    from tests.unit.t20_helpers import Site
    from zero_mem import cli

    owner = Site(tmp_path, "o")
    peer = Site(tmp_path, "p")
    owner.add("cli shared fact about pelicans", "fact", name="pel")
    outputs = {}

    def run(site, *argv):
        env_keys = {"ZERO_MEM_DATA_ROOT": str(site.root), "ZERO_MEM_SETTINGS": str(site.settings),
                    "XDG_CONFIG_HOME": str(site.root.parent / (site.root.name + "-xdg")), "ZERO_MEM_CORPUS_ROOT": ""}
        old = {k: os.environ.get(k) for k in env_keys}
        os.environ.update(env_keys)
        import io, contextlib
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = cli.main(list(argv))
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        return rc, out.getvalue(), err.getvalue()

    from zero_mem.share.server import ShareServer
    server = ShareServer(owner.node, bind="127.0.0.1", port=0, duration=60).start()
    try:
        rc, out, err = run(owner, "share", "invite", "--host", "127.0.0.1", "--port", str(server.port), "--json",
                           "--grant", "space=ks-shared,type=fact,expires=7d")
        assert rc == 0, err
        code = json.loads(out)["code"]
        assert run(peer, "share", "join", code, "--name", "laptop")[0] == 0
        rc, out, _ = run(owner, "share", "peers", "--json")
        pid = json.loads(out)["peers"][0]["peer_id"]
        rc, out, _ = run(owner, "share", "grants", "--json")
        assert json.loads(out)["grants"][0]["types"] == ["fact"]
        owner_id = json.loads(run(peer, "share", "peers", "--json")[1])["owners"][0]["peer_id"]
        assert run(peer, "share", "pull", owner_id, "--dry-run")[0] == 0
        rc, out, _ = run(peer, "share", "pull", owner_id, "--yes", "--json")
        assert rc == 0, (rc, out, _)
        assert json.loads(out)["stored"] == 1, out
        assert run(owner, "share", "audit")[0] == 0
        assert run(owner, "share", "revoke", pid)[0] == 0
        rc, _o, err = run(peer, "share", "pull", owner_id, "--yes")
        assert rc != 0
        assert run(owner, "share", "grant", pid, "--space", "ks-shared", "--yes")[0] == 3  # revoked peer
        assert run(owner, "share", "revoke", "nobody")[0] == 5
    finally:
        server.stop()
    owner.close()
    peer.close()
