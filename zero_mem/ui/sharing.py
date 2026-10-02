"""Control-panel pages for peer sharing (``/sharing``), docs/runbooks/control-panel.md and peer-sharing.md.

Same security model as the rest of the panel (loopback, cookie, Host / Origin / CSRF, POST-only mutation, escaping, CSP).
There is NO new sharing logic here: every action calls :class:`zero_mem.share.node.ShareNode` / ``share.client`` exactly like
``zero-mem share ...``. The panel never opens a network listener (``share serve`` stays a CLI action) and never stores,
logs or puts an invite code in a URL: the ``zm1:`` string exists only in the body of the one POST response that created it.
Grants and pulls are two-step: a POST computes a server-side PREVIEW / PLAN (random id, short lived), the confirm POST applies
exactly that stored object.
"""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections import OrderedDict
from typing import Optional

from .. import learning_settings as ls
from ..memory import MEMORY_TYPES, PEER_REF_PREFIX, Memory
from ..share import DEFAULT_PORT, ShareError
from ..share import events as ev
from .render import Markup, checkbox, e, field, flash_html, form, h, join, select, table, textarea, url
from .server import Request, Response, redirect

PREVIEW_TTL = 15 * 60.0
MAX_STORED = 12
PREVIEW_REFS = 20
MAX_PLAN_ROWS = 200
AUDIT_ROWS = 60
INVITE_EXPIRIES = (("10m", "10 minutes"), ("30m", "30 minutes"), ("1h", "1 hour"), ("6h", "6 hours"), ("24h", "24 hours"))
GRANT_EXPIRIES = (("1d", "1 day"), ("7d", "7 days"), ("30d", "30 days (default)"), ("90d", "90 days"), ("never", "never"))
COPY_SCRIPT = (
    "(function(){var b=document.getElementById('copy-invite'),t=document.getElementById('invite-code');"
    "if(!b||!t||!navigator.clipboard){return}b.hidden=false;"
    "b.addEventListener('click',function(){navigator.clipboard.writeText(t.value).then("
    "function(){b.textContent='Copied'},function(){t.focus();t.select()})})})();")


def _short(value, n: int = 12) -> str:
    return str(value or "")[:n]


def _msg(exc: ShareError) -> str:
    return exc.message


def _flash_error(title: str, message: str) -> dict:
    return {"kind": "error", "title": title, "lines": [message]}


class Sharing:
    """Handlers for the sharing page; registered by :class:`zero_mem.ui.handlers.Panel`."""

    def __init__(self, panel) -> None:
        self.panel = panel
        self._store: "OrderedDict[str, dict]" = OrderedDict()
        self._lock = threading.Lock()
        self._busy = threading.Lock()  # one network operation (join / plan / pull) at a time

    # ------------------------------------------------------------------------------------------ plumbing
    def routes(self) -> tuple:
        get = {"/sharing": self.get_sharing, "/sharing/grant-preview": self.get_grant_preview,
               "/sharing/pull-plan": self.get_pull_plan}
        post = {"/sharing/invite": self.post_invite, "/sharing/join": self.post_join,
                "/sharing/grant-preview": self.post_grant_preview, "/sharing/grant-confirm": self.post_grant_confirm,
                "/sharing/revoke-grant": self.post_revoke_grant, "/sharing/revoke-peer": self.post_revoke_peer,
                "/sharing/pull-plan": self.post_pull_plan, "/sharing/pull-confirm": self.post_pull_confirm,
                "/sharing/unpair": self.post_unpair}
        return get, post

    def _node(self):
        from ..share.node import SERVICE_PROFILE, ShareNode

        return ShareNode(Memory(SERVICE_PROFILE, self.panel.layout, channel="ui"))

    def _put(self, kind: str, payload: dict) -> str:
        key = secrets.token_urlsafe(16)
        with self._lock:
            now = time.monotonic()
            for old in [k for k, v in self._store.items() if now - v["at"] > PREVIEW_TTL]:
                del self._store[old]
            self._store[key] = {"kind": kind, "at": now, **payload}
            while len(self._store) > MAX_STORED:
                self._store.popitem(last=False)
        return key

    def _get(self, key: Optional[str], kind: str) -> Optional[dict]:
        with self._lock:
            item = self._store.get(key or "")
            if item is None or item["kind"] != kind or time.monotonic() - item["at"] > PREVIEW_TTL:
                return None
            return item

    def _drop(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def _fail(self, title: str, exc: Exception, path: str = "/sharing") -> Response:
        if isinstance(exc, ShareError):
            return self.panel.go(path, _flash_error(title, _msg(exc)))
        self.panel.log_error("sharing", exc)
        return self.panel.go(path, _flash_error(title, "unexpected error; nothing was changed (see the terminal running zero-mem ui)"))

    # ------------------------------------------------------------------------------------------ the page
    def _status(self) -> dict:
        cfg = ls.load_settings()
        try:
            import cryptography  # noqa: F401
            crypto = True
        except ImportError:
            crypto = False
        reasons = []
        if not crypto:
            reasons.append('the optional package "cryptography" is not installed (pip install "zero-mem[share]")')
        if not cfg.valid:
            reasons.append("the settings file is unusable, so sharing is off (zero-mem settings validate)")
        elif cfg.kill_switch:
            reasons.append("the kill switch is on (settings: safety.kill_switch)")
        elif not cfg.sharing_enabled:
            reasons.append("sharing.enabled is false (enable it: zero-mem settings set sharing.enabled true)")
        return {"active": bool(cfg.sharing_active and crypto and not reasons), "reasons": reasons, "crypto": crypto,
                "import_into_recall": bool(getattr(cfg, "import_into_recall", False))}

    def _serve_command(self) -> str:
        try:
            from ..workspaces import active_selection

            selection = active_selection()
            memory = f" --memory {selection.name}" if selection is not None and selection.named else ""
        except Exception:  # noqa: BLE001
            memory = ""
        return f"zero-mem{memory} share serve --port {DEFAULT_PORT} --for 30m"

    def get_sharing(self, ctx) -> Response:
        status = self._status()
        with self._node() as node:
            from ..share.identity import load_identity

            try:
                ident = load_identity(node.layout)
            except ShareError:
                ident = None
            peers = node.peers()
            grants = node.grants(None, include_ended=True)
            owners = node.owners()
            events = node.audit(1000)
        reviewer_rows = []
        try:
            reviewer_rows = [p for p in self.panel.reviewer().list("pending") if p.get("source") == "peer"]
        except Exception:  # noqa: BLE001
            pass
        with self.panel.memory(self.panel.profile) as mem:
            imports = _peer_imports(mem)
        last_pull: dict = {}
        owner_pull: dict = {}
        for event in events:
            if event["op"] in ("manifest", "fetch") and event.get("peer_id"):
                last_pull[event["peer_id"]] = event["at"]
            elif event["op"] == "pull" and event.get("owner"):
                owner_pull[event["owner"]] = event["at"]
        forgotten = [x for x in events if x["op"] == "import" and x.get("outcome") == "revoke_proposed"][-10:]
        view = {"status": status, "ident": ident, "label": node.own_label(), "peers": peers, "grants": grants,
                "owners": owners, "last_pull": last_pull, "owner_pull": owner_pull, "imports": imports,
                "proposals": reviewer_rows, "forgotten": forgotten, "audit": list(reversed(events))[:AUDIT_ROWS],
                "serve": self._serve_command(), "lan": _lan()}
        return ctx.render("Sharing", _page(view, ctx.csrf), "/sharing")

    # ------------------------------------------------------------------------------------------ invite
    def post_invite(self, ctx) -> Response:
        from ..share.grants import expires_arg, validate_grant_spec
        from ..share.invite import MAX_INVITE_SECONDS
        from ..share.util import parse_duration

        f = ctx.request.form
        try:
            expires = parse_duration(f.get("expires") or "10m", maximum=MAX_INVITE_SECONDS)
            port = _port(f.get("port"))
            grants = []
            if (f.get("space") or "").strip() or (f.get("projects") or "").strip():
                grants.append(_grant_spec_from_form(f))
            host = (f.get("host") or "").strip() or None
            label = (f.get("label") or "").strip() or None
            with self._node() as node:
                invite = node.create_invite(host=host, port=port, label=label, expires_in=expires, grants=grants)
                code = invite.encode()
                host_used, left = invite.host, max(0, invite.expires - int(time.time()))
        except ShareError as exc:
            return self.panel.go("/sharing", _flash_error("Invite not created", _msg(exc)))
        except Exception as exc:  # noqa: BLE001
            return self._fail("Invite not created", exc)
        body = _invite_view(code, host_used, left, len(grants), ctx.nonce)
        response = ctx.render("Invite created", body, "/sharing")
        response.script = True
        response.headers.append(("Cache-Control", "no-store"))
        return response

    # ------------------------------------------------------------------------------------------ join
    def post_join(self, ctx) -> Response:
        from ..share import client

        code = (ctx.request.form.get("code") or "").strip()
        label = (ctx.request.form.get("label") or "").strip() or None
        if not self._busy.acquire(blocking=False):
            return self.panel.go("/sharing", _flash_error("Busy", "another sharing operation is running; try again in a moment"))
        try:
            with self._node() as node:
                result = client.join(node, code, label)
        except Exception as exc:  # noqa: BLE001
            return self._fail("Not joined", exc)
        finally:
            self._busy.release()
        return self.panel.go("/sharing", {"kind": "ok", "title": "Paired with the owner", "details": [
            ("Owner", result["owner_label"]), ("Peer id", result["owner_peer_id"]),
            ("Next", "ask the owner to grant you access, then plan a pull below")]})

    # ------------------------------------------------------------------------------------------ grants
    def post_grant_preview(self, ctx) -> Response:
        from ..share.grants import validate_grant_spec

        f = ctx.request.form
        try:
            spec = validate_grant_spec(_grant_spec_from_form(f))
            with self._node() as node:
                peer = node.resolve_peer(f.get("peer", ""))
                preview = node.preview_spec(peer["peer_id"], spec, limit=PREVIEW_REFS)
        except Exception as exc:  # noqa: BLE001
            return self._fail("Cannot preview the grant", exc)
        key = self._put("grant", {"peer": peer["peer_id"], "label": peer["label"], "spec": spec, "preview": preview})
        return redirect(url("/sharing/grant-preview", id=key))

    def get_grant_preview(self, ctx) -> Response:
        item = self._get(ctx.request.query.get("id"), "grant")
        if item is None:
            return self.panel.go("/sharing", _flash_error("Preview expired", "Start again: previews are kept for 15 minutes."))
        return ctx.render("Review the grant", _grant_preview(item, ctx.request.query["id"], ctx.csrf), "/sharing")

    def post_grant_confirm(self, ctx) -> Response:
        f = ctx.request.form
        item = self._get(f.get("id"), "grant")
        if item is None:
            return self.panel.go("/sharing", _flash_error("Preview expired", "Nothing was granted. Start again."))
        if not f.get("confirm"):
            return self.panel.go("/sharing", _flash_error("Not confirmed", "Tick the confirmation box to grant access. Nothing was granted."))
        try:
            with self._node() as node:
                grant = node.grant(item["peer"], item["spec"])
                now = node.preview(item["peer"])
        except Exception as exc:  # noqa: BLE001
            return self._fail("Not granted", exc)
        self._drop(f["id"])
        return self.panel.go("/sharing", {"kind": "ok", "title": "Access granted", "details": [
            ("Peer", item["label"]), ("Grant", grant["grant_id"]), ("Readable sources now", now["sources"]),
            ("Note", "the peer can copy what it reads; revoking cannot recall copies")]})

    def post_revoke_grant(self, ctx) -> Response:
        f = ctx.request.form
        if not f.get("confirm"):
            return self.panel.go("/sharing", _flash_error("Not confirmed", "Tick the confirmation box to revoke."))
        try:
            with self._node() as node:
                result = node.revoke_grants(f.get("peer", ""), f.get("grant_id") or None)
        except Exception as exc:  # noqa: BLE001
            return self._fail("Not revoked", exc)
        return self.panel.go("/sharing", {"kind": "ok", "title": "Grant revoked", "details": [
            ("Peer", result["peer_id"]), ("Grants", ", ".join(result["revoked"]) or "none")]})

    def post_revoke_peer(self, ctx) -> Response:
        f = ctx.request.form
        if not f.get("confirm"):
            return self.panel.go("/sharing", _flash_error("Not confirmed", "Tick the confirmation box to revoke the peer."))
        try:
            with self._node() as node:
                result = node.revoke_peer(f.get("peer", ""))
        except Exception as exc:  # noqa: BLE001
            return self._fail("Peer not revoked", exc)
        return self.panel.go("/sharing", {"kind": "ok", "title": "Peer revoked", "details": [
            ("Peer", result["peer_id"]), ("Status", result["status"]),
            ("Note", "its certificate is no longer trusted; copies it already pulled cannot be recalled")]})

    # ------------------------------------------------------------------------------------------ pull
    def post_pull_plan(self, ctx) -> Response:
        from ..share import client

        if not self._busy.acquire(blocking=False):
            return self.panel.go("/sharing", _flash_error("Busy", "another sharing operation is running; try again in a moment"))
        try:
            with self._node() as node:
                report = client.pull(node, ctx.request.form.get("owner", ""), dry_run=True)
        except Exception as exc:  # noqa: BLE001
            return self._fail("Cannot plan the pull", exc)
        finally:
            self._busy.release()
        key = self._put("pull", {"owner": report.owner["peer_id"], "label": report.owner["label"], "plan": report.plan,
                                 "sig": _plan_signature(report.plan)})
        return redirect(url("/sharing/pull-plan", id=key))

    def get_pull_plan(self, ctx) -> Response:
        item = self._get(ctx.request.query.get("id"), "pull")
        if item is None:
            return self.panel.go("/sharing", _flash_error("Plan expired", "Start again: plans are kept for 15 minutes."))
        return ctx.render("Review the pull", _pull_plan(item, ctx.request.query["id"], ctx.csrf), "/sharing")

    def post_pull_confirm(self, ctx) -> Response:
        from ..share import client

        f = ctx.request.form
        item = self._get(f.get("id"), "pull")
        if item is None:
            return self.panel.go("/sharing", _flash_error("Plan expired", "Nothing was imported. Plan the pull again."))
        if not f.get("confirm"):
            return self.panel.go("/sharing", _flash_error("Not confirmed", "Tick the confirmation box to import. Nothing was imported."))
        if not self._busy.acquire(blocking=False):
            return self.panel.go("/sharing", _flash_error("Busy", "another sharing operation is running; try again in a moment"))
        try:
            with self._node() as node:
                report = client.pull(node, item["owner"], confirm=lambda plan: _plan_signature(plan) == item["sig"])
        except Exception as exc:  # noqa: BLE001
            return self._fail("Pull failed", exc)
        finally:
            self._busy.release()
        self._drop(f["id"])
        if report.aborted:
            return self.panel.go("/sharing", _flash_error(
                "The owner's offering changed", "It differs from the plan you reviewed, so nothing was imported. Plan again."))
        lines = [f"rejected {r['ref']}: {r['reason']}" for r in report.rejected[:20]]
        lines += [f"you approved {r['ref']} but the owner forgot it: review it in the Inbox (approved) and revoke it if you agree"
                  for r in report.revoke_proposed]
        return self.panel.go("/sharing", {"kind": "warn" if report.rejected else "ok", "title": "Pull finished", "details": [
            ("Stored in quarantine", report.stored), ("Proposals to review", report.proposed),
            ("Unchanged", report.unchanged), ("Forgotten by the owner", report.tombstoned),
            ("Withdrawn proposals", report.withdrawn), ("Rejected", len(report.rejected))], "lines": lines})

    def post_unpair(self, ctx) -> Response:
        f = ctx.request.form
        if not f.get("confirm"):
            return self.panel.go("/sharing", _flash_error("Not confirmed", "Tick the confirmation box to forget the owner."))
        try:
            with self._node() as node:
                result = node.forget_owner(f.get("owner", ""))
        except Exception as exc:  # noqa: BLE001
            return self._fail("Not removed", exc)
        return self.panel.go("/sharing", {"kind": "ok", "title": "Owner forgotten", "details": [
            ("Owner", result["peer_id"]), ("Note", "copies already pulled stay in their quarantine space")]})


# ---------------------------------------------------------------------------------------------- helpers
def _lan() -> str:
    try:
        from ..share.util import detect_lan_address

        return detect_lan_address() or ""
    except Exception:  # noqa: BLE001
        return ""


def _port(text) -> int:
    value = (text or "").strip()
    if not value:
        return DEFAULT_PORT
    if not value.isdigit() or not 1 <= int(value) <= 65535:
        raise ShareError("invalid_port", "the port must be a number between 1 and 65535")
    return int(value)


def _grant_spec_from_form(f) -> dict:
    from ..share.grants import expires_arg

    projects = [p for p in (f.get("projects") or "").replace(",", " ").split() if p]
    prefixes = [line.strip() for line in (f.get("ref_prefixes") or "").splitlines() if line.strip()]
    return {"space": (f.get("space") or "").strip() or None, "projects": projects, "types": f.getlist("types"),
            "ref_prefixes": prefixes, "expires_in": expires_arg(f.get("grant_expires") or None)}


def _plan_signature(plan: dict) -> str:
    rows = [(r["source_id"], r["digest"], r["action"]) for r in plan["rows"]]
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


def _peer_imports(memory, limit: int = 100) -> list:
    """Live sources imported from peers (newest first) with their provenance; read-only."""
    registry, _blobs = memory._corpus()
    registry.refresh()
    latest: dict = {}
    for rec in registry.all_records():
        latest[rec.source_id] = rec
    rows = []
    for rec in latest.values():
        if not rec.external_ref.startswith(PEER_REF_PREFIX) or rec.lifecycle_status == "deleted":
            continue
        prov = rec.provenance if isinstance(rec.provenance, dict) else {}
        rows.append({"source_id": rec.source_id, "ref": rec.external_ref, "type": (rec.custom_meta or {}).get("memory_type") or "?",
                     "peer": str(prov.get("peer") or ""), "peer_label": str(prov.get("peer_label") or ""),
                     "original_ref": str(prov.get("original_ref") or ""), "digest": str(prov.get("digest") or ""),
                     "fetched_at": str(prov.get("fetched_at") or rec.created_at)})
    rows.sort(key=lambda r: (r["fetched_at"], r["source_id"]), reverse=True)
    return rows[:limit]


# ---------------------------------------------------------------------------------------------- rendering
def _confirm_form(action: str, csrf: str, hidden: dict, label: str, button: str, *, danger: bool = False,
                  secondary: bool = False) -> Markup:
    inner = join([h('<input type="hidden" name="{}" value="{}">', k, v) for k, v in hidden.items()]
                 + [checkbox("confirm", label, required=True)])
    return form(action, csrf, inner, button=button, danger=danger, secondary=secondary)


def _status_card(view: dict) -> Markup:
    st = view["status"]
    ident = view["ident"]
    state = Markup('<span class="badge ok">ACTIVE</span>') if st["active"] else Markup('<span class="badge bad">OFF</span>')
    reasons = join(h("<li>{}</li>", r) for r in st["reasons"])
    why = h('<p>Why it is off:</p><ul>{}</ul>', reasons) if st["reasons"] else Markup("")
    rows = [("Sharing", state), ("This memory's name for peers", view["label"]),
            ("Peer id", h("<code>{}</code>", ident.peer_id) if ident else "(created the first time you make an invite or join)"),
            ("Certificate fingerprint", h("<code>{}</code>", _short(ident.fingerprint, 16)) if ident else "-"),
            ("Peer content in recall", "on (settings: sharing.import_into_recall)" if st["import_into_recall"]
             else "off (settings: sharing.import_into_recall)")]
    dl = Markup("<dl>" + "".join(str(h("<dt>{}</dt><dd>{}</dd>", k, v)) for k, v in rows) + "</dl>")
    serve = h('<p>Serving stays a terminal action; the panel never opens a network listener. To let paired peers connect '
              '(LAN only, time-boxed), run on this machine:</p><pre>{}</pre>'
              '<p class="hint">Start it before you give out an invite; stop it with Ctrl+C. Details: '
              'docs/runbooks/peer-sharing.md.</p>', view["serve"])
    return h('<section class="card" aria-label="status"><h2>Status</h2>{}{}{}</section>', dl, why, serve)


def _invite_form(view: dict, csrf: str) -> Markup:
    inner = join([
        Markup('<div class="row">'),
        field("host", "Address in the invite", view["lan"], maxlength=253, placeholder="detected LAN address",
              hint="The address the other machine will connect to (private LAN address)."),
        field("port", "Port", str(DEFAULT_PORT), maxlength=5, hint="Where you run share serve."),
        field("label", "Name the other machine shows for you", view["label"], maxlength=40),
        select("expires", INVITE_EXPIRIES, "10m", label="Invite valid for"),
        Markup("</div>"),
        h('<h3>Offer access with the invite (optional)</h3><p class="hint">Leave empty to offer nothing; you can grant '
          'later with a preview.</p>'),
        Markup('<div class="row">'),
        field("space", "Knowledge space", "", maxlength=64, placeholder="ks-shared"),
        field("projects", "Projects (space separated)", "", maxlength=200),
        select("grant_expires", GRANT_EXPIRIES, "30d", label="Grant lasts"),
        Markup("</div>"),
        _types_boxes(), _prefix_box(),
    ])
    return h('<section class="card" aria-label="invite"><h2>Invite a machine (you are the owner)</h2>'
             '<p>Creates a one-time <code>zm1:</code> code. It is shown <strong>once</strong>, never saved, never in a URL or log.</p>{}</section>',
             form("/sharing/invite", csrf, inner, button="Create invite"))


def _types_boxes(selected=()) -> Markup:
    return h('<fieldset><legend>Only these memory types (none ticked = all types)</legend>{}</fieldset>',
             join(checkbox("types", t, value=t, checked=t in selected) for t in MEMORY_TYPES))


def _prefix_box(value: str = "") -> Markup:
    return textarea("ref_prefixes", "Only references starting with (one per line, mem:// or file://)", value, rows=2,
                    hint="Optional. Example: mem://rule/")


def _peers_card(view: dict, csrf: str) -> Markup:
    peers, grants = view["peers"], view["grants"]
    if not peers:
        return h('<section class="card" aria-label="peers"><h2>Paired peers</h2><p class="muted">No peer is paired. '
                 'Create an invite above.</p></section>')
    parts = [h("<h2>Paired peers</h2>")]
    for peer in peers:
        mine = [g for g in grants if g["peer_id"] == peer["peer_id"]]
        revoked = peer["status"] == "revoked"
        head = [("Label", peer["label"]), ("Peer id", h("<code>{}</code>", peer["peer_id"])),
                ("Fingerprint", h("<code>{}</code>", _short(peer["fingerprint"], 16))), ("Paired", peer["created_at"]),
                ("Last pull", view["last_pull"].get(peer["peer_id"], "never")),
                ("Status", join([Markup('<span class="badge bad">revoked</span> '), peer["revoked_at"]]) if revoked
                 else Markup('<span class="badge ok">active</span>'))]
        dl = Markup("<dl>" + "".join(str(h("<dt>{}</dt><dd>{}</dd>", k, v)) for k, v in head) + "</dl>")
        rows = []
        for g in mine:
            scope = ", ".join(([g["space"]] if g["space"] else []) + [f"project:{p}" for p in g["projects"]])
            action = Markup("")
            if g["state"] == "active":
                action = _confirm_form("/sharing/revoke-grant", csrf, {"peer": peer["peer_id"], "grant_id": g["grant_id"]},
                                       "I confirm: revoke this grant", "Revoke grant", danger=True)
            rows.append((g["grant_id"], scope, ", ".join(g["types"]) or "all types", ", ".join(g["ref_prefixes"]) or "-",
                         g["expires_at"] or "never", g["state"], action))
        grants_table = table(["Grant", "Space / project", "Types", "Ref prefixes", "Expires", "State", ""], rows,
                             empty="No grants: this peer can read nothing.", wrap_cols=(1, 3))
        kill = Markup("") if revoked else _confirm_form(
            "/sharing/revoke-peer", csrf, {"peer": peer["peer_id"]}, "I confirm: stop trusting this machine now",
            "Revoke this peer", danger=True)
        parts.append(h('<div class="card" aria-label="peer">{}<h3>Grants</h3>{}{}</div>', dl, grants_table, kill))
    return h('<section aria-label="peers">{}</section>', join(parts))


def _grant_form(view: dict, csrf: str) -> Markup:
    active = [p for p in view["peers"] if p["status"] == "active"]
    if not active:
        return Markup("")
    options = [(p["peer_id"], f"{p['label']} ({p['peer_id'][:8]})") for p in active]
    inner = join([
        select("peer", options, label="Peer"),
        Markup('<div class="row">'),
        field("space", "Knowledge space", "", maxlength=64, placeholder="ks-shared"),
        field("projects", "Projects (space separated)", "", maxlength=200),
        select("grant_expires", GRANT_EXPIRIES, "30d", label="Grant lasts"),
        Markup("</div>"), _types_boxes(), _prefix_box(),
    ])
    return h('<section class="card" aria-label="grant"><h2>Let a peer read more</h2>'
             '<p>You will see exactly which sources the peer could read before anything is granted. '
             'Private memory can never be shared.</p>{}</section>',
             form("/sharing/grant-preview", csrf, inner, button="Preview what would be shared", secondary=True))


def _join_card(view: dict, csrf: str) -> Markup:
    join_form = form("/sharing/join", csrf, join([
        textarea("code", "Invite code (zm1:...)", "", rows=3, required=True,
                 hint="Paste the code the owner gave you. It is sent once to the owner's address and not kept here."),
        field("label", "Name the owner shows for this machine", view["label"], maxlength=40)]),
        button="Join")
    rows = []
    for o in view["owners"]:
        pull = _confirm_form_plain("/sharing/pull-plan", csrf, {"owner": o["peer_id"]}, "Plan a pull")
        unpair = _confirm_form("/sharing/unpair", csrf, {"owner": o["peer_id"]}, "I confirm: forget this owner", "Forget", danger=True)
        rows.append((o["label"], h("<code>{}</code>", o["peer_id"]), f"{o['host']}:{o['port']}", o["added_at"],
                     view["owner_pull"].get(o["peer_id"], "never"), pull, unpair))
    owners = table(["Owner", "Peer id", "Address", "Joined", "Last pull", "", ""], rows,
                   empty="You have not joined an owner yet.", wrap_cols=())
    return h('<section class="card" aria-label="join"><h2>Receive from another machine (you are the peer)</h2>{}'
             '<h3>Owners you can pull from</h3>{}<p class="hint">Pulling first shows a plan; nothing is imported until you '
             'confirm it. Imported text is stored as untrusted reference; rules, decisions and gotchas become proposals.</p></section>',
             join_form, owners)


def _confirm_form_plain(action: str, csrf: str, hidden: dict, button: str) -> Markup:
    inner = join([h('<input type="hidden" name="{}" value="{}">', k, v) for k, v in hidden.items()])
    return form(action, csrf, inner, button=button, secondary=True)


def _imports_card(view: dict) -> Markup:
    rows = [(r["type"], h("<code>{}</code>", r["ref"]), f"{r['peer_label']} ({r['peer'][:8]})", h("<code>{}</code>", r["original_ref"]),
             _short(r["digest"], 12), r["fetched_at"], Markup('<span class="badge warn">untrusted reference</span>'))
            for r in view["imports"]]
    t = table(["Type", "Stored as", "From peer", "Original ref", "Digest", "Fetched", "Label"], rows,
              empty="Nothing has been imported from a peer yet.", wrap_cols=(1, 3))
    return h('<section class="card" aria-label="imports"><h2>Imported from peers</h2><p class="hint">Read-only quarantine copies. '
             'Never injected into briefs or context; visible to agents only if you enable sharing.import_into_recall and '
             'grant them the quarantine space.</p>{}</section>', t)


def _proposals_card(view: dict) -> Markup:
    props = view["proposals"]
    rows = [(p["memory_type"], p.get("name") or "", (p["text"] or "")[:160], p["id"]) for p in props[:20]]
    t = table(["Type", "Name", "Text", "Proposal"], rows, empty="No pending proposals came from peers.", wrap_cols=(2,))
    forgotten = ""
    if view["forgotten"]:
        items = join(h("<li><code>{}</code> (you approved it; the owner forgot it)</li>", x.get("ref", "")) for x in view["forgotten"])
        forgotten = h('<p>The owner forgot items you had approved. Nothing was deleted; review them in the Inbox (approved) '
                      'and revoke them if you agree:</p><ul>{}</ul>', items)
    return h('<section class="card" aria-label="peer proposals"><h2>Proposals from peers</h2>{}{}'
             '<p><a href="/inbox">Open the Inbox</a> to approve or reject them.</p></section>', t, forgotten)


def _audit_card(view: dict) -> Markup:
    skip = {"at", "op"}
    rows = []
    for ev_ in view["audit"]:
        detail = " ".join(f"{k}={str(v)[:80]}" for k, v in sorted(ev_.items()) if k not in skip and v not in (None, "", {}, []))
        rows.append((ev_["at"], ev_["op"], detail))
    return h('<section class="card" aria-label="audit"><h2>Sharing audit log</h2>{}</section>',
             table(["When", "Event", "Details"], rows, empty="No sharing events yet.", wrap_cols=(2,)))


def _page(view: dict, csrf: str) -> Markup:
    return join([_status_card(view), _invite_form(view, csrf), _peers_card(view, csrf), _grant_form(view, csrf),
                 _join_card(view, csrf), _imports_card(view), _proposals_card(view), _audit_card(view)])


def _invite_view(code: str, host: str, left: int, offered: int, nonce: str) -> Markup:
    warn = h('<div class="flash warn" role="alert"><h2>This code is a secret</h2><p>Anyone who has it before it is used or expires can '
             'pair with this memory. It is shown only on this page: it is not stored, not logged and not in the address bar. '
             'Hand it over through a channel you trust, then close this page.</p></div>')
    code_box = h('<label for="invite-code">Invite code (valid about {} minutes, one use)</label>'
                 '<textarea id="invite-code" readonly rows="5" spellcheck="false">{}</textarea>'
                 '<p><button type="button" id="copy-invite" hidden>Copy to clipboard</button> '
                 '<span class="hint">Without JavaScript: click the box, select all and copy.</span></p>',
                 max(1, left // 60), code)
    steps = h('<p>It points at <code>{}</code> and offers {}.</p><p>Next: keep <code>zero-mem share serve</code> running in a terminal on this machine; '
              'on the other machine run <code>zero-mem share join &lt;code&gt;</code> or paste it into its control panel.</p>'
              '<p><a href="/sharing">Back to Sharing</a></p>',
              host, "NO access (grant it later with a preview)" if not offered else f"{offered} grant(s)")
    script = Markup(f'<script nonce="{e(nonce)}">{COPY_SCRIPT}</script>')
    return h('<section class="card" aria-label="invite code">{}{}{}</section>{}', warn, code_box, steps, script)


def _spec_lines(spec: dict) -> list:
    lines = []
    if spec["space"]:
        lines.append(("Knowledge space", spec["space"]))
    if spec["projects"]:
        lines.append(("Projects", ", ".join(spec["projects"])))
    lines.append(("Types", ", ".join(spec["types"]) or "all types"))
    lines.append(("Reference prefixes", ", ".join(spec["ref_prefixes"]) or "any"))
    lines.append(("Lasts", "never expires" if spec["expires_in"] is None else
                  (f"{spec['expires_in'] // 86400} day(s)" if spec["expires_in"] >= 86400 else f"{spec['expires_in'] // 60} min")))
    return lines


def _grant_preview(item: dict, key: str, csrf: str) -> Markup:
    pv, spec = item["preview"], item["spec"]
    dl = Markup("<dl>" + "".join(str(h("<dt>{}</dt><dd>{}</dd>", k, v)) for k, v in
                                 [("Peer", f"{item['label']} ({item['peer'][:8]})")] + _spec_lines(spec)) + "</dl>")
    by_type = ", ".join(f"{t}: {n}" for t, n in sorted(pv["by_type"].items())) or "nothing"
    summary = h('<p><strong>{}</strong> source(s) would become readable ({} bytes). By type: {}.</p>', pv["sources"], pv["bytes"], by_type)
    omitted = ""
    if pv["omitted"]:
        omitted = h('<p class="hint">Never served (not counted): {}.</p>', ", ".join(f"{k}: {v}" for k, v in sorted(pv["omitted"].items())))
    refs = table(["Type", "Reference", "Size"], [(r["memory_type"], h("<code>{}</code>", r["ref"]), r["size"]) for r in pv["refs"]],
                 empty="No source matches: the peer would read nothing.", wrap_cols=(1,))
    more = h('<p class="hint">Showing the first {} of {}.</p>', len(pv["refs"]), pv["sources"]) if pv["sources"] > len(pv["refs"]) else ""
    confirm = _confirm_form("/sharing/grant-confirm", csrf, {"id": key},
                            "I understand the peer can copy these sources and I cannot recall the copies", "Grant access")
    return h('<section class="card" aria-label="grant preview"><h2>What this grant allows</h2>{}{}{}{}{}{}'
             '<p><a href="/sharing">Cancel</a> (nothing has been granted yet)</p></section>', dl, summary, omitted, refs, more, confirm)


def _pull_plan(item: dict, key: str, csrf: str) -> Markup:
    plan = item["plan"]
    rows = [(r["action"] + (f" ({r['reason']})" if r["reason"] else ""), r["memory_type"], r["size"], h("<code>{}</code>", r["ref"]))
            for r in plan["rows"][:MAX_PLAN_ROWS]]
    t = table(["Action", "Type", "Size", "Reference"], rows, empty="The owner offers nothing (or has granted you nothing).",
              wrap_cols=(3,))
    summary = ", ".join(f"{k}: {v}" for k, v in sorted(plan["summary"].items())) or "nothing offered"
    more = h('<p class="hint">Showing the first {} of {} rows.</p>', MAX_PLAN_ROWS, len(plan["rows"])) if len(plan["rows"]) > MAX_PLAN_ROWS else ""
    note = h('<p>Imported text is stored as <strong>untrusted reference</strong> in a quarantine space; rules, decisions and gotchas '
             'become <strong>proposals</strong> you approve in the Inbox. Nothing is imported until you confirm.</p>')
    confirm = _confirm_form("/sharing/pull-confirm", csrf, {"id": key}, "Import exactly this plan", "Import")
    return h('<section class="card" aria-label="pull plan"><h2>Pull plan from {}</h2><p>Plan: {}; {} source(s), {} bytes.</p>{}{}{}{}'
             '<p><a href="/sharing">Cancel</a> (nothing has been imported yet)</p></section>',
             item["label"], summary, plan["sources"], plan["bytes"], t, more, note, confirm)
