"""T22 finding 1 - the panel session must not be ambient authority.

A cookie is scoped to the host, not the port, so the browser sends it to every other service on 127.0.0.1 / localhost (for
example an agent's dev server). The session secret therefore lives only in the URL path prefix (``/s/<secret>/``): a page on
another origin cannot read it, and a cookie (which no longer exists) cannot carry it."""
from __future__ import annotations

import re

from tests.unit.t19_helpers import ROUTES, Client, env, layout, populated, ppanel, panel, state_fingerprint  # noqa: F401


def test_a_cookie_alone_cannot_drive_the_panel_from_a_non_browser_client(panel, layout):
    """RED against the cookie design: the ambient cookie + forged Origin/Referer + the panel's Host authenticated a mutation."""
    server = panel.server
    before = state_fingerprint(layout)
    forged = {"Origin": f"http://127.0.0.1:{server.port}", "Referer": f"http://127.0.0.1:{server.port}/add"}
    anon = Client(server, cookie=False)
    # what a hostile dev server on another port could replay if the browser had ever given it a cookie
    leaked = getattr(server, "_cookie_secret", server.token)
    names = [f"zm_session_{server.port}", "zm_session", "session"]
    for name in names:
        headers = dict(forged, Cookie=f"{name}={leaked}")
        status, _h, _b = anon.raw("GET", "/add", headers=headers)
        assert status != 200
        body = b"csrf=" + server.csrf_token.encode() + b"&text=owned&memory_type=fact"
        status, _h, _b = anon.raw("POST", "/add", body, dict(headers, **{"Content-Type": "application/x-www-form-urlencoded"}))
        assert status in (401, 404)
    assert state_fingerprint(layout) == before


def test_responses_never_set_a_cookie_and_the_policy_keeps_the_secret_in_the_origin(ppanel):
    for route in ROUTES + ["/inbox?status=pending"]:
        status, headers, _b = ppanel.get(route)
        assert status == 200 and "set-cookie" not in headers
        assert headers["referrer-policy"] == "same-origin"  # the path secret is never sent in a cross-origin Referer
        assert headers["cache-control"] == "no-store"


LINK = re.compile(r'\b(?:href|action)="([^"]*)"')


def _check_links(client, route, seen):
    status, headers, body = client.get(route)
    assert status == 200, route
    prefix = client.server.prefix + "/"
    for target in LINK.findall(body):
        if target.startswith("#"):
            continue
        assert target.startswith(prefix), (route, target)
        seen.add(target[len(client.server.prefix):])
    return body


def test_every_link_and_form_action_carries_the_prefix_crawl(ppanel):
    seen, done = set(), set()
    queue = list(ROUTES)
    while queue:
        route = queue.pop()
        if route in done:
            continue
        done.add(route)
        links = set()
        _check_links(ppanel, route, links)
        for link in links:
            path = link.split("?", 1)[0]
            # follow GET-able pages only (forms with mutating POST targets answer 405 to a GET)
            if link not in done and ppanel.get(link)[0] == 200 and len(done) < 80:
                queue.append(link)
        seen |= links
    assert len(done) >= len(ROUTES)
    assert any(link.startswith("/inbox") for link in seen)
    assert "/sharing" in seen or any(link.startswith("/sharing") for link in seen)


def test_redirects_carry_the_prefix(ppanel):
    status, headers, _b = ppanel.post("/add", {"text": "redirect check fact", "memory_type": "fact"}, follow=False)
    assert status == 303 and headers["location"].startswith(ppanel.server.prefix + "/add")
    status, headers, _b = ppanel.post("/agents/add", {"profile": "zed"}, follow=False)
    assert status == 303 and headers["location"].startswith(ppanel.server.prefix + "/agents")


def test_forms_posted_to_their_prefixed_action_work_end_to_end(ppanel):
    body = ppanel.page("/add")
    action = re.search(r'<form method="post" action="([^"]+)"', body).group(1)
    assert action == ppanel.server.prefix + "/add"
    status, headers, _b = ppanel.raw("POST", action, b"csrf=" + ppanel.server.csrf_token.encode() + b"&text=via+action&memory_type=fact",
                                     {"Content-Type": "application/x-www-form-urlencoded",
                                      "Origin": f"http://127.0.0.1:{ppanel.port}"})
    assert status == 303


def test_error_pages_for_unauthenticated_requests_reveal_nothing(panel):
    anon = Client(panel.server, cookie=False)
    status, headers, body = anon.raw("GET", "/")
    assert status == 404 and "<nav" not in body and "control panel" not in body.lower() and "Set-Cookie" not in headers
