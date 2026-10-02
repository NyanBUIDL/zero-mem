"""HTML building blocks of the control panel: automatic escaping, the page shell and the stylesheet.

Every value interpolated into markup goes through :func:`e` (``html.escape`` with quotes) unless it is already a
:class:`Markup`. Page code builds fragments with :func:`h` / :func:`join`, so a user-controlled string (memory text,
names, refs, evidence, file names, error text) can never become markup. No JavaScript, no external resource: one inline
stylesheet carries the per-response CSP nonce.
"""
from __future__ import annotations

import html
from typing import Iterable, Optional
from urllib.parse import quote


class Markup(str):
    """A string that is already safe HTML."""

    __slots__ = ()


def e(value) -> Markup:
    """Escape ``value`` for HTML text and double-quoted attributes (``Markup`` passes through)."""
    if isinstance(value, Markup):
        return value
    return Markup(html.escape("" if value is None else str(value), quote=True))


def h(template: str, *args, **kwargs) -> Markup:
    """``str.format`` with every argument escaped. The template itself is trusted markup."""
    return Markup(template.format(*[e(a) for a in args], **{k: e(v) for k, v in kwargs.items()}))


def join(items: Iterable, sep: str = "") -> Markup:
    return Markup(sep.join(e(i) for i in items))


def url(path: str, **params) -> str:
    """A same-origin link with percent-encoded query values (``None`` values are dropped)."""
    query = "&".join(f"{quote(k, safe='')}={quote(str(v), safe='')}" for k, v in params.items() if v not in (None, ""))
    return path + ("?" + query if query else "")


NAV = (
    ("/", "Overview"), ("/inbox", "Inbox"), ("/add", "Add"), ("/ingest", "Ingest"), ("/search", "Browse"),
    ("/brief", "Brief"), ("/agents", "Agents"), ("/settings", "Settings"), ("/eval", "Eval &amp; health"),
    ("/audit", "Audit"),
)

CSS = """
:root{--bg:#f6f6f3;--fg:#1b1b19;--muted:#585853;--card:#fff;--border:#d4d4cc;--accent:#1d58b8;--accent-fg:#fff;
--danger:#b3261e;--danger-bg:#fdecea;--ok:#17653a;--ok-bg:#e8f5ec;--warn:#7a4f00;--warn-bg:#fff4dc;--code:#eeeee8;
--focus:#0b57d0}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#141412;--fg:#ecece6;--muted:#aaaaa2;--card:#1e1e1b;
--border:#3b3b35;--accent:#8ab8ff;--accent-fg:#0c1a31;--danger:#ff9087;--danger-bg:#3a1b19;--ok:#7fdca5;--ok-bg:#16301f;
--warn:#f1c76f;--warn-bg:#352a10;--code:#272721;--focus:#8ab8ff}}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]) button.danger{background:#b3261e;border-color:#ff9087}}
*{box-sizing:border-box}
html{color-scheme:light dark}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.skip{position:absolute;left:-999px}.skip:focus{left:8px;top:8px;background:var(--card);padding:6px 10px;z-index:9}
header{background:var(--card);border-bottom:1px solid var(--border)}
header .bar{max-width:1100px;margin:0 auto;padding:10px 16px}
.brand{font-weight:700;margin-right:12px}
nav ul{list-style:none;margin:6px 0 0;padding:0;display:flex;flex-wrap:wrap;gap:4px 6px}
nav a{display:inline-block;padding:4px 10px;border-radius:6px;color:var(--fg);text-decoration:none;border:1px solid transparent}
nav a:hover{border-color:var(--border)}
nav a[aria-current=page]{background:var(--accent);color:var(--accent-fg)}
main{max-width:1100px;margin:0 auto;padding:16px}
h1{font-size:1.5rem;margin:.2em 0 .6em}h2{font-size:1.15rem;margin:1.4em 0 .5em}h3{font-size:1rem;margin:1em 0 .4em}
a{color:var(--accent)}
:focus-visible{outline:3px solid var(--focus);outline-offset:2px}
.card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:12px 14px;margin:0 0 14px}
.card>h2:first-child{margin-top:0}
progress{width:100%;height:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--border);border-radius:8px;background:var(--card);margin:0 0 14px}
table{border-collapse:collapse;width:100%;min-width:480px}
th,td{text-align:left;vertical-align:top;padding:6px 10px;border-bottom:1px solid var(--border)}
th{font-size:.85rem;color:var(--muted);white-space:nowrap}
tr:last-child td{border-bottom:0}
td.wrap{min-width:240px;max-width:560px;overflow-wrap:anywhere}
code,pre,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.88em}
code{background:var(--code);padding:1px 5px;border-radius:4px;overflow-wrap:anywhere}
pre{background:var(--code);padding:10px 12px;border-radius:6px;overflow-x:auto;white-space:pre-wrap;overflow-wrap:anywhere;margin:0}
form{margin:0}
label{display:block;font-weight:600;margin:10px 0 3px}
label.inline{display:inline-flex;gap:6px;align-items:center;font-weight:400;margin:6px 12px 6px 0}
input[type=text],input[type=number],input[type=search],input[type=file],select,textarea{width:100%;max-width:100%;padding:7px 9px;
border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--fg);font:inherit}
textarea{min-height:6em;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.9rem}
input[type=checkbox]{width:1.1em;height:1.1em}
.row{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:0 12px}
button,.btn{font:inherit;padding:7px 14px;border-radius:6px;border:1px solid var(--accent);background:var(--accent);color:var(--accent-fg);
cursor:pointer;margin-top:10px}
button.secondary{background:transparent;color:var(--accent)}
button.danger{background:var(--danger);border-color:var(--danger);color:#fff}
button.big{font-size:1.15rem;padding:12px 22px}
.badge{display:inline-block;padding:1px 8px;border-radius:99px;border:1px solid var(--border);font-size:.8rem;margin-right:4px}
.ok{color:var(--ok)}.bad{color:var(--danger)}.warn{color:var(--warn)}.muted{color:var(--muted)}
.flash{border-radius:8px;padding:10px 14px;margin:0 0 14px;border:1px solid var(--border)}
.flash.ok{background:var(--ok-bg);border-color:var(--ok)}.flash.error{background:var(--danger-bg);border-color:var(--danger)}
.flash.warn{background:var(--warn-bg);border-color:var(--warn)}
.flash.error h2,.flash.ok h2,.flash.warn h2{color:var(--fg);margin:0 0 4px;font-size:1.05rem}
.flash ul{margin:4px 0 0;padding-left:20px}
.err{color:var(--danger);font-weight:600;margin:4px 0 0}
.hint{color:var(--muted);font-size:.9rem;margin:3px 0 0}
.meter{height:10px;border-radius:5px;background:var(--code);overflow:hidden;border:1px solid var(--border)}
.meter>span{display:block;height:100%;background:var(--accent)}
.danger-zone{border:2px solid var(--danger);border-radius:8px;padding:12px 14px;background:var(--danger-bg)}
dl{margin:0;display:grid;grid-template-columns:max-content 1fr;gap:4px 14px}dt{color:var(--muted)}dd{margin:0;overflow-wrap:anywhere}
.pager{display:flex;gap:12px;align-items:center;margin:8px 0}
footer{max-width:1100px;margin:0 auto;padding:8px 16px 28px;color:var(--muted);font-size:.85rem}
@media (max-width:520px){main{padding:12px}h1{font-size:1.3rem}dl{grid-template-columns:1fr}dt{margin-top:6px}}
""".strip()


def csrf_field(token: str) -> Markup:
    return h('<input type="hidden" name="csrf" value="{}">', token)


def page(title: str, body: Markup, *, nonce: str, active: str = "/", flash: Optional[Markup] = None,
         badge: Optional[int] = None) -> bytes:
    items = []
    for href, label in NAV:
        current = ' aria-current="page"' if href == active else ""
        extra = ""
        if href == "/inbox" and badge:
            extra = h(' <span class="badge">{}</span>', badge)
        items.append(f'<li><a href="{href}"{current}>{label}</a>{extra}</li>')
    doc = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light dark">'
        f"<title>{e(title)} - Zero-Mem control panel</title>"
        f'<style nonce="{e(nonce)}">{CSS}</style></head><body>'
        '<a class="skip" href="#main">Skip to content</a>'
        '<header><div class="bar"><span class="brand">Zero-Mem control panel</span>'
        f'<nav aria-label="Main"><ul>{"".join(items)}</ul></nav></div></header>'
        f'<main id="main"><h1>{e(title)}</h1>{flash or ""}{body}</main>'
        '<footer>Local owner console on 127.0.0.1. Agents must never be given this URL, its cookie or a shell on this machine.'
        "</footer></body></html>"
    )
    return doc.encode("utf-8")


def error_page(title: str, message: str, *, nonce: str) -> bytes:
    body = h('<div class="card"><p>{}</p><p><a href="/">Back to the overview</a></p></div>', message)
    return page(title, body, nonce=nonce, active="")


def table(headers: list, rows: list, *, empty: str = "Nothing to show.", wrap_cols: tuple = ()) -> Markup:
    """A horizontally scrollable table; ``rows`` hold escaped-on-the-fly cells (``Markup`` or plain values)."""
    if not rows:
        return h('<p class="muted">{}</p>', empty)
    head = join(h("<th scope=\"col\">{}</th>", c) for c in headers)
    body = []
    for row in rows:
        cells = []
        for index, cell in enumerate(row):
            cls = ' class="wrap"' if index in wrap_cols else ""
            cells.append(Markup(f"<td{cls}>{e(cell)}</td>"))
        body.append(Markup("<tr>" + "".join(cells) + "</tr>"))
    return Markup(f'<div class="scroll" tabindex="0" role="region" aria-label="table"><table><thead><tr>{head}</tr></thead>'
                  f'<tbody>{"".join(body)}</tbody></table></div>')


def select(name: str, options: Iterable, selected: Optional[str] = None, *, label: str, hint: str = "",
           blank: Optional[str] = None, id_: Optional[str] = None) -> Markup:
    ident = id_ or f"f-{name}"
    opts = []
    if blank is not None:
        opts.append(h('<option value="">{}</option>', blank))
    for option in options:
        value, text = option if isinstance(option, tuple) else (option, option)
        sel = " selected" if str(value) == str(selected) else ""
        opts.append(Markup(f'<option value="{e(value)}"{sel}>{e(text)}</option>'))
    return Markup(f'<label for="{e(ident)}">{e(label)}</label><select id="{e(ident)}" name="{e(name)}">{join(opts)}</select>'
                  + (str(h('<p class="hint">{}</p>', hint)) if hint else ""))


def field(name: str, label: str, value: str = "", *, hint: str = "", type_: str = "text", required: bool = False,
          maxlength: Optional[int] = None, error: Optional[str] = None, placeholder: str = "") -> Markup:
    ident = f"f-{name}"
    req = " required" if required else ""
    ml = f' maxlength="{int(maxlength)}"' if maxlength else ""
    ph = f' placeholder="{e(placeholder)}"' if placeholder else ""
    err = str(h('<p class="err" id="{}-err" role="alert">{}</p>', ident, error)) if error else ""
    desc = f' aria-describedby="{ident}-err"' if error else ""
    inv = ' aria-invalid="true"' if error else ""
    hint_html = str(h('<p class="hint">{}</p>', hint)) if hint else ""
    return Markup(f'<label for="{ident}">{e(label)}</label>'
                  f'<input id="{ident}" type="{e(type_)}" name="{e(name)}" value="{e(value)}"{req}{ml}{ph}{desc}{inv}>'
                  f"{err}{hint_html}")


def textarea(name: str, label: str, value: str = "", *, hint: str = "", rows: int = 6, required: bool = False,
             error: Optional[str] = None) -> Markup:
    ident = f"f-{name}"
    req = " required" if required else ""
    err = str(h('<p class="err" id="{}-err" role="alert">{}</p>', ident, error)) if error else ""
    desc = f' aria-describedby="{ident}-err"' if error else ""
    hint_html = str(h('<p class="hint">{}</p>', hint)) if hint else ""
    return Markup(f'<label for="{ident}">{e(label)}</label>'
                  f'<textarea id="{ident}" name="{e(name)}" rows="{int(rows)}"{req}{desc}>{e(value)}</textarea>{err}{hint_html}')


def checkbox(name: str, label: str, *, checked: bool = False, required: bool = False, value: str = "1") -> Markup:
    return Markup(f'<label class="inline"><input type="checkbox" name="{e(name)}" value="{e(value)}"'
                  f'{" checked" if checked else ""}{" required" if required else ""}> {e(label)}</label>')


def form(action: str, csrf: str, inner, *, multipart: bool = False, button: str = "Submit", danger: bool = False,
         secondary: bool = False) -> Markup:
    enc = ' enctype="multipart/form-data"' if multipart else ""
    cls = "danger" if danger else ("secondary" if secondary else "")
    cls_attr = f' class="{cls}"' if cls else ""
    return Markup(f'<form method="post" action="{e(action)}"{enc}>{csrf_field(csrf)}{e(inner)}'
                  f'<button type="submit"{cls_attr}>{e(button)}</button></form>')


def flash_html(flash: Optional[dict]) -> Optional[Markup]:
    """Render a stored flash message: ``{"kind": ok|error|warn, "title", "details": [(k, v)], "lines": [str]}``."""
    if not flash:
        return None
    kind = flash.get("kind", "ok") if flash.get("kind") in ("ok", "error", "warn") else "ok"
    parts = [h('<h2>{}</h2>', flash.get("title", ""))]
    if flash.get("details"):
        parts.append(Markup("<dl>" + "".join(str(h("<dt>{}</dt><dd>{}</dd>", k, v)) for k, v in flash["details"]) + "</dl>"))
    if flash.get("lines"):
        parts.append(Markup("<ul>" + "".join(str(h("<li>{}</li>", line)) for line in flash["lines"]) + "</ul>"))
    role = "alert" if kind == "error" else "status"
    return Markup(f'<div class="flash {kind}" role="{role}">{join(parts)}</div>')
