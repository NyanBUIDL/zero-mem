"""T21 - control-panel Sharing page: two memories, real TLS on loopback, invite shown once, previews before grants/pulls,
and the panel's security model (CSRF / Origin / Host / cookie / escaping / CSP / no secrets in logs) for every new endpoint."""
from __future__ import annotations

import re
import sys
from urllib.parse import quote

import pytest

pytest.importorskip("cryptography")

from tests.unit.t19_helpers import XSS, Client, start, stop  # noqa: E402
from tests.unit.t20_helpers import Site  # noqa: E402
from zero_mem.share.server import ShareServer  # noqa: E402


def has_code(text):
    return bool(re.search(r"zm1:[A-Za-z0-9_-]{20,}", text))


class World:
    def __init__(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg" / "config"))
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg" / "state"))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg" / "data"))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg" / "cache"))
        self.alice = Site(tmp_path, "alice")
        self.bob = Site(tmp_path, "bob")
        monkeypatch.setenv("ZERO_MEM_SETTINGS", str(self.alice.settings))
        self.logs: list = []
        self.sa, self.ta = start(layout=self.alice.node.layout, log=self.logs.append)
        self.sb, self.tb = start(layout=self.bob.node.layout, log=self.logs.append)
        self.ca, self.cb = Client(self.sa), Client(self.sb)
        self.share = ShareServer(self.alice.node, bind="127.0.0.1", port=0, duration=300).start()

    def close(self):
        self.share.stop()
        stop(self.sa, self.ta)
        stop(self.sb, self.tb)
        self.alice.close()
        self.bob.close()

    def invite(self, grant_fields=None):
        fields = {"host": "127.0.0.1", "port": str(self.share.port), "label": "alice", "expires": "10m"}
        fields.update(grant_fields or {})
        status, headers, body = self.ca.post("/sharing/invite", fields, follow=False)
        assert status == 200, body[:300]
        code = re.search(r'<textarea id="invite-code"[^>]*>(zm1:[^<]+)</textarea>', body).group(1)
        return code, headers, body

    def pair(self):
        code, _h, _b = self.invite()
        status, _hh, body = self.cb.post("/sharing/join", {"code": code, "label": "bob"})
        assert status == 200 and "Paired with the owner" in body, body[:500]
        return code


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    try:
        yield w
    finally:
        w.close()


def peer_id(w):
    return w.alice.node.peers()[0]["peer_id"]


# ------------------------------------------------------------------------------------------------ status
def test_status_reasons(world, monkeypatch):
    body = world.ca.page("/sharing")
    assert "ACTIVE" in body and "zero-mem share serve" in body and "never opens a network listener" in body
    world.alice.set_settings("[sharing]\nenabled = false\n")
    assert "sharing.enabled is false" in world.ca.page("/sharing") and "OFF" in world.ca.page("/sharing")
    world.alice.set_settings("[sharing]\nenabled = true\n[safety]\nkill_switch = true\n")
    assert "kill switch is on" in world.ca.page("/sharing")
    world.alice.set_settings("[sharing\nbroken")
    assert "unusable" in world.ca.page("/sharing")
    world.alice.set_settings("[sharing]\nenabled = true\n")
    monkeypatch.setitem(sys.modules, "cryptography", None)  # import raises ImportError: the extra is "missing"
    assert "cryptography" in world.ca.page("/sharing") and "zero-mem[share]" in world.ca.page("/sharing")


def test_mutations_are_refused_when_sharing_is_off(world):
    world.alice.set_settings("[sharing]\nenabled = false\n")
    status, _h, body = world.ca.post("/sharing/invite", {"host": "127.0.0.1", "port": "1", "expires": "10m"})
    assert status == 200 and "peer sharing is off" in body and not has_code(body)


# ------------------------------------------------------------------------------------------------ invite shown once
def test_invite_is_shown_once_and_leaks_nowhere(world, capsys):
    code, headers, body = world.invite()
    csp = headers["content-security-policy"]
    nonce = csp.split("'nonce-")[1].split("'")[0]
    assert f"script-src 'nonce-{nonce}'" in csp and f'<script nonce="{nonce}">' in body
    assert "'unsafe-inline'" not in csp and headers["cache-control"] == "no-store"
    assert "secret" in body.lower() and "hidden" in body and "copy-invite" in body  # warning + button degrades without JS
    assert 'readonly' in body and code in body
    for path in ("/sharing", "/audit", "/", "/inbox"):  # a later page never shows it, and has no script
        page = world.ca.page(path)
        assert code not in page and "<script" not in page.lower()
    token = code.split(":", 1)[1]
    assert not any(code in line or token in line for line in world.logs)
    out = capsys.readouterr()
    assert code not in out.out + out.err and token not in out.out + out.err
    for path in world.alice.root.rglob("*"):  # not stored anywhere (the store keeps a hash only)
        if path.is_file() and path.stat().st_size < 5_000_000:
            data = path.read_bytes()
            assert code.encode() not in data and token.encode() not in data, path
    audit = world.ca.page("/sharing")
    assert "invite_create" in audit


def test_invite_with_offered_grant_and_bad_input(world):
    _code, _h, body = world.invite({"space": "ks-shared", "types": "rule"})
    assert "1 grant(s)" in body
    status, _h, flash = world.ca.post("/sharing/invite", {"host": "127.0.0.1", "port": "70000", "expires": "10m"})
    assert "port must be" in flash and not has_code(flash)
    _s, _h, flash = world.ca.post("/sharing/invite", {"host": "127.0.0.1", "port": "1", "expires": "10m", "space": "ks-peer-x"})
    assert "quarantine" in flash and not has_code(flash)
    _s, _h, flash = world.ca.post("/sharing/invite", {"host": "8.8.8.8", "port": "1", "expires": "10m"})
    assert not has_code(flash)


# ------------------------------------------------------------------------------------------------ the whole flow
def test_full_flow_through_the_panels(world):
    w = world
    w.alice.add("Never deploy on Fridays at all", "rule", name="no-friday")
    w.alice.add("An ordinary fact that stays home", "fact", name="home")
    w.alice.add("The orchid cluster lives in region north", "file", name="notes.txt")
    w.pair()
    pid = peer_id(w)
    page = w.ca.page("/sharing")
    assert "bob" in page and pid in page and "never" in page and "No grants" in page
    assert "alice" in w.cb.page("/sharing") and w.alice.node.identity().peer_id in w.cb.page("/sharing")

    # grant: preview first, nothing granted yet
    form = {"peer": pid, "space": "ks-shared", "grant_expires": "30d", "ref_prefixes": "mem://rule/"}
    status, _h, preview = w.ca.post("/sharing/grant-preview", form, lists=[("types", "rule")])
    assert status == 200 and "mem://rule/no-friday" in preview and "rule: 1" in preview
    assert "mem://fact/home" not in preview and "notes.txt" not in preview
    assert w.alice.node.grants(None) == []
    token = re.search(r'name="id" value="([^"]+)"', preview).group(1)
    status, _h, body = w.ca.post("/sharing/grant-confirm", {"id": token})  # no confirmation ticked
    assert "Not confirmed" in body and w.alice.node.grants(None) == []
    status, _h, body = w.ca.post("/sharing/grant-confirm", {"id": token, "confirm": "1"})
    assert "Access granted" in body and len(w.alice.node.grants(None)) == 1
    assert w.alice.node.preview(pid)["sources"] == 1  # what the preview promised is what is readable
    assert "expired" in w.ca.post("/sharing/grant-confirm", {"id": token, "confirm": "1"})[2]  # one use

    # pull: plan, then confirm
    owner_id = w.alice.node.identity().peer_id
    status, _h, plan = w.cb.post("/sharing/pull-plan", {"owner": owner_id})
    assert "mem://rule/no-friday" in plan and "proposal" in plan and "untrusted reference" in plan and "notes.txt" not in plan
    assert w.bob.node.log.imported_digest(owner_id, "x") is None
    pull_id = re.search(r'name="id" value="([^"]+)"', plan).group(1)
    _s, _h, body = w.cb.post("/sharing/pull-confirm", {"id": pull_id})
    assert "Not confirmed" in body
    _s, _h, body = w.cb.post("/sharing/pull-confirm", {"id": pull_id, "confirm": "1"})
    assert "Pull finished" in body and "Proposals to review" in body
    page = w.cb.page("/sharing")
    assert "Never deploy on Fridays" in page and 'href="/inbox"' in page  # proposal from a peer
    assert "Nothing has been imported from a peer yet" in page  # the rule is a proposal, not an import

    # a file arrives only once it is granted
    form = {"peer": pid, "space": "ks-shared", "grant_expires": "7d"}
    _s, _h, preview = w.ca.post("/sharing/grant-preview", form, lists=[("types", "file")])
    assert "notes.txt" in preview and "file: 1" in preview
    token = re.search(r'name="id" value="([^"]+)"', preview).group(1)
    w.ca.post("/sharing/grant-confirm", {"id": token, "confirm": "1"})
    _s, _h, plan = w.cb.post("/sharing/pull-plan", {"owner": owner_id})
    pull_id = re.search(r'name="id" value="([^"]+)"', plan).group(1)
    w.cb.post("/sharing/pull-confirm", {"id": pull_id, "confirm": "1"})
    page = w.cb.page("/sharing")
    assert f"peer://{owner_id}/file/notes.txt" in page and "untrusted reference" in page
    assert "file://notes.txt" in page  # provenance: original ref
    assert "mem://fact/home" not in page

    # the owner sees the pulls, and revokes a single grant
    page = w.ca.page("/sharing")
    assert re.search(r"Last pull</dt><dd>20\d\d-", page)
    grant_id = w.alice.node.grants(None)[0]["grant_id"]
    status, _h, body = w.ca.post("/sharing/revoke-grant", {"peer": pid, "grant_id": grant_id})
    assert "Not confirmed" in body
    _s, _h, body = w.ca.post("/sharing/revoke-grant", {"peer": pid, "grant_id": grant_id, "confirm": "1"})
    assert "Grant revoked" in body
    assert w.alice.node.preview(pid)["sources"] == 1  # the other grant (files) is still active
    # revoking the peer: the next plan fails clearly
    _s, _h, body = w.ca.post("/sharing/revoke-peer", {"peer": pid, "confirm": "1"})
    assert "Peer revoked" in body and "revoked" in w.ca.page("/sharing")
    _s, _h, body = w.cb.post("/sharing/pull-plan", {"owner": owner_id})
    assert "Cannot plan the pull" in body
    _s, _h, body = w.cb.post("/sharing/unpair", {"owner": owner_id, "confirm": "1"})
    assert "Owner forgotten" in body and "You have not joined" in w.cb.page("/sharing")
    assert not any(has_code(line) for line in w.logs)


def test_pull_confirm_aborts_when_the_offer_changed(world):
    w = world
    w.alice.add("first granted fact", "fact", name="one")
    w.pair()
    pid, owner_id = peer_id(w), w.alice.node.identity().peer_id
    w.alice.node.grant(pid, {"space": "ks-shared"})
    _s, _h, plan = w.cb.post("/sharing/pull-plan", {"owner": owner_id})
    pull_id = re.search(r'name="id" value="([^"]+)"', plan).group(1)
    w.alice.add("a late addition the peer never reviewed", "fact", name="two")
    _s, _h, body = w.cb.post("/sharing/pull-confirm", {"id": pull_id, "confirm": "1"})
    assert "offering changed" in body
    assert "Nothing has been imported" in w.cb.page("/sharing")


def test_peer_supplied_text_is_escaped(world):
    w = world
    w.alice.add(XSS, "rule", name="xss")
    w.pair()
    pid, owner_id = peer_id(w), w.alice.node.identity().peer_id
    w.alice.node.grant(pid, {"space": "ks-shared"})
    _s, _h, plan = w.cb.post("/sharing/pull-plan", {"owner": owner_id})
    pull_id = re.search(r'name="id" value="([^"]+)"', plan).group(1)
    w.cb.post("/sharing/pull-confirm", {"id": pull_id, "confirm": "1"})
    for page in (w.cb.page("/sharing"), w.cb.page("/inbox")):
        assert "<script>alert(1)</script>" not in page and "<img src=x" not in page and "&lt;script&gt;" in page


def test_garbage_input_is_escaped_and_never_echoed(world):
    status, _h, body = world.cb.post("/sharing/join", {"code": XSS, "label": XSS})
    assert "<script>" not in body and "alert(1)" not in body.replace("&lt;", "<") .split("Not joined")[0]
    assert "Not joined" in body
    _s, _h, body = world.ca.post("/sharing/grant-preview", {"peer": XSS, "space": XSS})
    assert "<script>" not in body and "Cannot preview" in body
    _s, _h, body = world.ca.post("/sharing/pull-plan", {"owner": XSS})
    assert "<script>" not in body
    for path in ("/sharing/grant-preview", "/sharing/pull-plan"):
        status, _h, body = world.ca.get(quote(path + "?id=" + XSS, safe="/?=")), None, None
    status, _h, body = world.ca.get("/sharing/grant-preview?id=" + quote(XSS))
    assert status == 303


# ------------------------------------------------------------------------------------------------ security per endpoint
POSTS = ["/sharing/invite", "/sharing/join", "/sharing/grant-preview", "/sharing/grant-confirm", "/sharing/revoke-grant",
         "/sharing/revoke-peer", "/sharing/pull-plan", "/sharing/pull-confirm", "/sharing/unpair"]
GETS = ["/sharing", "/sharing/grant-preview", "/sharing/pull-plan"]


@pytest.mark.parametrize("path", POSTS)
def test_post_endpoints_enforce_csrf_origin_host_cookie(world, path):
    c = world.ca
    fields = {"owner": "x", "peer": "x"}
    before = len(world.alice.node.audit(500))
    assert c.post(path, fields, csrf=None, follow=False)[0] == 403
    assert c.post(path, fields, csrf="wrong", follow=False)[0] == 403
    assert c.post(path, fields, origin="http://evil.example", follow=False)[0] == 403
    assert c.post(path, fields, origin=None, follow=False)[0] == 403
    assert c.post(path, fields, origin=f"http://localhost:{c.port}.evil.example", follow=False)[0] == 403
    status, *_ = c.raw("POST", path, b"csrf=" + c.server.csrf_token.encode(),
                       {"Content-Type": "application/x-www-form-urlencoded", "Origin": f"http://127.0.0.1:{c.port}",
                        "Cookie": c.cookie}, host_header="evil.example")
    assert status == 403
    anon = Client(world.sa, cookie=False)
    assert anon.post(path, fields, follow=False)[0] == 401
    assert c.get(path)[0] in (200, 303, 405) and c.raw("PUT", path, b"", c._auth())[0] == 405
    assert len(world.alice.node.audit(500)) == before  # nothing was written by any refused request


@pytest.mark.parametrize("path", POSTS)
def test_post_only_mutations_reject_get(world, path):
    if path in ("/sharing/grant-preview", "/sharing/pull-plan"):
        pytest.skip("the GET of a preview shows a stored plan; it cannot mutate")
    assert world.ca.get(path)[0] == 405


@pytest.mark.parametrize("path", GETS)
def test_get_pages_enforce_host_and_cookie(world, path):
    c = world.ca
    assert Client(world.sa, cookie=False).get(path)[0] == 401
    assert c.get(path, host_header="evil.example")[0] == 403
    status, headers, _b = c.get(path)
    assert status in (200, 303)
    assert "script-src" not in headers.get("content-security-policy", "")


def test_csrf_token_is_in_every_form(world):
    body = world.ca.page("/sharing")
    forms = re.findall(r"<form .*?</form>", body, re.S)
    assert forms and all('name="csrf"' in f and 'method="post"' in f for f in forms)
    assert not re.search(r"<form[^>]+method=.get", body, re.I)
