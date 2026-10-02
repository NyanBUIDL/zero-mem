"""T20 - pairing and transport attacks over real TLS on loopback (needs the optional cryptography extra)."""
from __future__ import annotations

import base64
import json
import socket
import ssl
import threading
import time

import pytest

pytest.importorskip("cryptography")

from tests.unit.t20_helpers import Site, foreign_identity, http, pair, raw_tls  # noqa: E402
from zero_mem.share import SNI_PAIR, ShareError, client, events as ev, tls  # noqa: E402
from zero_mem.share.server import ShareServer, check_bind  # noqa: E402


@pytest.fixture
def sites(tmp_path):
    owner, peer = Site(tmp_path, "owner"), Site(tmp_path, "peer")
    owner.add("alpha fact one", name="a1")
    yield owner, peer
    owner.close()
    peer.close()


@pytest.fixture
def served(sites):
    owner, peer = sites
    server = ShareServer(owner.node, bind="127.0.0.1", port=0, duration=60).start()
    yield owner, peer, server
    server.stop()


def invite_for(owner, server, grants=None, expires=600):
    return owner.node.create_invite(host="127.0.0.1", port=server.port, expires_in=expires, grants=grants or [])


def ops(site):
    return [e["op"] for e in site.node.audit(500)]


def test_pairing_happy_path_and_default_deny(served):
    owner, peer, server = served
    res = client.join(peer.node, invite_for(owner, server).encode(), "peer")
    assert res["status"] == "joined" and res["owner_peer_id"] == owner.node.identity().peer_id
    peers = owner.node.peers()
    assert len(peers) == 1 and peers[0]["active_grants"] == 0 and peers[0]["peer_id"] == peer.node.identity().peer_id
    plan = client.pull(peer.node, "owner", dry_run=True).plan
    assert plan["rows"] == []  # nothing granted: nothing offered


def test_wrong_fingerprint_aborts_before_token_is_sent(served, tmp_path):
    owner, peer, server = served
    inv = invite_for(owner, server)
    from zero_mem.share.invite import Invite, parse_invite
    good = parse_invite(inv.encode())
    mitm = Invite(good.host, good.port, "00" * 32, good.token, good.expires, good.label)
    with pytest.raises(ShareError) as exc:
        client.join(peer.node, mitm.encode(), "peer")
    assert exc.value.code == "pin_mismatch"
    assert owner.node.peers() == []
    # the token was never presented: the invite is still redeemable
    client.join(peer.node, inv.encode(), "peer")
    assert len(owner.node.peers()) == 1


def test_simulated_mitm_with_other_certificate(sites, tmp_path):
    owner, peer = sites
    inv = owner.node.create_invite(host="127.0.0.1", port=1, grants=[])
    stranger = Site(tmp_path, "mitm")
    seen = []
    srv = ShareServer(stranger.node, bind="127.0.0.1", port=0, duration=30).start()
    from zero_mem.share.invite import Invite, parse_invite
    g = parse_invite(inv.encode())
    # attacker listens where the invite points, with its own certificate
    forged = Invite(g.host, srv.port, g.server_fp, g.token, g.expires, g.label)
    with pytest.raises(ShareError) as exc:
        client.join(peer.node, forged.encode(), "peer")
    assert exc.value.code == "pin_mismatch"
    assert "pair_attempt" not in ops(stranger)  # no token ever reached the attacker's endpoint
    srv.stop()
    stranger.close()


def test_replayed_token_refused(served):
    owner, peer, server = served
    inv = invite_for(owner, server)
    client.join(peer.node, inv.encode(), "peer")
    other = Site(owner.root.parent, "second")
    with pytest.raises(ShareError) as exc:
        client.join(other.node, inv.encode(), "second")
    assert exc.value.code == "pairing_refused"
    assert any(e["op"] == "pair_attempt" and e.get("reason") == "used" for e in owner.node.audit(100))
    other.close()


def test_wrong_and_expired_token_refused_and_audited_without_token(served):
    owner, peer, server = served
    inv = invite_for(owner, server)
    from zero_mem.share.invite import Invite, parse_invite
    g = parse_invite(inv.encode())
    bad = Invite(g.host, g.port, g.server_fp, base64.urlsafe_b64encode(b"q" * 32).decode().rstrip("="), g.expires, g.label)
    with pytest.raises(ShareError):
        client.join(peer.node, bad.encode(), "peer")
    short = invite_for(owner, server, expires=1)
    time.sleep(2.2)
    with pytest.raises(ShareError):
        client.join(peer.node, short.encode(), "peer")  # joiner-side expiry check
    audit = json.dumps(owner.node.audit(500))
    assert g.token not in audit and bad.token not in audit
    assert any(e.get("reason") == "unknown" for e in owner.node.audit(100))


def test_server_side_expiry(served):
    owner, peer, server = served
    inv = invite_for(owner, server, expires=1)
    from zero_mem.share.invite import parse_invite
    g = parse_invite(inv.encode())
    time.sleep(2.2)
    # bypass the joiner-side check: talk to the endpoint directly
    s = tls.connect_pinned("127.0.0.1", server.port, g.server_fp, identity=peer.node.identity(), sni=SNI_PAIR)
    from zero_mem.share import httpio, protocol
    body = protocol.dump_json({"v": 1, "token": g.token, "label": "peer", "cert_der_b64": base64.b64encode(peer.node.identity().cert_der).decode()})
    status, _ = httpio.request(s, "POST", "/v1/pair", body, max_response=4096)
    s.close()
    assert status == 403
    assert any(e.get("reason") == "expired" for e in owner.node.audit(100))


def test_bruteforce_lockout_burns_open_invites_and_is_audited(served):
    owner, peer, server = served
    inv = invite_for(owner, server)
    from zero_mem.share.invite import parse_invite
    g = parse_invite(inv.encode())
    from zero_mem.share import httpio, protocol
    cert = base64.b64encode(peer.node.identity().cert_der).decode()
    statuses = []
    for i in range(8):
        s = tls.connect_pinned("127.0.0.1", server.port, g.server_fp, identity=peer.node.identity(), sni=SNI_PAIR)
        tok = base64.urlsafe_b64encode(bytes([i]) * 32).decode().rstrip("=")
        st, _ = httpio.request(s, "POST", "/v1/pair", protocol.dump_json({"v": 1, "token": tok, "label": "p", "cert_der_b64": cert}), max_response=4096)
        s.close()
        statuses.append(st)
    assert statuses[:5] == [403] * 5 and 429 in statuses[5:]
    with pytest.raises(ShareError):  # the real token no longer works: the invite was burned
        client.join(peer.node, inv.encode(), "peer")
    assert "pair_lockout" in ops(owner)
    assert owner.node.peers() == []


def test_unknown_client_certificate_refused_after_pairing(served, tmp_path):
    owner, peer, server = served
    client.join(peer.node, invite_for(owner, server).encode(), "peer")
    stranger = foreign_identity(tmp_path)
    refused = False
    try:
        s = raw_tls(server.port, cert=stranger)
        status, _ = http(s)
        refused = status == 0
    except (ssl.SSLError, OSError):
        refused = True
    assert refused
    try:
        s = raw_tls(server.port)  # no certificate at all
        assert http(s)[0] == 0
    except (ssl.SSLError, OSError):
        pass


def test_revoked_peer_refused_immediately(served):
    owner, peer, server = served
    client.join(peer.node, invite_for(owner, server, grants=[{"space": "ks-shared"}]).encode(), "peer")
    assert client.pull(peer.node, "owner", dry_run=True).plan["rows"]
    owner.node.revoke_peer(peer.node.identity().peer_id)
    with pytest.raises(ShareError) as exc:
        client.pull(peer.node, "owner", dry_run=True)
    assert exc.value.code in ("connect_failed", "access_revoked", "connection_failed")
    assert any(e["op"] == "peer_revoke" for e in owner.node.audit(100))


def test_tls_below_13_refused(served):
    owner, peer, server = served
    with pytest.raises((ssl.SSLError, OSError)):
        raw_tls(server.port, maximum=ssl.TLSVersion.TLSv1_2, sni=SNI_PAIR)


def test_plain_http_and_garbage_clients_refused(served):
    owner, peer, server = served
    for payload in (b"GET /v1/manifest HTTP/1.1\r\nHost: x\r\n\r\n", b"\x00\x01garbage" * 10, b""):
        s = socket.create_connection(("127.0.0.1", server.port), timeout=5)
        s.sendall(payload)
        s.settimeout(6)
        try:
            data = s.recv(1024)
        except (OSError, socket.timeout):
            data = b""
        s.close()
        assert b"200 OK" not in data and b"alpha" not in data
    assert owner.node.peers() == []


def test_non_private_bind_refused(sites):
    owner, _ = sites
    for addr in ("0.0.0.0", "::", "8.8.8.8", "1.2.3.4"):
        with pytest.raises(ShareError) as exc:
            ShareServer(owner.node, bind=addr, port=0)
        assert exc.value.code == "public_bind_refused"
    with pytest.raises(ShareError):  # setting alone is not enough
        owner.set_settings("[sharing]\nenabled = true\nallow_public_bind = true\n")
        ShareServer(owner.node, bind="0.0.0.0", port=0)
    owner.set_settings("[sharing]\nenabled = true\n")
    with pytest.raises(ShareError):  # flag alone is not enough
        ShareServer(owner.node, bind="0.0.0.0", port=0, i_know_public=True)


def test_bind_policy_function():
    for ok in ("127.0.0.1", "10.1.2.3", "172.16.0.9", "192.168.0.4", "169.254.1.1", "::1", "fe80::1", "fd12::1"):
        assert check_bind(ok, allow_public_bind=False, i_know_public=False) == ok
    for bad in ("172.32.0.1", "100.64.0.1", "2001:db8::1", "::ffff:8.8.8.8", "localhost", ""):
        with pytest.raises(ShareError):
            check_bind(bad, allow_public_bind=False, i_know_public=False)
    assert check_bind("0.0.0.0", allow_public_bind=True, i_know_public=True) == "0.0.0.0"


def test_no_write_endpoint_and_closed_routes(served):
    owner, peer, server = served
    client.join(peer.node, invite_for(owner, server, grants=[{"space": "ks-shared"}]).encode(), "peer")
    ident = peer.node.identity()
    for method in ("PUT", "DELETE", "PATCH", "POST", "OPTIONS", "TRACE", "HEAD"):
        for path in ("/v1/manifest", "/v1/tombstones", "/v1/sources", "/v1/write", "/v1/add", "/", "/v1/pair"):
            s = tls.connect_pinned("127.0.0.1", server.port, owner.node.identity().fingerprint, identity=ident)
            status, _ = http(s, method, path, b"{}" if method == "POST" else b"")
            s.close()
            assert status in (400, 404, 405, 411), (method, path, status)
    s = tls.connect_pinned("127.0.0.1", server.port, owner.node.identity().fingerprint, identity=ident)
    assert http(s, "GET", "/v1/fetch")[0] == 405
    s.close()


def test_request_size_and_framing_limits(served):
    owner, peer, server = served
    client.join(peer.node, invite_for(owner, server, grants=[{"space": "ks-shared"}]).encode(), "peer")
    fp, ident = owner.node.identity().fingerprint, peer.node.identity()

    def go(method, path, body=b"", headers=""):
        s = tls.connect_pinned("127.0.0.1", server.port, fp, identity=ident)
        try:
            return http(s, method, path, body, headers)[0]
        finally:
            s.close()
    assert go("POST", "/v1/fetch", b"x" * (70 * 1024)) == 413
    assert go("GET", "/v1/manifest", headers="X-Big: " + "a" * 9000 + "\r\n") == 431
    assert go("GET", "/v1/manifest", headers="Transfer-Encoding: chunked\r\n") == 501
    assert go("POST", "/v1/fetch", b'{"v":1,"source_ids":["a"]}garbage', headers="") in (400, 404)
    assert go("GET", "/v1/manifest?" + "a" * 600) == 400


def test_slowloris_connection_is_dropped(sites, monkeypatch):
    owner, peer = sites
    from zero_mem.share import server as srv_mod
    monkeypatch.setattr(srv_mod, "REQUEST_SECONDS", 1.5)
    monkeypatch.setattr(srv_mod, "HELLO_SECONDS", 1.5)
    server = ShareServer(owner.node, bind="127.0.0.1", port=0, duration=30).start()
    try:
        client.join(peer.node, invite_for(owner, server, grants=[{"space": "ks-shared"}]).encode(), "peer")
        s = tls.connect_pinned("127.0.0.1", server.port, owner.node.identity().fingerprint, identity=peer.node.identity())
        s.sendall(b"GET /v1/manifest HTTP/1.1\r\n")  # never finishes the header block
        s.settimeout(6)
        started = time.monotonic()
        data = s.recv(4096)
        assert b"408" in data or data == b""
        assert time.monotonic() - started < 5
        s.close()
        # a half-open TCP connection that never sends a ClientHello does not block the server
        dead = socket.create_connection(("127.0.0.1", server.port))
        assert client.pull(peer.node, "owner", dry_run=True) is not None
        dead.close()
    finally:
        server.stop()


def test_concurrent_pulls(served):
    owner, peer, server = served
    client.join(peer.node, invite_for(owner, server, grants=[{"space": "ks-shared"}]).encode(), "peer")
    errors, rows = [], []

    def run():
        try:
            rows.append(len(client.pull(peer.node, "owner", dry_run=True).plan["rows"]))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
    threads = [threading.Thread(target=run) for _ in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and rows == [1] * 10


def test_connection_cap_and_rate_limit(served, monkeypatch):
    owner, peer, server = served
    client.join(peer.node, invite_for(owner, server, grants=[{"space": "ks-shared"}]).encode(), "peer")
    from zero_mem.share import server as srv_mod
    monkeypatch.setattr(srv_mod, "PEER_RATE_PER_MINUTE", 3)
    codes = []
    for _ in range(5):
        try:
            client.pull(peer.node, "owner", dry_run=True)
            codes.append("ok")
        except ShareError as exc:
            codes.append(exc.code)
    assert "rate_limited" in codes


def test_sharing_disabled_or_kill_switch_stops_serving_and_pairing(served):
    owner, peer, server = served
    inv = invite_for(owner, server)
    owner.set_settings("[sharing]\nenabled = true\n[safety]\nkill_switch = true\n")
    with pytest.raises(ShareError) as exc:
        client.join(peer.node, inv.encode(), "peer")
    assert exc.value.code in ("sharing_disabled", "pairing_refused", "connect_failed")
    assert owner.node.peers() == []
    with pytest.raises(ShareError):
        ShareServer(owner.node, bind="127.0.0.1", port=0)
    owner.set_settings("not = [valid toml")
    with pytest.raises(ShareError):
        owner.node.create_invite(host="127.0.0.1")


def _wait_for_op(site, op, seconds=20.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if op in ops(site):
            return True
        time.sleep(0.1)
    return op in ops(site)


def test_server_stops_after_duration(sites):
    owner, _ = sites
    server = ShareServer(owner.node, bind="127.0.0.1", port=0, duration=1).start()
    t = threading.Thread(target=server.serve_forever)
    t.start()
    t.join(timeout=20)
    assert not t.is_alive()
    # T25 / DEF-192: serve_forever() must not return before serve_stop is audited
    assert "serve_stop" in ops(owner), ops(owner)
    assert _wait_for_op(owner, "serve_stop")
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", server.port), timeout=1)


def test_server_stops_on_time_while_a_client_holds_an_idle_connection(sites):
    owner, _ = sites
    server = ShareServer(owner.node, bind="127.0.0.1", port=0, duration=1).start()
    idle = socket.create_connection(("127.0.0.1", server.port))  # never sends a ClientHello
    try:
        started = time.monotonic()
        t = threading.Thread(target=server.serve_forever)
        t.start()
        t.join(timeout=20)
        assert not t.is_alive()
        assert time.monotonic() - started < 8  # duration (1 s) + bounded grace, not the 5 s hello timeout
        assert "serve_stop" in ops(owner), ops(owner)
    finally:
        idle.close()


def test_concurrent_stop_callers_all_return_after_serve_stop_is_audited(sites):
    owner, _ = sites
    server = ShareServer(owner.node, bind="127.0.0.1", port=0, duration=60).start()
    seen = []
    callers = [threading.Thread(target=lambda: (server.stop(), seen.append("serve_stop" in ops(owner)))) for _ in range(4)]
    for c in callers:
        c.start()
    for c in callers:
        c.join(20)
    assert seen == [True] * 4
