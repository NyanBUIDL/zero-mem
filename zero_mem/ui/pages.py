"""Page bodies of the control panel: small pure render functions (data in, safe HTML out).

Handlers (``zero_mem.ui.handlers``) gather the data through the existing Memory / Reviewer / Provisioner / settings APIs and
call these. Nothing here touches the store. Every dynamic value is escaped by :mod:`zero_mem.ui.render`.
"""
from __future__ import annotations

from typing import Optional

from ..learning_settings import INJECTION_TYPES, LEARNING_MODES
from ..memory import MEMORY_TYPES, SCOPES
from .render import (
    Markup, checkbox, csrf_field, e, field, form, h, join, select, table, textarea, url,
)

STATUS_TABS = ("pending", "approved", "rejected", "expired", "revoked", "withdrawn", "superseded", "all")


def _state(ok: bool, yes: str, no: str) -> Markup:
    return h('<span class="{}">{}</span>', "ok" if ok else "warn", yes if ok else no)


def _kv(pairs) -> Markup:
    return Markup("<dl>" + "".join(str(h("<dt>{}</dt><dd>{}</dd>", k, v)) for k, v in pairs) + "</dl>")


def _counts(mapping: dict) -> Markup:
    if not mapping:
        return h('<span class="muted">none</span>')
    return join((h('<span class="badge">{} {}</span>', k, v) for k, v in sorted(mapping.items())))


def _profile_field(profile: str, label: str = "Act as profile", error: Optional[str] = None) -> Markup:
    return field("profile", label, profile, hint="The agent profile this action runs as (same as the CLI --profile).",
                 maxlength=64, error=error)


# ------------------------------------------------------------------------------------------------ overview
def overview(d: dict) -> Markup:
    s = d["settings"]
    inj = "ON" if s.injection_enabled else "off"
    runtime = d.get("runtime") or {}
    cards = [
        h('<div class="card"><h2>Memory</h2>{}</div>', _kv([
            ("Data root", h("<code>{}</code>", d["data_root"])),
            ("Acting profile", d["profile"]),
            ("Live sources", d["inventory"]["total"]),
            ("Forgotten", d["inventory"]["forgotten"]),
            ("Last change", runtime.get("last_write") or "none yet"),
        ])),
        h('<div class="card"><h2>By type</h2><p>{}</p><h2>By scope</h2><p>{}</p></div>',
          _counts(d["inventory"]["by_type"]), _counts(d["inventory"]["by_scope"])),
        h('<div class="card"><h2>Learning and injection</h2>{}</div>', _kv([
            ("Learning mode", s.effective_mode),
            ("Pending proposals", h('<a href="/inbox">{}</a>', d["pending"])),
            ("Injection", _state(s.injection_enabled, "on (default)", "off (default)")),
            ("Kill switch", h('<span class="{}">{}</span>', "bad" if s.kill_switch else "ok",
                              "ON: no proposals, approvals or injection" if s.kill_switch else "off")),
            ("Settings file", join([h("<code>{}</code>", d["settings_path"]),
                                   h(' <span class="bad">unusable: {}</span>', s.error) if not s.valid else ""])),
        ])),
    ]
    agents = d["agents"]
    agent_rows = [[a["profile"], _state(a["can_read_shared"], "read", "no read"),
                   _state(a["can_write_shared"], "write", "private only"), len(a["grants"])] for a in agents]
    writes = [[w["at"], w["category"], w["actor"], h("<code>{}</code>", w["target"])] for w in d["writes"]]
    warns = [c for c in d["doctor"]["checks"] if c["status"] in ("FAIL", "WARN")]
    doctor_rows = [[_state(c["status"] != "FAIL", c["status"], c["status"]), c["id"], c["message"]] for c in warns]
    return join([
        Markup('<div class="grid">'), join(cards), Markup("</div>"),
        h("<h2>Agents</h2>{}", table(["Profile", "Shared read", "Shared write", "Grants"], agent_rows,
                                      empty="No agents registered yet (Agents page).")),
        h("<h2>Last writes</h2>{}", table(["When (UTC)", "Kind", "By", "Reference"], writes, empty="No writes yet.")),
        h("<h2>Doctor</h2><p>Overall: <strong>{}</strong></p>{}", d["doctor"]["overall"],
          table(["Status", "Check", "Message"], doctor_rows, empty="No warnings.", wrap_cols=(2,))),
    ])


# ------------------------------------------------------------------------------------------------ inbox
def _proposal_card(p: dict, csrf: str) -> Markup:
    meta = [("Proposer", p["proposer"]), ("Source", p.get("source")), ("Type", p["memory_type"]),
            ("Scope", p["scope"] + (f" / {p['project_id']}" if p.get("project_id") else "")),
            ("Name", p.get("name") or "-"), ("Seen", f"{p.get('seen', 1)}x"), ("Created", p["created_at"]),
            ("Status", p["status"])]
    if p.get("reason"):
        meta.append(("Reason", p["reason"]))
    if p.get("source_id"):
        meta.append(("Source id", h("<code>{}</code>", p["source_id"])))
        meta.append(("Reference", h("<code>{}</code>", p.get("external_ref") or "")))
    evidence = p.get("evidence") or []
    parts = [
        h('<h3><code>{}</code></h3>', p["id"]), _kv(meta),
        h("<h3>Text</h3><pre>{}</pre>", p["text"]),
    ]
    if p.get("final_text"):
        parts.append(h("<h3>Approved text (edited)</h3><pre>{}</pre>", p["final_text"]))
    if evidence:
        parts.append(h("<h3>Evidence</h3><ul>{}</ul>", join(h("<li>{}</li>", ev) for ev in evidence)))
    if p["status"] == "pending":
        approve = join([
            textarea("edit", "Edit before approving (optional)", p["text"], rows=4,
                     hint="Leave unchanged to approve exactly what was proposed."),
            field("name", "Name (optional)", p.get("name") or "", maxlength=128,
                  hint="Approval then versions mem://<type>/<name>."),
            checkbox("approve", "I approve this write (single-write approval, audited)", required=True),
            h('<input type="hidden" name="id" value="{}">', p["id"]),
        ])
        reject = join([
            field("reason", "Reason (optional)", "", maxlength=200),
            h('<input type="hidden" name="id" value="{}">', p["id"]),
        ])
        parts.append(h('<div class="grid"><div>{}</div><div>{}</div></div>',
                       form("/inbox/approve", csrf, approve, button="Approve"),
                       form("/inbox/reject", csrf, reject, button="Reject", secondary=True)))
    elif p["status"] == "approved" and p.get("source_id"):
        revoke = join([
            h('<input type="hidden" name="ref" value="{}">', p["source_id"]),
            field("reason", "Reason (optional)", "", maxlength=200),
            checkbox("approve", "I confirm: stop recalling this memory for every agent", required=True),
        ])
        parts.append(form("/inbox/revoke", csrf, revoke, button="Revoke", danger=True))
    return h('<section class="card" aria-label="proposal">{}</section>', join(parts))


def inbox(proposals: list, status: str, csrf: str, pending: int) -> Markup:
    tabs = join(h('<a class="badge" href="{}"{}>{}</a>', url("/inbox", status=t),
                  Markup(' aria-current="page"') if t == status else "", t) for t in STATUS_TABS)
    expire = form("/inbox/expire", csrf, Markup('<p class="hint">Records every pending proposal older than the TTL as expired '
                                                'and lists approved items that are past their active TTL.</p>'),
                  button="Apply TTLs now", secondary=True)
    body = [h('<p>Status: {}</p>', tabs)]
    if proposals:
        body.extend(_proposal_card(p, csrf) for p in proposals)
    else:
        body.append(h('<p class="muted">No {} proposals.</p>', "" if status == "all" else status))
    body.append(h('<details><summary>Maintenance</summary>{}</details>', expire))
    return join(body)


# ------------------------------------------------------------------------------------------------ add / ingest
def _target_fields(profile: str, values: Optional[dict] = None, errors: Optional[dict] = None) -> Markup:
    v, er = values or {}, errors or {}
    return join([
        Markup('<div class="row">'),
        select("memory_type", MEMORY_TYPES, v.get("memory_type", "fact"), label="Type"),
        select("scope", SCOPES, v.get("scope", "private"), label="Scope",
               hint="shared and project writes need an operator-approved grant for the acting profile."),
        field("project_id", "Project (project scope / devlog)", v.get("project_id", ""), maxlength=64,
              error=er.get("project_id")),
        field("name", "Name (optional)", v.get("name", ""), maxlength=128, error=er.get("name"),
              hint="Same name again = new version."),
        _profile_field(v.get("profile", profile), error=er.get("profile")),
        Markup("</div>"),
    ])


def add(profile: str, csrf: str, values: Optional[dict] = None, errors: Optional[dict] = None) -> Markup:
    v, er = values or {}, errors or {}
    inner = join([
        textarea("text", "Text", v.get("text", ""), required=True, rows=8, error=er.get("text"),
                 hint="Up to 256 KiB. Credential-like values are rejected and never stored."),
        _target_fields(profile, values, errors),
    ])
    return h('<div class="card"><p>Writes through the owner path (like <code>zero-mem add</code>); the rule, decision and '
             'gotcha types are allowed here because you are the owner.</p>{}</div>',
             form("/add", csrf, inner, button="Add to memory"))


def ingest_form(profile: str, csrf: str, roots: list, max_upload_mib: int, values: Optional[dict] = None,
                errors: Optional[dict] = None) -> Markup:
    v, er = values or {}, errors or {}
    if roots:
        root_list = join(h("<li><code>{}</code></li>", r) for r in roots)
        path_part = join([
            h('<p>Allowed roots:</p><ul>{}</ul>', root_list),
            field("path", "Absolute path to a file or folder under an allowed root", v.get("path", ""),
                  maxlength=1024, error=er.get("path"), hint="Symlinks are refused; the panel never lists the file system."),
        ])
    else:
        path_part = Markup('<p class="muted">No folders are allowed for path ingestion. Start the panel with '
                           '<code>zero-mem ui --allow-root DIR</code> to enable it; uploads work without it.</p>')
    path_form = form("/ingest/preview", csrf, join([
        Markup('<input type="hidden" name="mode" value="path">'), path_part, _target_fields(profile, values, errors)]),
        button="Preview path")
    upload_form = form("/ingest/preview", csrf, join([
        Markup('<input type="hidden" name="mode" value="upload">'),
        Markup('<label for="f-file">File</label><input id="f-file" type="file" name="file" required>'),
        h('<p class="hint">Up to {} MiB. The file name must not contain a path.</p>', max_upload_mib),
        (h('<p class="err" role="alert">{}</p>', er["file"]) if er.get("file") else Markup("")),
        _target_fields(profile, values, errors)]), multipart=True, button="Preview upload")
    return join([
        Markup('<p>Nothing is stored until you confirm the preview.</p>'),
        h('<div class="card"><h2>Upload a file</h2>{}</div>', upload_form),
        h('<div class="card"><h2>Ingest by path</h2>{}</div>', path_form),
    ])


def ingest_preview(pv: dict, csrf: str) -> Markup:
    rows = []
    for item in pv["items"]:
        if item["verdict"] == "ok":
            verdict = Markup('<span class="ok">would ingest</span>')
        elif item["verdict"] == "rejected":
            verdict = h('<span class="bad">rejected: {}</span>', item["reason"])
        else:
            verdict = h('<span class="warn">skipped: {}</span>', item["reason"])
        rows.append([h("<code>{}</code>", item["name"]), item.get("kind") or "-", item.get("size", "-"), verdict])
    summary = pv["summary"]
    target = pv["target"]
    confirm = form("/ingest/confirm", csrf, join([
        h('<input type="hidden" name="id" value="{}">', pv["id"]),
        checkbox("approve", f"I confirm: ingest {summary['ok']} item(s) as {target['memory_type']} "
                            f"({target['scope']}{' ' + target['project_id'] if target.get('project_id') else ''}) "
                            f"for profile {target['profile']}", required=True),
    ]), button="Confirm ingest") if summary["ok"] else Markup('<p class="bad">Nothing can be ingested.</p>')
    return join([
        h('<div class="card">{}</div>', _kv([
            ("Source", pv["source_label"]), ("Type", target["memory_type"]), ("Scope", target["scope"]),
            ("Acting profile", target["profile"]), ("Name", target.get("name") or "-"),
            ("Would ingest", summary["ok"]), ("Rejected (secrets / unreadable)", summary["rejected"]),
            ("Skipped", summary["skipped"]),
        ])),
        table(["Item", "Kind", "Bytes", "Verdict"], rows, empty="Nothing found there.", wrap_cols=(0,)),
        Markup('<p class="hint">This is a dry run: the real result (including authorization and versioning) is shown after confirming.</p>'),
        confirm,
    ])


# ------------------------------------------------------------------------------------------------ browse
def search(d: dict, csrf: str) -> Markup:
    q = d["query"]
    type_opts = [("", "any type")] + [(t, t) for t in MEMORY_TYPES]
    scope_opts = [("", "any scope")] + [(s, s) for s in SCOPES]
    controls = Markup(
        '<form method="get" action="/search" class="card">'
        + str(join([
            Markup('<div class="row">'),
            field("q", "Query (empty lists newest sources)", q["q"], type_="search", maxlength=1000),
            select("type", type_opts, q["type"], label="Type"),
            select("scope", scope_opts, q["scope"], label="Scope"),
            field("project", "Project", q["project"], maxlength=64),
            _profile_field(q["profile"], "View as profile"),
            Markup("</div>"),
        ])) + '<button type="submit">Search</button></form>')
    msg = h('<p class="err" role="alert">{}</p>', d["error"]) if d.get("error") else Markup("")
    rows = []
    for r in d["rows"]:
        link = url("/source", id=r["source_id"], profile=q["profile"])
        rows.append([h('<a href="{}"><code>{}</code></a>', link, r["ref"] or r["source_id"][:12]), r["type"], r["scope"],
                     h("<code>{}</code>", r["source_id"][:12]), r.get("version") or "-",
                     r["score"] if r.get("score") is not None else "-", r.get("text") or ""])
    nav = Markup("")
    if d.get("page") is not None:
        prev = h('<a href="{}">Previous</a>', url("/search", **{**q, "page": d["page"] - 1})) if d["page"] > 1 else Markup("")
        nxt = h('<a href="{}">Next</a>', url("/search", **{**q, "page": d["page"] + 1})) if d["more"] else Markup("")
        nav = h('<div class="pager">{} <span class="muted">page {}</span> {}</div>', prev, d["page"], nxt)
    return join([controls, msg, h("<p>{} result(s){}</p>", len(d["rows"]), d.get("note") or ""),
                 table(["Reference", "Type", "Scope", "Source id", "Version", "Score", "Text"], rows,
                       empty="No results.", wrap_cols=(6,)), nav])


def source_detail(d: dict, csrf: str) -> Markup:
    meta = [("Reference", h("<code>{}</code>", d["ref"])), ("Source id", h("<code>{}</code>", d["source_id"])),
            ("Type", d["type"]), ("Scope", d["scope"]), ("Owner profile", d.get("profile_id") or "-"),
            ("Project", d.get("project_id") or "-"), ("Space", d.get("space") or "-"), ("Version", d.get("version") or "-"),
            ("Kind", d["kind"]), ("Status", d["status"]), ("Created", d["created_at"]), ("Viewing as", d["viewer"])]
    prov = [[k, v] for k, v in sorted((d.get("provenance") or {}).items())]
    if d["text"] is None:
        content = h('<p class="muted">Binary or non-text content ({} bytes); recall shows its extracted text.</p>', d["size"])
    else:
        content = h("<pre>{}</pre>{}", d["text"],
                    h('<p class="hint">Truncated to the first 64 KiB of {} bytes.</p>', d["size"]) if d["truncated"] else "")
    forget = form("/forget", csrf, join([
        h('<input type="hidden" name="id" value="{}">', d["source_id"]),
        h('<input type="hidden" name="profile" value="{}">', d["viewer"]),
        checkbox("approve", "I confirm: forget this source (it will not be recalled; the raw bytes are kept)", required=True),
    ]), button="Forget", danger=True) if d["status"] != "forgotten" else Markup("")
    return join([h('<div class="card">{}</div>', _kv(meta)), h("<h2>Content</h2>{}", content),
                 h("<h2>Provenance</h2>{}", table(["Field", "Value"], prov, empty="None recorded.")),
                 h('<h2>Forget</h2><div class="card">{}</div>', forget),
                 h('<p><a href="{}">Back to browse</a></p>', url("/search", profile=d["viewer"]))])


# ------------------------------------------------------------------------------------------------ brief
def brief(d: dict) -> Markup:
    q = d["query"]
    controls = Markup(
        '<form method="get" action="/brief" class="card">' + str(join([
            Markup('<div class="row">'),
            _profile_field(q["profile"], "Agent profile"),
            field("project", "Project", q["project"], maxlength=64),
            field("max_chars", "Character budget (blank = the setting)", q["max_chars"], type_="number"),
            Markup("</div>"),
            textarea("task", "Task the agent is about to do", q["task"], rows=3),
        ])) + '<button type="submit">Preview briefing</button></form>')
    if d.get("error"):
        return join([controls, h('<p class="err" role="alert">{}</p>', d["error"])])
    if d.get("bundle") is None:
        return join([controls, Markup('<p class="muted">Choose a profile and a task to see exactly what '
                                      '<code>Memory.brief(preview=True)</code> returns.</p>')])
    b = d["bundle"]
    pct = 0 if not b["max_chars"] else min(100, round(100 * b["chars"] / b["max_chars"]))
    why = {
        None: "Injection is ON for this profile/project: an agent would receive exactly this text.",
        "injection_disabled": "Injection is OFF for this profile/project (settings): an agent receives nothing; "
                              "this is what WOULD be injected.",
        "kill_switch": "The kill switch is ON: an agent receives nothing; this is what WOULD be injected.",
        "settings_invalid": "The settings file is unusable, so injection is OFF (fail-safe).",
    }.get(b.get("reason"), f"Not injected ({b.get('reason')}).")
    pol = d["policy"]
    items = [[i.get("ref"), i.get("type"), i.get("why") or ""] for i in b["items"]]
    return join([
        controls,
        h('<div class="card"><p><strong class="{}">{}</strong></p><p>{}</p>{}</div>',
          "ok" if b["enabled"] else "warn", "Injection ON" if b["enabled"] else "Injection OFF", why,
          _kv([("Policy (project > profile > global)", f"enabled={pol[0]}, max_chars={pol[1]}, types={', '.join(pol[2])}"),
               ("Status", b["status"]), ("Truncated", "yes" if b["truncated"] else "no")])),
        Markup(f'<h2>Budget</h2><p>{b["chars"]} of {b["max_chars"]} characters used ({pct}%)</p>'
               f'<progress max="100" value="{pct}" aria-label="budget used"></progress>'),
        h("<h2>Briefing text</h2>{}", h("<pre>{}</pre>", b["text"]) if b["text"] else
          Markup('<p class="muted">Empty: nothing matched.</p>')),
        h("<h2>Included</h2>{}", table(["Reference", "Type", "Why"], items, empty="Nothing included.", wrap_cols=(2,))),
        h("<h2>Sections</h2><p>{}</p>", _counts(b["sections"])),
        (h("<h2>Omitted (did not fit)</h2><p>{}</p>", _counts(b["omitted"])) if b["omitted"] else Markup("")),
    ])


# ------------------------------------------------------------------------------------------------ agents
def agents(d: dict, csrf: str, errors: Optional[dict] = None) -> Markup:
    er = errors or {}
    rows = []
    for a in d["agents"]:
        grants = join(h("<div>{} {}:{}{}</div>", g["operation"].lower(), g["target_type"], g["target_id"],
                        "" if g["operation"] != "WRITE" else (" (approved)" if g.get("approval_verified") else " (UNVERIFIED)"))
                      for g in a["grants"]) or h('<span class="muted">none</span>')
        rows.append([a["profile"], _state(a["registered"], "yes", "no"), _state(a["can_read_shared"], "yes", "no"),
                     _state(a["can_write_shared"], "yes", "private only"), grants])
    kind = [("space", "knowledge space"), ("project", "project")]
    add_f = form("/agents/add", csrf, field("profile", "Agent profile name", "", required=True, maxlength=64,
                                           error=er.get("add")), button="Register agent")
    read_f = form("/agents/grant-read", csrf, join([
        field("profile", "Agent", "", required=True, maxlength=64), select("kind", kind, "project", label="Target kind"),
        field("target", "Space or project id", "", required=True, maxlength=64, error=er.get("read")),
    ]), button="Grant read")
    write_f = form("/agents/grant-write", csrf, join([
        field("profile", "Agent", "", required=True, maxlength=64), select("kind", kind, "space", label="Target kind"),
        field("target", "Space or project id", "ks-shared", required=True, maxlength=64, error=er.get("write")),
        field("basis", "Why (recorded in the audit event)", "", maxlength=500),
        checkbox("approve", "I approve this agent writing there (operator approval, audited; recorded as "
                            + d["operator"] + ")", required=True),
    ]), button="Grant write", danger=True)
    revoke_f = form("/agents/revoke", csrf, join([
        field("profile", "Agent", "", required=True, maxlength=64),
        select("kind", [("", "everything")] + kind, "", label="Target kind (blank = all grants)"),
        field("target", "Space or project id (when a kind is chosen)", "", maxlength=64, error=er.get("revoke")),
        select("operation", [("", "read and write"), ("READ", "read only"), ("WRITE", "write only")], "", label="Operation"),
    ]), button="Revoke", secondary=True)
    return join([
        h("<p>Agents can read <code>ks-shared</code> once registered and write only to their own private memory until you "
          "approve more. These are the same operations as <code>zero-mem agents ...</code>.</p>"),
        table(["Agent", "Registered", "Read shared", "Write shared", "Grants"], rows,
              empty="No agents registered yet."),
        h('<div class="grid"><div class="card"><h2>Register agent</h2>{}</div>'
          '<div class="card"><h2>Grant read</h2>{}</div></div>', add_f, read_f),
        h('<div class="grid"><div class="card"><h2>Grant write</h2>{}</div>'
          '<div class="card"><h2>Revoke</h2>{}</div></div>', write_f, revoke_f),
    ])


# ------------------------------------------------------------------------------------------------ settings
def settings(d: dict, csrf: str, errors: Optional[dict] = None, values: Optional[dict] = None) -> Markup:
    s = d["settings"]
    er = errors or {}
    v = values or {}

    def val(key, default):
        return v.get(key, default)

    types_now = set(val("injection_types", list(s.injection_types)) if isinstance(val("injection_types", None), list)
                    else s.injection_types)
    types_boxes = join(checkbox("injection_types", t, checked=t in types_now, value=t) for t in INJECTION_TYPES)
    inner = join([
        h("<h2>Learning</h2>"),
        select("mode", LEARNING_MODES, val("mode", s.mode), label="Mode",
               hint="auto_low_risk is reserved: it behaves exactly like suggest."),
        (h('<p class="err" role="alert">{}</p>', er["mode"]) if er.get("mode") else Markup("")),
        Markup('<div class="row">'),
        field("max_proposals_per_day", "Max proposals per profile per day", str(val("max_proposals_per_day", s.max_proposals_per_day)),
              type_="number", error=er.get("max_proposals_per_day")),
        select("allow_agent_proposals", [("true", "yes"), ("false", "no (only owner proposals)")],
               val("allow_agent_proposals", "true" if s.allow_agent_proposals else "false"), label="Allow agent proposals"),
        field("proposal_ttl_days", "Pending proposal TTL (days)", str(val("proposal_ttl_days", s.proposal_ttl_days)),
              type_="number", error=er.get("proposal_ttl_days")),
        field("active_ttl_days", "Approved item TTL (days, 0 = never)", str(val("active_ttl_days", s.active_ttl_days)),
              type_="number", error=er.get("active_ttl_days")),
        Markup("</div>"),
        h("<h2>Injection (global default)</h2>"),
        Markup('<div class="row">'),
        select("injection_enabled", [("true", "on"), ("false", "off")],
               val("injection_enabled", "true" if s.injection_enabled else "false"), label="Injection"),
        field("injection_max_chars", "Max characters (1-8000)", str(val("injection_max_chars", s.injection_max_chars)),
              type_="number", error=er.get("injection_max_chars")),
        Markup("</div>"),
        h('<fieldset><legend>Types an agent briefing may include</legend>{}</fieldset>', types_boxes),
        (h('<p class="err" role="alert">{}</p>', er["injection_types"]) if er.get("injection_types") else Markup("")),
        h("<h2>Deny patterns</h2>"),
        textarea("deny_patterns", "Regular expressions, one per line", val("deny_patterns", "\n".join(s.deny_patterns)),
                 rows=4, error=er.get("deny_patterns"), hint="A proposal whose text or name matches one is rejected."),
    ])
    overrides = []
    for kind, mapping in (("profile", s.profiles), ("project", s.projects)):
        for name, ov in sorted(mapping.items()):
            body = ov.as_dict()
            rm = form("/settings/unset", csrf, join([
                h('<input type="hidden" name="kind" value="{}">', kind), h('<input type="hidden" name="name" value="{}">', name)]),
                button="Remove", secondary=True)
            overrides.append([kind, name, str(body.get("enabled", "inherit")), body.get("max_chars", "inherit"),
                              ", ".join(body.get("types", [])) or "inherit", rm])
    ov_form = form("/settings/override", csrf, join([
        Markup('<div class="row">'),
        select("kind", [("profile", "profile"), ("project", "project")], "profile", label="Applies to"),
        field("name", "Name", "", required=True, maxlength=64, error=er.get("override")),
        select("enabled", [("", "inherit"), ("true", "on"), ("false", "off")], "", label="Injection"),
        field("max_chars", "Max characters (blank = inherit)", "", type_="number"),
        field("types", "Types (comma separated, blank = inherit)", "", maxlength=200),
        Markup("</div>"),
    ]), button="Save override")
    kill_on = s.kill_switch
    kill = form("/settings/kill", csrf, join([
        h('<input type="hidden" name="state" value="{}">', "off" if kill_on else "on"),
        checkbox("approve", "I confirm: " + ("turn the kill switch OFF and re-enable learning and injection" if kill_on else
                                             "stop all proposals, approvals and injection now"), required=True),
    ]), button="Turn kill switch OFF" if kill_on else "KILL SWITCH: stop learning and injection", danger=not kill_on,
        secondary=kill_on)
    return join([
        h("<p>Settings file: <code>{}</code>{}</p>", d["path"],
          h(' <span class="bad">unusable ({}): fail-safe is active</span>', s.error) if not s.valid else ""),
        (h('<p class="err" role="alert">{}</p>', er["file"]) if er.get("file") else Markup("")),
        h('<div class="danger-zone"><h2>Kill switch</h2><p>Currently <strong>{}</strong>. It stops new proposals, approvals and '
          'injection; reads of existing memory still work.</p>{}</div>', "ON" if kill_on else "off", kill),
        h('<div class="card">{}</div>', form("/settings/save", csrf, inner, button="Save settings")),
        h('<h2>Per-profile and per-project injection</h2>{}', table(
            ["Kind", "Name", "Enabled", "Max chars", "Types", ""], overrides, empty="No overrides.")),
        h('<div class="card">{}</div>', ov_form),
    ])


# ------------------------------------------------------------------------------------------------ eval and health
def eval_page(d: dict, csrf: str, errors: Optional[dict] = None, result: Optional[dict] = None,
              cases_text: str = "") -> Markup:
    er = errors or {}
    hist = [[r.get("at"), r.get("file"), r.get("cases"), r.get("passed"), r.get("failed"),
             "n/a" if r.get("recall") is None else r.get("recall"), r.get("forbidden_hits"), r.get("latency_ms_avg")]
            for r in reversed(d["history"])]
    doctor_rows = [[_state(c["status"] in ("PASS", "OPTIONAL"), c["status"], c["status"]), c["id"], c["message"]]
                   for c in d["doctor"]["checks"]]
    parts = [
        h('<div class="grid"><div class="card"><h2>Safety suite</h2><p>Builds a throw-away store and asserts the harness '
          'invariants (nothing unapproved, expired, forgotten or foreign ever appears; kill switch and budget hold).</p>{}</div>'
          '<div class="card"><h2>Run a cases file</h2>{}</div></div>',
          form("/eval/safety", csrf, Markup(""), button="Run safety suite"),
          form("/eval/run", csrf, join([
              textarea("cases", "Cases (JSON lines)", cases_text, rows=8, required=True, error=er.get("cases"),
                       hint="One JSON object per line: id, task, must_include, must_not_include, profile, project, max_chars."),
              _profile_field(d["profile"], "Default profile"),
          ]), button="Run cases")),
    ]
    if result:
        parts.append(result_html(result))
    parts.append(h("<h2>History</h2>{}", table(["When (UTC)", "File", "Cases", "Passed", "Failed", "Recall", "Forbidden", "Avg ms"],
                                                hist, empty="No eval runs recorded yet.")))
    parts.append(h("<h2>Doctor</h2><p>Overall: <strong>{}</strong></p>{}", d["doctor"]["overall"],
                   table(["Status", "Check", "Message"], doctor_rows, wrap_cols=(2,))))
    return join(parts)


def result_html(result: dict) -> Markup:
    if result["type"] == "safety":
        rows = [[_state(c["ok"], "PASS", "FAIL"), c["name"], c.get("detail") or ""] for c in result["checks"]]
        return h('<h2>Safety suite: {}</h2>{}', "all invariants hold" if result["passed"] else
                 f"{result['failed']} invariant(s) VIOLATED", table(["Result", "Check", "Detail"], rows, wrap_cols=(2,)))
    rows = [[_state(r["passed"], "PASS", "FAIL"), r["id"], f"{r['chars']}/{r['max_chars']}", r["latency_ms"],
             ", ".join(r["missing"]) or "-", ", ".join(r["forbidden"]) or "-", r.get("error") or ""]
            for r in result["cases"]]
    s = result["summary"]
    return h("<h2>Cases: {} of {} passed</h2><p>Recall {}; forbidden hits {}; truncated {}; injection off for {} case(s) "
             "(results show what WOULD be injected).</p>{}", s["passed"], s["cases"],
             "n/a" if s["recall"] is None else s["recall"], s["forbidden_hits"], s["truncated"], s["injection_off_cases"],
             table(["Result", "Case", "Chars", "ms", "Missing", "Forbidden", "Error"], rows, wrap_cols=(4, 5)))


# ------------------------------------------------------------------------------------------------ audit
def audit(rows: list, page: int, more: bool) -> Markup:
    body = table(["When (UTC)", "Category", "Action", "By", "Target", "Detail"],
                 [[r["at"], r["category"], r["action"], r["actor"], h("<code>{}</code>", r["target"]), r["detail"]] for r in rows],
                 empty="No events yet.", wrap_cols=(4, 5))
    prev = h('<a href="{}">Newer</a>', url("/audit", page=page - 1)) if page > 1 else Markup("")
    nxt = h('<a href="{}">Older</a>', url("/audit", page=page + 1)) if more else Markup("")
    return join([body, h('<div class="pager">{} <span class="muted">page {}</span> {}</div>', prev, page, nxt)])
