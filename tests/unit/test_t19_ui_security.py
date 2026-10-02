"""T19 - control panel security: loopback bind, path-secret session (no cookie), Host / Origin / CSRF, headers, caps, errors."""
from __future__ import annotations

import socket
import threading
import time

import pytest

from tests.unit.t19_helpers import (  # noqa: F401  (fixtures)
    ROUTES, Client, env, layout, panel, populated, ppanel, start, state_fingerprint, stop,
)
from zero_mem import cli
from zero_mem.ui import PanelSecurityError, create_server


# ----------------------------------------------------------------------------------------------- binding
@pytest.mark.parametrize("host", ["0.0.0.0", "::", "", "192.168.1.5", "10.0.0.1", "example.com", "localhost.evil.com",
                                  "127.0.0.2", "::ffff:127.0.0.1", "0", "*"])
def test_non_loopback_bind_is_refused_before_anything_is_created(env, host):
    with pytest.raises(PanelSecurityError):
        create_server(host=host)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_loopback_bind_works_and_reports_the_bound_address(env, host):
    server = create_server(host=host)
    try:
        assert server.server_address[0] == "127.0.0.1"
        assert server.entry_url().startswith(f"http://127.0.0.1:{server.port}/s/")
        assert server.entry_url().endswith(f"/s/{server.token}/")
    finally:
        server.server_close()


def test_ipv6_loopback_bind_when_available(env):
    try:
        probe = socket.socket(socket.AF_INET6)
        probe.bind(("::1", 0))
        probe.close()
    except OSError:
        pytest.skip("IPv6 loopback not available")
    server, thread = start(host="::1")
    try:
        assert server.entry_url().startswith("http://[::1]:")
        conn = __import__("http.client").client.HTTPConnection("::1", server.port, timeout=10)
        conn.putrequest("GET", f"{server.prefix}/", skip_host=True)
        conn.putheader("Host", f"[::1]:{server.port}")
        conn.endheaders()
        assert conn.getresponse().status == 200
    finally:
        stop(server, thread)


def test_cli_refuses_a_non_loopback_host_and_bad_values(env, capsys):
    assert cli.main(["ui", "--host", "0.0.0.0"]) == 2
    assert "loopback" in capsys.readouterr().err
    assert cli.main(["ui", "--idle-timeout", "0"]) == 2
    assert cli.main(["ui", "--port", "70000"]) == 2
    assert cli.main(["ui", "--allow-root", "relative/dir"]) == 2
    assert cli.main(["ui", "--profile", "bad profile!"]) in (2,)


def test_bad_port_is_refused(env):
    with pytest.raises(PanelSecurityError):
        create_server(port=70000)


def test_a_non_loopback_peer_would_be_dropped(env):
    server = create_server()
    try:
        class Sock:
            sent = b""

            def sendall(self, data):
                self.sent += data

        closed = []
        server.shutdown_request = lambda request: closed.append(request)
        sock = Sock()
        server.process_request(sock, ("203.0.113.9", 5555))
        assert closed == [sock] and sock.sent == b""
    finally:
        server.server_close()


# ----------------------------------------------------------------------------------------------- path secret (no cookie)
def test_there_is_no_cookie_at_all_so_nothing_can_leak_to_another_port(env):
    server, thread = start()
    try:
        client = Client(server)
        for route in ("/", "/add", "/inbox"):
            status, headers, _ = client.get(route)
            assert status == 200 and "set-cookie" not in headers
        status, headers, _ = Client(server, cookie=False).raw("GET", f"/?t={server.token}")
        assert status == 404 and "set-cookie" not in headers
        assert len(server.token) >= 43 and server.token != server.csrf_token
    finally:
        stop(server, thread)


def test_the_cookie_alone_is_not_authority_other_port_simulation(panel):
    """A service on another port of 127.0.0.1 would receive any host-scoped cookie. There is none to receive, and replaying
    the secret as a cookie (or as a query parameter) from a non-browser client with a forged Origin/Referer and Host gives
    nothing: only the path prefix authenticates."""
    server = panel.server
    anon = Client(server, cookie=False)
    for cookie in (f"zm_session_{server.port}={server.token}", f"zm_session={server.token}", f"session={server.token}"):
        for route in ("/", "/add", "/sharing", "/agents"):
            status, _h, body = anon.raw("GET", route, headers={"Cookie": cookie, "Referer": f"http://127.0.0.1:{server.port}/"})
            assert status == 404, (cookie, route)
            assert server.token not in body
        body = b"csrf=" + server.csrf_token.encode() + b"&text=owned&memory_type=fact"
        status, _h, _b = anon.raw("POST", "/add", body, {
            "Cookie": cookie, "Origin": f"http://127.0.0.1:{server.port}", "Referer": f"http://127.0.0.1:{server.port}/add",
            "Content-Type": "application/x-www-form-urlencoded"})
        assert status == 404
    assert anon.raw("GET", f"/?t={server.token}")[0] == 404
    assert anon.raw("GET", f"/?session={server.token}")[0] == 404


def test_the_secret_in_the_path_is_the_only_credential_and_is_reusable_and_constant_time(env):
    server, thread = start()
    try:
        client = Client(server)
        assert client.get("/")[0] == 200 and client.get("/")[0] == 200  # not single use: reloads and bookmarks work
        anon = Client(server, cookie=False)
        assert anon.raw("GET", f"{server.prefix}/inbox")[0] == 200
        assert anon.raw("GET", server.prefix)[0] == 200  # prefix without a trailing slash is the overview
    finally:
        stop(server, thread)


def test_constant_time_compare_is_used_for_the_prefix():
    import inspect

    from zero_mem.ui import server as srv

    assert "hmac.compare_digest" in inspect.getsource(srv._same)
    assert "_same(head, self.prefix)" in inspect.getsource(srv.PanelServer.split_prefix)


def test_tokens_differ_between_servers(env):
    a, b = create_server(), create_server()
    try:
        assert a.token != b.token and a.csrf_token != b.csrf_token
    finally:
        a.server_close()
        b.server_close()


@pytest.mark.parametrize("route", ROUTES + ["/source?id=" + "a" * 64, "/ingest/preview?id=x"])
def test_every_route_needs_the_path_secret_and_otherwise_is_a_generic_404(panel, route):
    anon = Client(panel.server, cookie=False)
    status, _h, body = anon.raw("GET", route)
    assert status == 404 and "Not found" in body
    server = panel.server
    wrong = ("/s/" + "A" * len(server.token), "/s/not-the-secret", "/s/" + server.token[:-1], "/s/" + server.token + "x",
             "/S/" + server.token, "/s//" + server.token, "/" + server.token, server.prefix + "%2f")
    for prefix in wrong:
        status, _h, body = anon.raw("GET", prefix + (route if route != "/" else "/"))
        assert status == 404, prefix
        assert "Overview" not in body and server.csrf_token not in body


def test_posts_without_the_prefix_are_refused_and_change_nothing(panel, layout):
    before = state_fingerprint(layout)
    anon = Client(panel.server, cookie=False)
    status, _h, _b = anon.post("/add", {"text": "hello", "memory_type": "fact"}, follow=False)
    assert status == 404
    assert state_fingerprint(layout) == before


# ----------------------------------------------------------------------------------------------- Host / Origin / CSRF
@pytest.mark.parametrize("host", ["evil.example", "evil.example:80", "127.0.0.1", "localhost", "127.0.0.1:1", "[::1]:1",
                                  "localhost.evil.com:PORT", "0.0.0.0:PORT", "", "127.0.0.1:PORT@evil.com"])
def test_bad_host_header_is_forbidden_dns_rebinding(panel, host):
    host = host.replace("PORT", str(panel.server.port))
    status, _h, body = panel.get("/", host_header=host or None)
    assert status == 403 and "Forbidden" in body


def test_missing_host_header_is_forbidden(panel):
    assert panel.get("/", host_header=None)[0] == 403


def test_host_is_checked_even_with_the_right_prefix(env):
    server, thread = start()
    try:
        client = Client(server)
        assert client.raw("GET", "/", host_header="rebind.evil.com")[0] == 403
        assert client.raw("GET", "/")[0] == 200
    finally:
        stop(server, thread)


@pytest.mark.parametrize("host", ["localhost:{p}", "LOCALHOST:{p}", "127.0.0.1:{p}"])
def test_loopback_host_names_with_the_port_are_accepted(panel, host):
    assert panel.get("/", host_header=host.format(p=panel.server.port))[0] == 200


def test_bad_origin_on_post_is_forbidden(panel, layout):
    before = state_fingerprint(layout)
    for origin in ("http://evil.example", "null", f"http://127.0.0.1:{panel.server.port + 1}", "https://127.0.0.1:%d" % panel.server.port,
                   f"http://localhost.evil.com:{panel.server.port}"):
        status, _h, _b = panel.post("/add", {"text": "owned", "memory_type": "fact"}, origin=origin, follow=False)
        assert status == 403, origin
    assert state_fingerprint(layout) == before


def test_post_without_origin_or_referer_is_forbidden_but_a_same_origin_referer_is_enough(panel, layout):
    before = state_fingerprint(layout)
    assert panel.post("/add", {"text": "x", "memory_type": "fact"}, origin=None, follow=False)[0] == 403
    assert state_fingerprint(layout) == before
    bad_ref = {"Referer": "http://evil.example/page"}
    assert panel.post("/add", {"text": "x", "memory_type": "fact"}, origin=None, headers=bad_ref, follow=False)[0] == 403
    good_ref = {"Referer": f"http://127.0.0.1:{panel.server.port}/add"}
    assert panel.post("/add", {"text": "referer ok", "memory_type": "fact"}, origin=None, headers=good_ref, follow=False)[0] == 303


def test_missing_or_wrong_csrf_is_forbidden_and_changes_nothing(panel, layout):
    before = state_fingerprint(layout)
    assert panel.post("/add", {"text": "x", "memory_type": "fact"}, csrf=None, follow=False)[0] == 403
    assert panel.post("/add", {"text": "x", "memory_type": "fact"}, csrf="wrong", follow=False)[0] == 403
    assert panel.post("/add", {"text": "x", "memory_type": "fact"}, csrf="", follow=False)[0] == 403
    assert state_fingerprint(layout) == before
    assert panel.post("/add", {"text": "x", "memory_type": "fact"}, follow=False)[0] == 303


def test_csrf_token_is_in_every_form_and_is_not_the_url_secret(panel):
    token = panel.token("/add")
    assert token == panel.server.csrf_token and token != panel.server.token
    for route in ("/inbox", "/ingest", "/agents", "/settings", "/eval"):
        assert f'name="csrf" value="{token}"' in panel.page(route)


@pytest.mark.parametrize("route", ["/inbox/approve", "/forget", "/settings/kill", "/agents/grant-write", "/eval/safety",
                                   "/ingest/confirm"])
def test_get_on_a_mutating_route_is_refused(panel, layout, route):
    before = state_fingerprint(layout)
    status, _h, _b = panel.get(route + "?approve=1&id=p-123&text=x&csrf=" + panel.server.csrf_token)
    assert status == 405
    assert state_fingerprint(layout) == before


def test_get_never_mutates_any_page_even_with_hostile_query_strings(ppanel, layout):
    before = state_fingerprint(layout)
    evil = "?approve=1&id=%s&ref=mem://rule/nofp&state=on&kind=space&text=x&csrf=%s&confirm=1&forget=1" % (
        ppanel.ids["pending"], ppanel.server.csrf_token)
    for route in ROUTES + ["/source", "/ingest/preview"]:
        ppanel.get(route + evil)
    assert state_fingerprint(layout) == before


def test_unsupported_methods_and_no_cors_headers(panel):
    for method in ("PUT", "DELETE", "PATCH", "OPTIONS", "HEAD", "TRACE"):
        status, headers, _b = panel.raw(method, "/", headers=panel._auth())
        assert status == 405, method
        assert not any(k.startswith("access-control-") for k in headers)
    status, headers, _b = panel.get("/", headers={"Origin": "http://evil.example"})
    assert not any(k.startswith("access-control-") for k in headers)


# ----------------------------------------------------------------------------------------------- headers
def _assert_security_headers(headers, body=None):
    csp = headers["content-security-policy"]
    assert "default-src 'none'" in csp and "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp
    assert "script-src" not in csp or "script-src 'none'" in csp
    assert "form-action 'self'" in csp and "frame-ancestors 'none'" in csp and "base-uri 'none'" in csp
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "same-origin"  # no-referrer makes Chromium send Origin: null on form posts
    assert "no-store" in headers["cache-control"]
    assert headers["x-frame-options"] == "DENY"
    assert not any(k.startswith("access-control-") for k in headers)
    return csp


@pytest.mark.parametrize("route", ROUTES)
def test_security_headers_on_every_page_and_the_nonce_matches_the_inline_style(panel, route):
    status, headers, body = panel.get(route)
    assert status == 200
    csp = _assert_security_headers(headers)
    nonce = csp.split("'nonce-")[1].split("'")[0]
    assert f'<style nonce="{nonce}">' in body
    assert "<script" not in body.lower() and " style=" not in body and "onclick" not in body.lower()
    assert "http://" not in body.replace("http://127.0.0.1", "") and "https://" not in body  # no external resources


def test_security_headers_on_redirects_and_errors_and_nonces_differ(panel):
    anon = Client(panel.server, cookie=False)
    for status, headers, _b in (anon.raw("GET", "/"), anon.raw("GET", "/", host_header="evil.example"),
                                panel.get("/nope"), panel.get("/add", headers={}),
                                panel.post("/add", {"text": "x"}, csrf=None, follow=False)):
        _assert_security_headers(headers)
    n1 = panel.get("/")[1]["content-security-policy"]
    n2 = panel.get("/")[1]["content-security-policy"]
    assert n1 != n2


# ----------------------------------------------------------------------------------------------- size caps, timeouts
def test_form_body_cap_is_enforced_before_the_body_is_read(panel):
    headers = panel._auth({"Content-Type": "application/x-www-form-urlencoded", "Origin": f"http://127.0.0.1:{panel.server.port}",
                           "Content-Length": str(1024 * 1024 + 1)})
    status, _h, body = panel.raw("POST", "/add", None, headers)
    assert status == 413 and "too large" in body


def test_upload_cap_is_enforced_by_content_length(panel):
    headers = panel._auth({"Content-Type": "multipart/form-data; boundary=x", "Origin": f"http://127.0.0.1:{panel.server.port}",
                           "Content-Length": str(27 * 1024 * 1024)})
    assert panel.raw("POST", "/ingest/preview", None, headers)[0] == 413


def test_upload_just_over_the_cap_is_refused_and_just_under_is_previewed(panel, layout):
    big = b"a" * (25 * 1024 * 1024 + 1)
    status, _h, body = panel.multipart("/ingest/preview", {"mode": "upload", "memory_type": "fact"}, "big.txt", big)
    assert status == 413 and "too large" in body
    ok = b"word " * 1000
    status, _h, body = panel.multipart("/ingest/preview", {"mode": "upload", "memory_type": "fact"}, "ok.txt", ok)
    assert status == 200 and "would ingest" in body


def test_missing_length_and_chunked_and_wrong_type_are_refused(panel):
    base = panel._auth({"Origin": f"http://127.0.0.1:{panel.server.port}", "Content-Type": "application/x-www-form-urlencoded"})
    assert panel.raw("POST", "/add", None, base)[0] == 411
    assert panel.raw("POST", "/add", b"0\r\n\r\n", {**base, "Transfer-Encoding": "chunked", "Content-Length": "5"})[0] == 411
    assert panel.raw("POST", "/add", b"{}", {**base, "Content-Type": "application/json"})[0] == 415
    assert panel.raw("POST", "/add", b"%ff%fe=1", base)[0] == 400
    assert panel.raw("POST", "/add", b"a=1", {**base, "Content-Length": "abc"})[0] == 411


def test_malformed_bodies_are_a_generic_400_not_a_traceback(panel):
    headers = panel._auth({"Origin": f"http://127.0.0.1:{panel.server.port}", "Content-Type": "multipart/form-data; boundary=zz"})
    for body in (b"garbage", b"--zz\r\nContent-Disposition: form-data\r\n\r\nx\r\n--zz--\r\n", b"--zz--\r\n",
                 b"--zz\r\n\r\n\r\n--zz--\r\n"):
        status, _h, text = panel.raw("POST", "/ingest/preview", body, headers)
        assert status in (400, 413) and "Traceback" not in text
    nob = panel._auth({"Origin": f"http://127.0.0.1:{panel.server.port}", "Content-Type": "multipart/form-data"})
    assert panel.raw("POST", "/ingest/preview", b"x", nob)[0] == 400


def test_very_long_url_and_odd_paths(panel):
    assert panel.get("/" + "a" * 5000)[0] == 400
    for path in ("/../../etc/passwd", "/%2e%2e/%2e%2e/etc/passwd", "//evil.example/x", "/static/../x", "/favicon.ico"):
        status, _h, body = panel.get(path)
        assert status in (400, 404) and "root:x:0" not in body


def test_slow_client_is_cut_off_by_the_request_timeout(env):
    server, thread = start(request_timeout=0.5)
    try:
        sock = socket.create_connection(("127.0.0.1", server.port), timeout=10)
        sock.sendall(b"GET / HTTP/1.0\r\nHost: 127.0.0.1")  # never finishes the headers
        started = time.monotonic()
        data = sock.recv(1024)
        assert time.monotonic() - started < 5
        assert data == b"" or b"HTTP/1.0 408" in data
        sock.close()
        assert Client(server).get("/")[0] == 200  # the server is still healthy
    finally:
        stop(server, thread)


def test_connection_budget_answers_503_instead_of_piling_up(env):
    server, thread = start(max_connections=2, request_timeout=3.0)
    idle = []
    try:
        for _ in range(2):
            idle.append(socket.create_connection(("127.0.0.1", server.port), timeout=10))
        time.sleep(0.3)
        sock = socket.create_connection(("127.0.0.1", server.port), timeout=10)
        sock.sendall(b"GET / HTTP/1.0\r\nHost: 127.0.0.1:%d\r\n\r\n" % server.port)
        assert b"503" in sock.recv(200)
        sock.close()
    finally:
        for s in idle:
            s.close()
        stop(server, thread)


def test_concurrent_requests_all_succeed(ppanel):
    results, errors = [], []

    def work(index):
        try:
            client = Client(ppanel.server)
            route = ROUTES[index % len(ROUTES)]
            results.append(client.get(route)[0])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not errors and results == [200] * 30


def test_concurrent_writes_do_not_corrupt_the_store(panel, layout):
    def work(index):
        client = Client(panel.server)
        client.post("/add", {"text": f"concurrent fact number {index}", "memory_type": "fact"}, follow=False)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    from zero_mem.memory import Memory

    with Memory.open("codex", channel="test") as mem:
        assert mem.status()["sources"]["total"] == 12 and not mem.status()["needs_rebuild"]


# ----------------------------------------------------------------------------------------------- idle timeout, errors
def test_idle_timeout_stops_the_server(env):
    server = create_server(idle_timeout_minutes=0.02)  # 1.2 s
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    thread.join(15)
    assert not thread.is_alive() and server._stopped_for_idle
    server.server_close()


def test_activity_postpones_the_idle_timeout(env):
    server = create_server(idle_timeout_minutes=0.05)  # 3 s
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    try:
        client = Client(server)
        for _ in range(5):
            time.sleep(1.0)
            assert client.get("/audit")[0] == 200
        assert thread.is_alive()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_handler_errors_never_leak_a_traceback_or_secrets(env, monkeypatch):
    from zero_mem.ui.handlers import Panel

    def boom(self, ctx):
        raise RuntimeError("SECRET-LEAK /home/owner/.ssh/id_rsa token=abc123")

    monkeypatch.setattr(Panel, "get_audit", boom)
    lines = []
    server, thread = start(log=lines.append)
    try:
        client = Client(server)
        status, headers, body = client.get("/audit?x=SECRETQUERY")
        assert status == 500
        for needle in ("SECRET", "Traceback", "RuntimeError", "/home/owner", "abc123", "File \""):
            assert needle not in body
        log = "\n".join(lines)
        assert "RuntimeError" in log and "/audit" in log
        for needle in ("SECRET", "abc123", "SECRETQUERY", server.token, server.csrf_token):
            assert needle not in log
        assert client.get("/")[0] == 200  # still serving
    finally:
        stop(server, thread)


def test_nothing_secret_is_logged_for_normal_traffic(env):
    lines = []
    server, thread = start(log=lines.append)
    try:
        client = Client(server)
        client.get("/")
        client.post("/add", {"text": "hello world", "memory_type": "fact"})
        assert lines == []
    finally:
        stop(server, thread)


def test_the_token_is_not_written_to_disk(env, tmp_path):
    server, thread = start()
    try:
        Client(server)
        token = server.token
        for path in tmp_path.rglob("*"):
            if path.is_file() and path.stat().st_size < 5_000_000:
                assert token.encode() not in path.read_bytes(), path
    finally:
        stop(server, thread)
