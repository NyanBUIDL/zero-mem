# Control panel (`zero-mem ui`)

The owner's local web console for managing what goes INTO memory (add, ingest, proposal inbox) and what comes OUT (browse, brief
preview, eval, audit), plus agents and settings. Standard library only, no JavaScript, no external requests, Windows/macOS/Linux,
Python 3.11-3.13. Plan: [CONTROL-PANEL-SHARING-PLAN.md](../plans/CONTROL-PANEL-SHARING-PLAN.md).

## Start

```bash
zero-mem ui                                   # random port on 127.0.0.1; prints a one-time URL
zero-mem --profile claude-code ui --port 8765 --allow-root ~/notes --allow-root ~/work/docs
zero-mem ui --open --idle-timeout 30          # open the browser yourself-for-you; stop after 30 idle minutes (default 60)
```

Open the printed `http://127.0.0.1:PORT/?t=TOKEN`. The token is exchanged once for an `HttpOnly; SameSite=Strict` cookie and you are
redirected to a token-free URL. The link works once; restart the command for a new one. Nothing is written to disk. Stop with Ctrl+C.
The data root comes from the normal resolution (`ZERO_MEM_DATA_ROOT` / `--memory`); the acting profile from `--profile`.
`--no-open` is the default. `--host` accepts only `127.0.0.1` or `::1`.

## Security model

This is a privileged owner console: it can approve rules, grant write access and ingest files.

- Loopback bind only; non-loopback hosts are refused before a socket exists; non-loopback peers are dropped.
- 256-bit one-time URL token, separate 256-bit session cookie (named per port) and per-session CSRF token; constant-time comparisons.
- Strict `Host` allow-list (DNS rebinding), `Origin`/`Referer` check and CSRF token on every POST; all mutations are POST, GET never changes state.
- No CORS headers. CSP `default-src 'none'` (no scripts; one inline stylesheet by per-response nonce), `nosniff`, `no-store`,
  `X-Frame-Options: DENY`. `Referrer-Policy: same-origin` (not `no-referrer`: Chromium then sends `Origin: null` on form posts and the Origin
  check would reject the owner's own forms; nothing is sent cross-origin either way).
- Caps: 1 MiB forms, 25 MiB uploads, per-socket timeout, total read deadline, 32 concurrent connections (else 503), idle shutdown.
- Every user-controlled string is HTML-escaped. Errors show a generic page; the terminal log carries only the exception class and location.
- Ingestion by path only under `--allow-root` folders (same `PathGuard` as the MCP `memory_ingest`: absolute, no symlinks, never the store
  itself); the panel never lists the file system. Uploads reject names with path components and go through the Memory bytes API.
- Preview is a dry run (the pre-write secret scan); the write happens only on a confirm POST, which re-checks the path.

**Agents must never have access to this panel.** Do not give an agent a shell on the machine, the URL, the cookie or the token: whoever
reaches it acts as you (approve rules, grant write access, forget memory, change the kill switch). Confirmation checkboxes are friction,
not authentication.

## Pages

| Page | What it does |
|---|---|
| Overview | memory path, counts by type/scope, agents, learning mode, injection, kill switch, pending count, last writes, doctor warnings |
| Inbox | pending proposals (proposer, type, scope, text, evidence, seen); approve (edit/name), reject (reason), revoke, expire; shows the resulting source id |
| Add | text form through `Memory._owner_add` (same as `zero-mem add`) |
| Ingest | upload or allow-root path, preview (would ingest / skipped / rejected), confirm, then the IngestReport |
| Browse | search or list with type/scope/project filters, provenance (ref, type, source id, score, version), detail view, forget with confirm |
| Brief | `Memory.brief(preview=True)` for a profile/project/task: text, why injection is on/off, budget used |
| Agents | agents and grants; register, grant read, grant write (checkbox "I approve" = `--yes`, operator recorded as `user@ui`), revoke |
| Settings | validated edit of `settings.toml` (inline errors, nothing written on error), overrides, deny patterns, kill switch |
| Eval and health | safety suite, pasted cases, history, doctor |
| Audit | recent canonical events and writes/forgets, newest first, paged |

Every mutation reuses the CLI's code (Reviewer, Provisioner, Memory owner entry points, settings API): no new write path.

## Limits

One browser session per start (single-use link); previews live in memory for 15 minutes (max 6); path preview walks at most 200 files / 64 MiB;
audit tail reads the last 6 MiB of each log; browse/search show 50 rows per page. Screenshots: [ui-screenshots/](ui-screenshots/).
