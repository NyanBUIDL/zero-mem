"""Controller of the control panel: routes, form handling and the calls into the existing zero-mem APIs.

There is NO new write path here. Every mutation goes through the same code the CLI uses:

* add / ingest ........ ``Memory._owner_add`` / ``Memory._owner_ingest`` (the owner entry points of ``zero-mem add|ingest``)
* proposals ........... ``zero_mem.learning.Reviewer`` (approve / reject / revoke / expire)
* forget .............. ``Memory.forget``
* agents and grants ... ``zero_mem.provisioning.Provisioner``
* settings ............ the validated ``zero_mem.learning_settings`` API (closed schema, atomic write)
* eval ................ ``zero_mem.eval_harness``

Reads of the store (browse, detail, brief preview, audit) are read-only. Every handler returns a :class:`Response`; unexpected
exceptions are caught one level up and shown as a generic error page.
"""
from __future__ import annotations

import contextlib
import getpass
import json
import secrets
import tempfile
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Optional

from .. import eval_harness as eh
from .. import learning_settings as ls
from ..commands_learning import _REASONS as LEARN_REASONS
from ..commands_memory import _hint_for_denied, _reason_text
from ..learning import Reviewer
from ..memory import MAX_INGEST_BYTES, MAX_REF_NAME_CHARS, MEMORY_TYPES, SCOPES, Memory, _Invalid
from ..memory_layout import Layout
from ..provisioning import Provisioner, ProvisioningError, valid_id
from . import data, pages
from .sharing import Sharing
from .forms import safe_upload_name
from .render import Markup, e, flash_html, h, page, url
from .server import MAX_UPLOAD_BYTES, Request, Response, redirect

MAX_PREVIEWS = 6
PREVIEW_TTL = 15 * 60.0
MAX_PREVIEW_FILES = 200
MAX_INGEST_TOTAL = 64 * 1024 * 1024
MAX_FLASHES = 60
MAX_CASES_BYTES = 256 * 1024
MAX_FLASH_LINES = 200
PAGE_SIZE = 50

_PATH_REFUSALS = {
    "DENY_NO_ALLOWED_ROOTS": "No folders are allowed for path ingestion. Start the panel with --allow-root DIR, or upload the file.",
    "DENY_PATH_OUTSIDE_ALLOWLIST": "That path is outside the folders you allowed with --allow-root.",
    "DENY_SYMLINK": "Symlinks are not followed. Use the real path of a regular file or folder.",
    "DENY_PATH_RESERVED": "That path belongs to the memory store itself and cannot be ingested.",
    "PATH_MUST_BE_ABSOLUTE": "The path must be absolute (no ~ and no relative path).",
    "PATH_NOT_FOUND": "No such file or folder.",
    "UNSUPPORTED_PATH_TYPE": "Only regular files and folders can be ingested.",
    "INVALID_ARGUMENTS": "That path is not valid.",
}


class PanelConfigError(ValueError):
    """The panel's startup configuration is unusable (message is safe to print)."""


def _operator() -> str:
    try:
        name = getpass.getuser() or "operator"
    except Exception:  # noqa: BLE001
        name = "operator"
    return f"{name}@ui"[:64]


class Panel:
    """State and handlers of one running control panel."""

    def __init__(self, layout: Layout, profile: str, allow_roots=(), *, operator: Optional[str] = None) -> None:
        from src.integration.m6w.pathguard import PathGuard, RootsConfigError, normalize_roots

        if not valid_id(profile):
            raise PanelConfigError("the profile must match [A-Za-z0-9][A-Za-z0-9._-]{0,63}")
        try:
            roots = normalize_roots(list(allow_roots))
        except RootsConfigError as exc:
            raise PanelConfigError(str(exc)) from None
        self.layout = layout
        self.profile = profile
        self.operator = operator or _operator()
        reserved = [layout.data_root, layout.corpus_root, layout.memory_stream.parent, layout.derived_db.parent]
        self.guard = PathGuard(roots, reserved)
        self.roots = [lexical for lexical, _real in roots]
        self._flashes: "OrderedDict[str, dict]" = OrderedDict()
        self._previews: "OrderedDict[str, dict]" = OrderedDict()
        self._lock = threading.Lock()
        self.sharing = Sharing(self)
        self._get: dict[str, Callable] = {
            "/": self.get_overview, "/inbox": self.get_inbox, "/add": self.get_add, "/ingest": self.get_ingest,
            "/ingest/preview": self.get_preview, "/search": self.get_search, "/source": self.get_source,
            "/brief": self.get_brief, "/agents": self.get_agents, "/settings": self.get_settings,
            "/eval": self.get_eval, "/audit": self.get_audit,
        }
        share_get, share_post = self.sharing.routes()
        self._get.update(share_get)
        self._post: dict[str, Callable] = {
            "/add": self.post_add, "/ingest/preview": self.post_ingest_preview, "/ingest/confirm": self.post_ingest_confirm,
            "/inbox/approve": self.post_approve, "/inbox/reject": self.post_reject, "/inbox/revoke": self.post_revoke,
            "/inbox/expire": self.post_expire, "/forget": self.post_forget, "/agents/add": self.post_agent_add,
            "/agents/grant-read": self.post_grant_read, "/agents/grant-write": self.post_grant_write,
            "/agents/revoke": self.post_agent_revoke, "/settings/save": self.post_settings_save,
            "/settings/override": self.post_override, "/settings/unset": self.post_unset, "/settings/kill": self.post_kill,
            "/eval/safety": self.post_eval_safety, "/eval/run": self.post_eval_run,
        }
        self._post.update(share_post)

    # ------------------------------------------------------------------------------------------ plumbing
    def route(self, request: Request, nonce: str, csrf: str) -> Response:
        table = self._post if request.method == "POST" else self._get
        handler = table.get(request.path)
        if handler is None:
            if request.path in (self._get if request.method == "POST" else self._post):
                return Response(status=405, body=page("Method not allowed", h("<p>Use the page's own form.</p>"),
                                                      nonce=nonce, active=""))
            return Response(status=404, body=page("Not found", h('<p>No such page.</p>'), nonce=nonce, active=""))
        ctx = _Ctx(self, request, nonce, csrf)
        return handler(ctx)

    @contextlib.contextmanager
    def memory(self, profile: Optional[str] = None):
        who = profile or self.profile
        if not valid_id(who):
            raise _Bad("invalid_profile")
        mem = Memory(who, self.layout, channel="ui")
        try:
            yield mem
        finally:
            mem.close()

    def reviewer(self) -> Reviewer:
        return Reviewer(self.layout, operator=self.operator, channel="ui")

    def provisioner(self) -> Provisioner:
        return Provisioner(self.layout, operator=self.operator)

    def log_error(self, where: str, exc: BaseException) -> None:
        """One generic line on the terminal (exception class only: never a message that could carry a secret)."""
        import sys

        print(f"zero-mem ui: {where} failed ({type(exc).__name__})", file=sys.stderr, flush=True)

    def put_flash(self, flash: dict) -> str:
        key = secrets.token_urlsafe(12)
        with self._lock:
            self._flashes[key] = flash
            while len(self._flashes) > MAX_FLASHES:
                self._flashes.popitem(last=False)
        return key

    def get_flash(self, key: Optional[str]) -> Optional[dict]:
        if not key:
            return None
        with self._lock:
            return self._flashes.get(key)

    def go(self, path: str, flash: dict, **params) -> Response:
        return redirect(url(path, flash=self.put_flash(flash), **params))

    def pending_count(self) -> Optional[int]:
        try:
            return len(self.reviewer().list("pending"))
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------------------------------ overview
    def get_overview(self, ctx) -> Response:
        from ..commands_doctor import collect

        try:
            with self.memory() as mem:
                inventory = data.inventory(mem)
        except Exception:  # noqa: BLE001
            inventory = {"total": 0, "forgotten": 0, "by_type": {}, "by_scope": {}}
        try:
            from ..memory_health import snapshot

            runtime = snapshot()
        except Exception:  # noqa: BLE001
            runtime = None
        try:
            agents = self.provisioner().list_agents()
        except Exception:  # noqa: BLE001
            agents = []
        pending = self.pending_count()
        body = pages.overview({
            "data_root": str(self.layout.data_root), "profile": self.profile, "inventory": inventory, "runtime": runtime,
            "settings": ls.load_settings(), "settings_path": str(ls.settings_path()), "agents": agents,
            "pending": "?" if pending is None else pending, "writes": data.last_writes(self.layout),
            "doctor": collect(),
        })
        return ctx.render("Overview", body, "/", badge=pending)

    # ------------------------------------------------------------------------------------------ inbox
    def get_inbox(self, ctx) -> Response:
        status = ctx.request.query.get("status", "pending")
        if status not in pages.STATUS_TABS:
            status = "pending"
        rows = self.reviewer().list(status=status)
        pending = rows if status == "pending" else None
        return ctx.render("Inbox: proposals", pages.inbox(rows[:200], status, ctx.csrf, 0), "/inbox",
                          badge=len(pending) if pending is not None else None)

    def post_approve(self, ctx) -> Response:
        f = ctx.request.form
        if not f.get("approve"):
            return self.go("/inbox", _err("Approval not confirmed", "Tick the confirmation box to approve."))
        edit = f.get("edit")
        pid = f.get("id", "")
        reviewer = self.reviewer()
        current = reviewer.show(pid)
        if current is not None and edit is not None and edit.strip() == current["text"].strip():
            edit = None  # unchanged text is not an edit
        name = (f.get("name") or "").strip() or None
        result = reviewer.approve(pid, edit=edit, name=name)
        if result.ok:
            details = [("Proposal", result.proposal_id), ("Result", result.write_status or ""),
                       ("Source id", result.source_id), ("Reference", result.external_ref), ("Version", result.version)]
            if result.superseded:
                details.append(("Note", "this replaced the previous version"))
            return self.go("/inbox", {"kind": "ok", "title": "Approved: committed to memory", "details": details})
        return self.go("/inbox", _review_error(result))

    def post_reject(self, ctx) -> Response:
        f = ctx.request.form
        result = self.reviewer().reject(f.get("id", ""), (f.get("reason") or "").strip() or None)
        if result.ok:
            return self.go("/inbox", {"kind": "ok", "title": "Rejected", "details": [("Proposal", result.proposal_id)]})
        return self.go("/inbox", _review_error(result))

    def post_revoke(self, ctx) -> Response:
        f = ctx.request.form
        if not f.get("approve"):
            return self.go("/inbox", _err("Revoke not confirmed", "Tick the confirmation box to revoke."))
        result = self.reviewer().revoke(f.get("ref", ""), (f.get("reason") or "").strip() or None)
        if result.ok:
            return self.go("/inbox", {"kind": "ok", "title": "Revoked", "details": [
                ("Reference", result.external_ref), ("Source id", result.source_id),
                ("Note", "raw bytes are kept; the memory is no longer recalled")]}, status="approved")
        return self.go("/inbox", _review_error(result))

    def post_expire(self, ctx) -> Response:
        result = self.reviewer().expire()
        if not result.ok:
            return self.go("/inbox", _review_error(result))
        detail = result.detail or {}
        lines = [f"expired proposal {pid}" for pid in detail.get("proposals_expired", [])]
        lines += [f"past active TTL (hidden from recall): {i.get('external_ref') or i.get('source_id')}"
                  for i in detail.get("active_hidden", [])]
        return self.go("/inbox", {"kind": "ok", "title": f"TTLs applied: {len(detail.get('proposals_expired', []))} "
                                                         "pending proposal(s) expired", "lines": lines})

    # ------------------------------------------------------------------------------------------ add
    def _target_values(self, f) -> tuple:
        values = {k: (f.get(k) or "").strip() for k in ("memory_type", "scope", "project_id", "name", "profile")}
        values["profile"] = values["profile"] or self.profile
        values["text"] = f.get("text", "")
        errors: dict = {}
        if not valid_id(values["profile"]):
            errors["profile"] = "invalid profile id"
        try:
            Memory._check_target(values["memory_type"] or "fact", values["scope"] or None, values["project_id"] or None)
            Memory._check_name(values["name"] or None, MAX_REF_NAME_CHARS)
        except _Invalid as exc:
            field = "name" if "name" in exc.reason else "project_id"
            errors[field] = _reason_text(exc.reason)
        return values, errors

    def get_add(self, ctx) -> Response:
        return ctx.render("Add to memory", pages.add(self.profile, ctx.csrf), "/add")

    def post_add(self, ctx) -> Response:
        values, errors = self._target_values(ctx.request.form)
        if errors:
            return ctx.render("Add to memory", pages.add(self.profile, ctx.csrf, values, errors), "/add", status=422)
        with self.memory(values["profile"]) as mem:
            result = mem._owner_add(values["text"], values["memory_type"] or "fact", name=values["name"] or None,
                                    scope=values["scope"] or None, project_id=values["project_id"] or None)
        flash = write_flash(result, values["profile"])
        if result.ok:
            return self.go("/add", flash)
        if result.status == "rejected_secret":
            values["text"] = ""  # never echo a rejected credential back into the page
        return ctx.render("Add to memory", pages.add(self.profile, ctx.csrf, values), "/add", status=422,
                          flash=flash_html(flash))

    # ------------------------------------------------------------------------------------------ ingest
    def get_ingest(self, ctx) -> Response:
        return ctx.render("Ingest files", pages.ingest_form(self.profile, ctx.csrf, self.roots, MAX_UPLOAD_BYTES // (1024 * 1024)),
                          "/ingest")

    def _ingest_error(self, ctx, values, errors, message=None) -> Response:
        flash = _err("Cannot preview", message) if message else None
        return ctx.render("Ingest files", pages.ingest_form(
            self.profile, ctx.csrf, self.roots, MAX_UPLOAD_BYTES // (1024 * 1024), values, errors), "/ingest", status=422,
            flash=flash_html(flash))

    def post_ingest_preview(self, ctx) -> Response:
        f = ctx.request.form
        mode = f.get("mode")
        values, errors = self._target_values(f)
        values["path"] = (f.get("path") or "").strip()
        if errors:
            return self._ingest_error(ctx, values, errors)
        target = {"memory_type": values["memory_type"] or "fact", "scope": values["scope"] or None,
                  "project_id": values["project_id"] or None, "name": values["name"] or None, "profile": values["profile"]}
        if mode == "upload":
            upload = ctx.request.files.get("file")
            if upload is None:
                return self._ingest_error(ctx, values, {"file": "Choose a file to upload."})
            try:
                filename = safe_upload_name(upload.filename)
            except Exception as exc:  # noqa: BLE001
                return self._ingest_error(ctx, values, {"file": str(exc)})
            pv = self._preview_upload(filename, upload.content, target)
        elif mode == "path":
            verdict = self.guard.check(values["path"])
            if not verdict.ok:
                return self._ingest_error(ctx, values, {"path": _PATH_REFUSALS.get(verdict.code, "That path cannot be ingested.")})
            pv = self._preview_path(values["path"], verdict.path, target)
        else:
            return self._ingest_error(ctx, values, {}, "Unknown ingest mode.")
        key = self._store_preview(pv)
        return redirect(url("/ingest/preview", id=key))

    def _preview_items(self, items: list, target: dict) -> dict:
        ok = sum(1 for i in items if i["verdict"] == "ok")
        rejected = sum(1 for i in items if i["verdict"] == "rejected")
        return {"items": items, "summary": {"ok": ok, "rejected": rejected, "skipped": len(items) - ok - rejected},
                "target": {**target, "scope": target["scope"] or ("project" if target["memory_type"] == "devlog" else "private")}}

    def _preview_upload(self, filename: str, content: bytes, target: dict) -> dict:
        from src.corpus.detect_kind import detect_kind

        with self.memory(target["profile"]) as mem:
            item = _check_item(mem, filename, content, detect_kind(filename, content))
        pv = self._preview_items([item], target)
        pv.update(mode="upload", filename=filename, content=content, source_label=f"upload: {filename}")
        return pv

    def _preview_path(self, raw: str, resolved: Path, target: dict) -> dict:
        from src.corpus.detect_kind import IngestPathError, iter_ingestable

        items: list = []
        with self.memory(target["profile"]) as mem:
            try:
                walk = iter_ingestable(resolved, allow_roots=self.guard.real_roots, max_bytes=MAX_INGEST_BYTES,
                                       max_files=MAX_PREVIEW_FILES)
            except IngestPathError as exc:
                items.append({"name": str(resolved.name), "verdict": "skipped", "reason": str(exc) or "invalid_path"})
                walk = None
            total = 0
            for item in (walk or []):
                rel, _path, kind = item
                try:
                    content = item.read_bytes()
                except Exception as exc:  # noqa: BLE001
                    items.append({"name": rel, "kind": kind, "verdict": "skipped", "reason": getattr(exc, "reason", "unreadable")})
                    continue
                total += len(content)
                if total > MAX_INGEST_TOTAL:
                    items.append({"name": rel, "kind": kind, "verdict": "skipped", "reason": "max_total_bytes_reached"})
                    break
                items.append(_check_item(mem, rel, content, kind))
            if walk is not None:
                items.extend({"name": s.relative_name, "verdict": "skipped", "reason": s.reason} for s in walk.skipped)
        pv = self._preview_items(items, target)
        pv.update(mode="path", path=raw, source_label=f"path: {raw}")
        return pv

    def _store_preview(self, pv: dict) -> str:
        key = secrets.token_urlsafe(16)
        pv["id"] = key
        pv["at"] = time.monotonic()
        with self._lock:
            self._prune_previews()
            self._previews[key] = pv
            while len(self._previews) > MAX_PREVIEWS:
                self._previews.popitem(last=False)
        return key

    def _prune_previews(self) -> None:
        now = time.monotonic()
        for key in [k for k, v in self._previews.items() if now - v["at"] > PREVIEW_TTL]:
            self._previews.pop(key, None)

    def get_preview(self, ctx) -> Response:
        with self._lock:
            self._prune_previews()
            pv = self._previews.get(ctx.request.query.get("id", ""))
        if pv is None:
            return ctx.render("Ingest preview", h('<div class="card"><p>This preview has expired or was already used.</p>'
                                                  '<p><a href="/ingest">Start again</a></p></div>'), "/ingest", status=404)
        return ctx.render("Ingest preview", pages.ingest_preview(pv, ctx.csrf), "/ingest")

    def post_ingest_confirm(self, ctx) -> Response:
        f = ctx.request.form
        if not f.get("approve"):
            return self.go("/ingest", _err("Ingest not confirmed", "Tick the confirmation box on the preview page."))
        with self._lock:
            self._prune_previews()
            pv = self._previews.pop(f.get("id", ""), None)  # single use
        if pv is None:
            return self.go("/ingest", _err("Preview expired", "Preview again; previews are single-use and expire after 15 minutes."))
        t = pv["target"]
        with self.memory(t["profile"]) as mem:
            if pv["mode"] == "upload":
                report = mem._owner_ingest(pv["content"], filename=pv["filename"], memory_type=t["memory_type"],
                                           scope=t["scope"], project_id=t["project_id"], name=t["name"])
            else:
                verdict = self.guard.check(pv["path"])  # re-checked: the file system may have changed since the preview
                if not verdict.ok:
                    return self.go("/ingest", _err("Path refused", _PATH_REFUSALS.get(verdict.code, "That path cannot be ingested.")))
                report = mem._owner_ingest(verdict.path, memory_type=t["memory_type"], scope=t["scope"],
                                           project_id=t["project_id"], name=t["name"], allow_roots=self.guard.real_roots,
                                           max_files=MAX_PREVIEW_FILES, max_total_bytes=MAX_INGEST_TOTAL)
        return self.go("/ingest", ingest_flash(report, t))

    # ------------------------------------------------------------------------------------------ browse
    def _search_query(self, query: dict) -> dict:
        q = {k: (query.get(k) or "").strip() for k in ("q", "type", "scope", "project", "profile")}
        q["profile"] = q["profile"] or self.profile
        return q

    def get_search(self, ctx) -> Response:
        q = self._search_query(ctx.request.query)
        try:
            page_no = max(1, min(int(ctx.request.query.get("page", "1")), 200))
        except ValueError:
            page_no = 1
        d: dict = {"query": q, "rows": [], "error": None, "page": None, "more": False, "note": ""}
        if not valid_id(q["profile"]):
            d["error"] = "Invalid profile id."
        elif q["type"] and q["type"] not in MEMORY_TYPES or q["scope"] and q["scope"] not in SCOPES:
            d["error"] = "Unknown type or scope."
        elif q["project"] and not valid_id(q["project"]):
            d["error"] = _reason_text("invalid_project_id")
        else:
            with self.memory(q["profile"]) as mem:
                if q["q"]:
                    d.update(self._do_recall(mem, q))
                else:
                    rows = [r for r in data.live_rows(mem, readable_only=True)
                            if (not q["type"] or r.memory_type == q["type"]) and (not q["scope"] or r.scope == q["scope"])
                            and (not q["project"] or r.project_id == q["project"])]
                    start = (page_no - 1) * PAGE_SIZE
                    d["rows"] = [{"source_id": r.source_id, "ref": r.external_ref, "type": r.memory_type, "scope": r.scope,
                                  "version": r.version, "score": None,
                                  "text": "(expired by active TTL)" if r.expired else ""} for r in rows[start:start + PAGE_SIZE]]
                    d.update(page=page_no, more=len(rows) > start + PAGE_SIZE, note=f" of {len(rows)} source(s)")
        return ctx.render("Browse and search", pages.search(d, ctx.csrf), "/search", status=400 if d["error"] else 200)

    def _do_recall(self, mem: Memory, q: dict) -> dict:
        result = mem.recall(q["q"], memory_types=[q["type"]] if q["type"] else None, limit=50,
                            project_id=q["project"] or None)
        if result.status in ("invalid", "denied", "error"):
            return {"error": _reason_text(result.reason)}
        registry, _blobs = mem._corpus()
        registry.refresh()
        rows = []
        for hit in result.hits:
            if q["scope"] and hit.scope != q["scope"]:
                continue
            record = registry.get_by_source_id(hit.source_id)
            text = " ".join(hit.text.split())
            rows.append({"source_id": hit.source_id, "ref": hit.external_ref, "type": hit.memory_type, "scope": hit.scope,
                         "version": record.source_version_id if record is not None else None, "score": hit.score,
                         "text": text if len(text) <= 240 else text[:239] + "..."})
        return {"rows": rows}

    def get_source(self, ctx) -> Response:
        sid = ctx.request.query.get("id", "")
        viewer = (ctx.request.query.get("profile") or self.profile).strip()
        if not valid_id(viewer) or not (8 <= len(sid) <= 64 and all(c in "0123456789abcdef" for c in sid)):
            return ctx.render("Source", h('<div class="card"><p>No such source.</p></div>'), "/search", status=404)
        with self.memory(viewer) as mem:
            record = data.latest_record(mem, sid)
            if record is None:
                return ctx.render("Source", h('<div class="card"><p>No such source (or it is not readable as '
                                              '<code>{}</code>).</p></div>', viewer), "/search", status=404)
            forgotten = record.lifecycle_status == "deleted"
            text, size, truncated = (None, 0, False) if forgotten else data.read_blob_text(mem, record)
            d = {"source_id": record.source_id, "ref": record.external_ref,
                 "type": (record.custom_meta or {}).get("memory_type") or "unknown", "scope": data.scope_of(record, mem.shared_space),
                 "profile_id": record.profile_id, "project_id": record.project_id, "space": record.knowledge_space_id,
                 "version": record.source_version_id, "kind": record.kind, "created_at": record.created_at,
                 "status": "forgotten" if forgotten else record.lifecycle_status, "viewer": viewer, "text": text,
                 "size": size, "truncated": truncated, "provenance": {k: str(v) for k, v in (record.provenance or {}).items()}}
        return ctx.render("Source", pages.source_detail(d, ctx.csrf), "/search")

    def post_forget(self, ctx) -> Response:
        f = ctx.request.form
        if not f.get("approve"):
            return self.go("/search", _err("Forget not confirmed", "Tick the confirmation box on the source page."))
        profile = (f.get("profile") or self.profile).strip()
        with self.memory(profile) as mem:
            result = mem.forget((f.get("id") or "").strip())
        if result.ok:
            return self.go("/search", {"kind": "ok", "title": f"Forgotten ({result.status})", "details": [
                ("Reference", result.external_ref), ("Source id", result.source_id),
                ("Note", "the raw bytes are kept; it will not be recalled")]}, profile=profile)
        why = _reason_text(result.reason)
        if result.status == "denied":
            why += "; " + _hint_for_denied(profile, None, None)
        return self.go("/search", _err(f"Not forgotten: {result.status}", why), profile=profile)

    # ------------------------------------------------------------------------------------------ brief
    def get_brief(self, ctx) -> Response:
        qs = ctx.request.query
        q = {"profile": (qs.get("profile") or self.profile).strip(), "project": (qs.get("project") or "").strip(),
             "task": qs.get("task", ""), "max_chars": (qs.get("max_chars") or "").strip()}
        d: dict = {"query": q, "bundle": None, "error": None}
        if "profile" in qs:
            max_chars: Optional[int] = None
            if q["max_chars"]:
                try:
                    max_chars = int(q["max_chars"])
                except ValueError:
                    d["error"] = "The character budget must be a number."
            if not valid_id(q["profile"]):
                d["error"] = "Invalid profile id."
            elif q["project"] and not valid_id(q["project"]):
                d["error"] = _reason_text("invalid_project_id")
            if d["error"] is None:
                with self.memory(q["profile"]) as mem:
                    bundle = mem.brief(q["task"] or None, max_chars=max_chars, project_id=q["project"] or None, preview=True)
                    policy = mem.injection_policy(q["project"] or None)
                if bundle.status in ("invalid", "error"):
                    d["error"] = {"invalid_max_chars": "The character budget must be between 1 and 8000.",
                                  "invalid_project_id": _reason_text("invalid_project_id")}.get(
                        bundle.reason, f"Cannot build the briefing ({bundle.reason}).")
                else:
                    d.update(bundle=bundle.as_dict(), policy=tuple(policy))
        return ctx.render("Brief preview", pages.brief(d), "/brief", status=400 if d["error"] else 200)

    # ------------------------------------------------------------------------------------------ agents
    def get_agents(self, ctx) -> Response:
        return ctx.render("Agents and access", pages.agents(self._agents_data(), ctx.csrf), "/agents")

    def _agents_data(self) -> dict:
        return {"agents": self.provisioner().list_agents(), "operator": self.operator}

    def _agents_error(self, ctx, key: str, message: str) -> Response:
        return ctx.render("Agents and access", pages.agents(self._agents_data(), ctx.csrf, {key: message}), "/agents", status=422)

    def _target_args(self, f, required: bool = True):
        kind, target = (f.get("kind") or "").strip(), (f.get("target") or "").strip()
        if kind not in ("space", "project", ""):
            raise _Bad("unknown target kind")
        if not kind:
            return None, None
        if not target:
            raise _Bad("give a space or project id")
        return (target, None) if kind == "space" else (None, target)

    def post_agent_add(self, ctx) -> Response:
        name = (ctx.request.form.get("profile") or "").strip()
        try:
            result = self.provisioner().add_agent(name)
        except ProvisioningError as exc:
            return self._agents_error(ctx, "add", exc.message)
        return self.go("/agents", {"kind": "ok", "title": f"Agent {result['status']}: {result['profile']}",
                                   "lines": [f"reads {', '.join(result['defaults']['read'])}; writes private only"]})

    def post_grant_read(self, ctx) -> Response:
        f = ctx.request.form
        try:
            space, project = self._target_args(f)
            if space is None and project is None:
                raise _Bad("choose a target kind")
            result = self.provisioner().grant_read((f.get("profile") or "").strip(), space=space, project=project)
        except _Bad as exc:
            return self._agents_error(ctx, "read", str(exc))
        except ProvisioningError as exc:
            return self._agents_error(ctx, "read", exc.message)
        return self.go("/agents", {"kind": "ok", "title": f"Read {result['status']}", "details": [
            ("Agent", result["profile"]), ("Target", f"{result['target_type']}:{result['target_id']}")]})

    def post_grant_write(self, ctx) -> Response:
        f = ctx.request.form
        if not f.get("approve"):
            return self._agents_error(ctx, "write", "Tick 'I approve': granting write access is an operator decision.")
        try:
            space, project = self._target_args(f)
            if space is None and project is None:
                raise _Bad("choose a target kind")
            basis = (f.get("basis") or "").strip() or f"approved in the control panel by {self.operator}"
            result = self.provisioner().grant_write((f.get("profile") or "").strip(), space=space, project=project, basis=basis)
        except _Bad as exc:
            return self._agents_error(ctx, "write", str(exc))
        except ProvisioningError as exc:
            return self._agents_error(ctx, "write", exc.message)
        return self.go("/agents", {"kind": "ok", "title": f"Write access {result['status']}", "details": [
            ("Agent", result["profile"]), ("Target", f"{result['target_type']}:{result['target_id']}"),
            ("Approval", result.get("approval_ref")), ("Operator", self.operator)]})

    def post_agent_revoke(self, ctx) -> Response:
        f = ctx.request.form
        try:
            space, project = self._target_args(f)
            op = (f.get("operation") or "").strip() or None
            result = self.provisioner().revoke((f.get("profile") or "").strip(), space=space, project=project, operation=op)
        except _Bad as exc:
            return self._agents_error(ctx, "revoke", str(exc))
        except ProvisioningError as exc:
            return self._agents_error(ctx, "revoke", exc.message)
        if not result["revoked"]:
            return self.go("/agents", _err("Nothing to revoke", f"{result['profile']} has no grants matching that filter."))
        return self.go("/agents", {"kind": "ok", "title": f"Revoked {len(result['revoked'])} grant(s) from {result['profile']}",
                                   "lines": [f"{g['operation']} {g['target_type']}:{g['target_id']}" for g in result["revoked"]]})

    # ------------------------------------------------------------------------------------------ settings
    def _settings_data(self) -> dict:
        return {"settings": ls.load_settings(), "path": str(ls.settings_path())}

    def get_settings(self, ctx) -> Response:
        return ctx.render("Settings", pages.settings(self._settings_data(), ctx.csrf), "/settings")

    def _render_settings_error(self, ctx, errors: dict, values: Optional[dict] = None) -> Response:
        return ctx.render("Settings", pages.settings(self._settings_data(), ctx.csrf, errors, values), "/settings", status=422)

    def post_settings_save(self, ctx) -> Response:
        f = ctx.request.form
        cfg = ls.load_settings()
        deny = [line.strip() for line in f.get("deny_patterns", "").splitlines() if line.strip()]
        types = f.getlist("injection_types")
        wanted = [
            ("mode", "learning.mode", f.get("mode", cfg.mode), cfg.mode),
            ("max_proposals_per_day", "learning.max_proposals_per_day", f.get("max_proposals_per_day", ""), str(cfg.max_proposals_per_day)),
            ("allow_agent_proposals", "learning.allow_agent_proposals", f.get("allow_agent_proposals", ""), "true" if cfg.allow_agent_proposals else "false"),
            ("proposal_ttl_days", "learning.proposal_ttl_days", f.get("proposal_ttl_days", ""), str(cfg.proposal_ttl_days)),
            ("active_ttl_days", "learning.active_ttl_days", f.get("active_ttl_days", ""), str(cfg.active_ttl_days)),
            ("injection_enabled", "injection.enabled", f.get("injection_enabled", ""), "true" if cfg.injection_enabled else "false"),
            ("injection_max_chars", "injection.max_chars", f.get("injection_max_chars", ""), str(cfg.injection_max_chars)),
            ("injection_types", "injection.types", json.dumps(types), json.dumps(list(cfg.injection_types))),
            ("deny_patterns", "safety.deny_patterns", json.dumps(deny), json.dumps(list(cfg.deny_patterns))),
        ]
        changes = [(field, key, value) for field, key, value, current in wanted if value.strip() != current]
        values = {"mode": f.get("mode", cfg.mode)}
        for field, _key, value, _cur in wanted:
            values[field] = value
        values["injection_types"] = types
        values["deny_patterns"] = "\n".join(deny)
        return self._apply_changes(ctx, changes, values, "Settings saved")

    def _apply_changes(self, ctx, changes: list, values: Optional[dict], title: str) -> Response:
        """Validate every change against the closed schema, then write once (atomic) under the settings lock."""
        path = ls.settings_path()
        errors: dict = {}
        try:
            with ls._settings_lock(path):
                doc = ls.read_raw(path) or {}
                for field, key, value in changes:
                    try:
                        trial = ls.apply_set(doc, key, value)
                        ls.parse_settings(trial)
                    except ls.SettingsError as exc:
                        errors[field] = str(exc)
                        continue
                    doc = trial
                if not errors and changes:
                    ls.write_settings(path, doc)
        except ls.SettingsError as exc:
            errors["file"] = str(exc)
        if errors:
            return self._render_settings_error(ctx, errors, values)
        if not changes:
            return self.go("/settings", {"kind": "ok", "title": "No changes"})
        return self.go("/settings", {"kind": "ok", "title": title, "lines": [key for _f, key, _v in changes]})

    def post_override(self, ctx) -> Response:
        f = ctx.request.form
        kind = f.get("kind", "")
        name = (f.get("name") or "").strip()
        if kind not in ("profile", "project"):
            return self._render_settings_error(ctx, {"override": "choose profile or project"})
        if not name or not valid_id(name):
            return self._render_settings_error(ctx, {"override": "the name must match [A-Za-z0-9][A-Za-z0-9._-]{0,63}"})
        base = f"injection.{kind}s.{name}"
        changes = []
        if f.get("enabled"):
            changes.append(("override", base + ".enabled", f["enabled"]))
        if (f.get("max_chars") or "").strip():
            changes.append(("override", base + ".max_chars", f["max_chars"]))
        if (f.get("types") or "").strip():
            changes.append(("override", base + ".types", f["types"]))
        if not changes:
            return self._render_settings_error(ctx, {"override": "choose at least one field to override"})
        return self._apply_changes(ctx, changes, None, f"Override saved for {kind} {name}")

    def post_unset(self, ctx) -> Response:
        f = ctx.request.form
        kind, name = f.get("kind", ""), (f.get("name") or "").strip()
        if kind not in ("profile", "project") or not name:
            return self._render_settings_error(ctx, {"override": "unknown override"})
        try:
            _cfg, removed = ls.unset_value(f"injection.{kind}s.{name}")
        except ls.SettingsError as exc:
            return self._render_settings_error(ctx, {"file": str(exc)})
        return self.go("/settings", {"kind": "ok" if removed else "warn",
                                     "title": f"Override removed for {kind} {name}" if removed else "No such override"})

    def post_kill(self, ctx) -> Response:
        f = ctx.request.form
        if not f.get("approve"):
            return self.go("/settings", _err("Not confirmed", "Tick the confirmation box to change the kill switch."))
        state = f.get("state")
        if state not in ("on", "off"):
            return self.go("/settings", _err("Unknown state", "Reload the page."))
        try:
            ls.set_value("safety.kill_switch", "true" if state == "on" else "false")
        except ls.SettingsError as exc:
            return self._render_settings_error(ctx, {"file": str(exc)})
        return self.go("/settings", {"kind": "warn" if state == "on" else "ok",
                                     "title": "Kill switch ON: proposals, approvals and injection are stopped"
                                     if state == "on" else "Kill switch OFF"})

    # ------------------------------------------------------------------------------------------ eval and health
    def _eval_data(self) -> dict:
        from ..commands_doctor import collect

        return {"history": eh.read_history(self.layout.data_root, 20), "doctor": collect(), "profile": self.profile}

    def get_eval(self, ctx) -> Response:
        flash = self.get_flash(ctx.request.query.get("flash"))
        result = flash.get("result") if flash else None
        return ctx.render("Eval and health", pages.eval_page(
            self._eval_data(), ctx.csrf, result=result, cases_text=eh.example_text()), "/eval")

    def post_eval_safety(self, ctx) -> Response:
        result = eh.run_safety_suite()
        return self.go("/eval", {"kind": "ok" if result["passed"] else "error", "title": "Safety suite finished",
                                 "result": {"type": "safety", **result}})

    def post_eval_run(self, ctx) -> Response:
        f = ctx.request.form
        text = f.get("cases", "")
        profile = (f.get("profile") or self.profile).strip()
        if len(text.encode("utf-8")) > MAX_CASES_BYTES or not valid_id(profile):
            return ctx.render("Eval and health", pages.eval_page(
                self._eval_data(), ctx.csrf, {"cases": "The cases are too large or the profile is invalid."}, cases_text=text),
                "/eval", status=422)
        with tempfile.TemporaryDirectory(prefix="zero-mem-ui-") as tmp:
            path = Path(tmp) / "cases.jsonl"
            path.write_text(text, encoding="utf-8", newline="\n")
            try:
                cases = eh.load_cases(path)
            except eh.EvalFileError as exc:
                return ctx.render("Eval and health", pages.eval_page(
                    self._eval_data(), ctx.csrf, {"cases": str(exc)}, cases_text=text), "/eval", status=422)
        report = eh.run_cases(cases, profile)
        with contextlib.suppress(Exception):  # the history is a convenience
            eh.append_history(self.layout.data_root, eh.history_row("control-panel.jsonl", report["summary"]))
        return self.go("/eval", {"kind": "ok" if report["summary"]["failed"] == 0 else "warn",
                                 "title": "Cases finished", "result": {"type": "cases", **report}})

    # ------------------------------------------------------------------------------------------ audit
    def get_audit(self, ctx) -> Response:
        try:
            page_no = max(1, min(int(ctx.request.query.get("page", "1")), data.MAX_PAGES))
        except ValueError:
            page_no = 1
        rows, more = data.audit_events(self.layout, page_no)
        return ctx.render("Audit log", pages.audit(rows, page_no, more), "/audit")


# ---------------------------------------------------------------------------------------------- helpers
class _Bad(Exception):
    """Invalid operator input (the message is safe to show)."""


class _Ctx:
    def __init__(self, panel: Panel, request: Request, nonce: str, csrf: str) -> None:
        self.panel, self.request, self.nonce, self.csrf = panel, request, nonce, csrf

    def render(self, title: str, body: Markup, active: str, *, status: int = 200, flash: Optional[Markup] = None,
               badge: Optional[int] = None) -> Response:
        if flash is None:
            stored = self.panel.get_flash(self.request.query.get("flash"))
            flash = flash_html({k: v for k, v in stored.items() if k != "result"}) if stored else None
        return Response(status=status, body=page(title, body, nonce=self.nonce, active=active, flash=flash, badge=badge))


def _err(title: str, message: Optional[str] = None) -> dict:
    return {"kind": "error", "title": title, "lines": [message] if message else []}


def _review_error(result) -> dict:
    reason = result.reason or result.status
    text = LEARN_REASONS.get(reason, reason)
    if result.status == "rejected_secret":
        text = "a credential-like value was detected in the text. Nothing was stored; edit it or reject the proposal."
    elif result.status == "not_pending":
        text = f"this proposal is already {reason}"
    return {"kind": "error", "title": f"{result.status}: not done", "lines": [text]}


def write_flash(result, profile: str) -> dict:
    if result.ok:
        details = [("Result", result.status), ("Reference", result.external_ref), ("Source id", result.source_id),
                   ("Version", result.version), ("Scope", result.scope), ("Units", result.units)]
        return {"kind": "ok", "title": "Saved", "details": [(k, v) for k, v in details if v not in (None, "")]}
    lines = [_reason_text(result.reason)]
    if result.status == "denied":
        lines.append(_hint_for_denied(profile, result.scope, result.project_id))
    if result.status == "rejected_secret":
        lines = ["a credential-like value was detected" + (f" (rule: {', '.join(result.rule_ids)})" if result.rule_ids else "")
                 + ". Nothing was stored."]
    return {"kind": "error", "title": f"Not saved: {result.status}", "lines": lines}


def ingest_flash(report, target: dict) -> dict:
    counts = report.counts
    lines = []
    for res in report.files[:MAX_FLASH_LINES]:
        if res.ok:
            lines.append(f"{res.status}: {res.external_ref} (source {res.source_id})")
        elif res.status == "rejected_secret":
            lines.append(f"rejected {res.name or res.external_ref}: a credential-like value was detected"
                         + (f" (rule: {', '.join(res.rule_ids)})" if res.rule_ids else ""))
        else:
            lines.append(f"{res.status} {res.name or res.external_ref}: {_reason_text(res.reason)}")
    for skip in report.skipped[:MAX_FLASH_LINES]:
        lines.append(f"skipped {skip['name']}: {skip['reason']}")
    summary = ", ".join(f"{counts.get(k, 0)} {k}" for k in
                        ("created", "updated", "unchanged", "rejected_secret", "rejected_content", "invalid", "denied", "error", "skipped")
                        if counts.get(k))
    if report.status in ("denied", "invalid", "error"):
        reason = _reason_text(report.reason)
        if report.status == "denied":
            reason += "; " + _hint_for_denied(target["profile"], target.get("scope"), target.get("project_id"))
        return {"kind": "error", "title": f"Ingest {report.status}", "lines": [reason]}
    return {"kind": "ok" if report.status == "ok" else "warn", "title": f"Ingest report ({report.status}): {summary or 'nothing'}",
            "lines": lines}


def _check_item(mem: Memory, name: str, content: bytes, kind: str) -> dict:
    """One preview row: what the write path's pre-scan would say, without storing anything."""
    base = {"name": name, "kind": kind, "size": len(content)}
    if len(content) > MAX_INGEST_BYTES:
        return {**base, "verdict": "rejected", "reason": _reason_text("content_too_large")}
    if not content:
        return {**base, "verdict": "skipped", "reason": "empty"}
    blocked = mem._preflight(content, kind, [name])
    if blocked is None:
        return {**base, "verdict": "ok"}
    status, reason, rules = blocked
    why = "a credential-like value was detected" + (f" (rule: {', '.join(rules)})" if rules else "") \
        if status == "rejected_secret" else _reason_text(reason)
    return {**base, "verdict": "rejected", "reason": why}
