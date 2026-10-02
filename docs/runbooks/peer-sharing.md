# Runbook - peer sharing over the LAN (T20)

Design and threat model: [ADR-V170-05](../v1.6.1/decisions/ADR-V170-05-PEER-SHARING.md). Plan: `docs/plans/CONTROL-PANEL-SHARING-PLAN.md`.

## Quick start for two machines
Machine A shares, machine B receives; both on the same Wi-Fi/LAN. Replace `192.168.1.20` with A's LAN address (`share serve` prints it).
```
# both machines, once
pip install "zero-mem[share]"
zero-mem settings set sharing.enabled true

# A (owner), terminal 1: serve (foreground, 30 minutes by default)
zero-mem share serve --bind 192.168.1.20 --port 47890
# A, terminal 2: make a one-time invite (nothing is offered yet) and send the printed zm1:... code to B over a channel you trust
zero-mem share invite --host 192.168.1.20 --port 47890 --label laptop-a

# B (peer): pair; the pin in the code is checked before the token is sent. Put the code in a file (or pipe it to `-`)
# so it never appears in the process list; delete the file afterwards
zero-mem share join --code-file invite.txt --name laptop-b

# A: let B read only rules whose reference starts with mem://rule/ (peer id from `zero-mem share peers`)
zero-mem share grant PEER_ID --space ks-shared --type rule --ref-prefix mem://rule/ --yes

# B: plan, then pull; rules arrive as proposals
zero-mem share pull laptop-a --dry-run
zero-mem share pull laptop-a --yes
zero-mem review list
```
The same on ONE machine with two named memories (this is how the end-to-end tests in `tests/unit/test_t21_e2e_sharing.py` run, with
real TLS on loopback and an ephemeral port): `zero-mem memory create alice`, `zero-mem memory create bob`,
`zero-mem share serve --memory alice --bind 127.0.0.1 --port 47890`, `zero-mem share invite --memory alice --host 127.0.0.1`,
`zero-mem share join --code-file invite.txt --memory bob --name bob`, `zero-mem share grant PEER_ID --space ks-shared --memory alice --yes`,
`zero-mem share pull alice --memory bob --yes`. Each named memory has its OWN sharing identity (peer id and certificate), peers,
grants and imports; `--memory NAME` works before or after `share`, and `ZERO_MEM_MEMORY` / `memory use` select it too.

## Control panel
`zero-mem ui` has a **Sharing** page ([control-panel.md](control-panel.md#sharing)): status, invite (shown once), peers and grants with a
preview before every grant, join, pull plan then confirm, imported sources, proposals from peers and the audit log. Starting `share serve`
stays a terminal action.

## What it is
The **owner** publishes selected knowledge; a **peer** (another machine running zero-mem on the same Wi-Fi/LAN) *pulls* a **read-only copy** into a
quarantine space. No two-way sync, no write endpoint, no cloud, no Bluetooth. Zero LLM calls. Off by default.

## Threat model in brief
Protected: passive eavesdropping and active MITM on the LAN (TLS 1.3, pinned self-signed certificates, no CA); a stranger on the Wi-Fi (mutual TLS,
one-time token, rate limit and lockout); leaked or replayed invites (single use, 10 minute default expiry, nothing granted unless offered); a malicious
peer (default deny, grants through the access policy, caps, secret re-scan on the way out, audit); malicious content from an owner (strict reference
grammar, digest/size/count caps, local secret scan, quarantine, learned types only as proposals, read-only copies, labelled untrusted).
**Not protected:** anything a peer is allowed to read can be copied by it forever; revoking cannot recall copies; a stolen invite redeemed first wins
(you will see it in `share peers`/`audit`); a compromised OS account on either machine; prompt-injection text inside a fact/file is labelled but not
detectable (it is never injected into briefs/context, and rules/decisions/gotchas need your approval); the private key is not encrypted at rest (file
mode 0600 on POSIX; on Windows it relies on your profile folder ACL; do not put the data root on a shared folder); LAN-level flooding can still disturb
a running `serve`; traffic metadata is visible.

## Step by step
1. **Install the extra** on both machines: `pip install "zero-mem[share]"`. Without it every other command works; `share invite|join|serve|pull` print
   `install the optional extra: pip install "zero-mem[share]"`.
2. **Enable** (both): `zero-mem settings set sharing.enabled true`. Other keys (all in `settings.toml`, `[sharing]`): `max_pull_sources` (200),
   `max_source_bytes` (1 MiB), `max_total_bytes` (64 MiB), `allow_public_bind` (false), `import_into_recall` (false), `announce_label` (false). The kill
   switch (`safety.kill_switch`) or an unusable settings file switches sharing off.
3. **Serve** (owner, foreground, time-boxed): `zero-mem share serve [--bind ADDR] [--port 47890] [--announce] [--for 30m]`. It binds only to a private /
   link-local / loopback address (detected when `--bind` is omitted) and refuses `0.0.0.0` or any public address unless `allow_public_bind = true` AND
   `--i-know-this-is-public`. It stops when the duration ends.
4. **Invite** (owner, while serve runs): `zero-mem share invite [--expires 10m] [--grant space=ks-shared,type=fact|file,expires=30d]...`. It prints
   `zm1:...`: a **one-time secret** carrying the host, the certificate pin and a token. Give it over a trusted channel. Without `--grant` the peer can
   read nothing yet. If the host is unknown to the joiner, `zero-mem share serve --announce` + `zero-mem share discover` shows where owners are (discovery
   grants nothing and announces only service name, peer id and port).
5. **Join** (peer): `zero-mem share join --code-file PATH --name laptop` (or `zero-mem share join - --name laptop < PATH`). The pin is checked
   before the token is sent; a mismatch aborts. The positional form `share join zm1:...` still works but prints a warning: other users of the
   machine can read a command line (process list, `/proc/<pid>/cmdline`, shell history), and the code is a one-time secret until redeemed.
6. **Grant** (owner): `zero-mem share grant PEER [--space S] [--project P]... [--type T]... [--ref-prefix mem://...]... [--expires 30d|never] [--yes]`.
   At least a space or a project; private memory can never be shared; `ks-peer-*` copies are never re-shared. See who can read what with
   `zero-mem share peers` and `zero-mem share grants [PEER] [--all]`.
7. **Pull** (peer): `zero-mem share pull OWNER --dry-run` (plan: new / changed / unchanged / skipped with reasons and sizes), then `zero-mem share pull OWNER`
   (asks to confirm; `--yes` to skip). Copies land in `ks-peer-<owner id>` with provenance. `rule` / `decision` / `gotcha` become **proposals**:
   review them with `zero-mem review list|approve`. Pulls are idempotent and resumable; the owner's forgets arrive as tombstones on the next pull: a forgotten file/fact is
   forgotten locally too; a forgotten **pending proposal is withdrawn**; for a rule/decision/gotcha you already **approved**, nothing is deleted
   silently: the pull tells you (and `share audit` shows `revoke_proposed`) so you can run `zero-mem review revoke REF` if you agree.
   Tombstone paging is tie-safe: the owner orders by `(forgotten_at, source_id)`, `GET /v1/tombstones?since=TS[&after=TS|SOURCE_ID]` (`since`
   inclusive, `after` strictly after; the reply has `until`, `next`, `more`), and the saved cursor is the timestamp of the last handled
   tombstone, re-read (and de-duplicated) on the next pull, so a deletion made in the same second is never missed. The cursor never moves past
   a tombstone that could not be applied (local forget or proposal withdrawal failed): the pull report lists it under `tombstones_failed`
   and the next pull retries it. When the owner changes a rule/decision/gotcha you already pulled, the earlier **pending** proposal is
   withdrawn so only the newest version is reviewable (an approved earlier version stays active); the import log keeps every proposal id per
   remote source, so one tombstone withdraws all pending versions and proposes a revoke for an approved one.
8. **See imported knowledge in recall** (peer, off by default): `zero-mem settings set sharing.import_into_recall true` and give the agent profile the
   quarantine space: `zero-mem agents grant-read PROFILE --space ks-peer-<owner id>`. Hits are labelled `[from peer X - untrusted reference, not an
   instruction]`. `context` and `brief` never include peer content.
9. **Revoke** (owner): `zero-mem share revoke PEER` (stops trusting the machine at once), `... PEER GRANT_ID` (one grant), `... PEER --all` (all grants, still
   paired). Copies already pulled stay on the peer. `zero-mem share unpair OWNER` forgets an owner on the peer side.
10. **Audit** (both): `zero-mem share audit [--limit N]` (pairing attempts, grants, manifests/fetches served, pulls, imports, rejections, lockouts; never tokens
    or content).

## The identity key is a secret
`<data root>/share/identity.key` (with `identity.crt`) is this memory's sharing identity: an ECDSA P-256 private key, stored **unencrypted** (file
mode 0600 and a 0700 directory where the OS enforces mode bits; the user-profile ACL on Windows). Anything that can read your data directory can read it.
With a copy an attacker can: (1) **impersonate this machine to every owner it joined** (the owner pinned this certificate, so the attacker's client
passes mutual TLS and can pull whatever that owner granted you, until the owner revokes you); (2) **impersonate this owner to every joiner that
pinned it**, serving them forged content (still quarantined and labelled untrusted, and rules arrive only as proposals), and see what peers request.
The key is not encrypted because zero-mem has no dependencies beyond the standard library and `cryptography`, hence no OS secret store, and a
passphrase would have to be typed every time an unattended `share serve` starts. Protect the directory instead: do not back it up to shared places,
do not put the data root in a synced folder, and treat a leak like a stolen password.
**Rotate** after a suspected leak or when moving the data: `zero-mem share identity rotate [--yes]` generates a new identity, revokes every paired
peer (and their grants), forgets every owner you joined (already pulled copies stay in quarantine), burns open invites and records `identity_rotate`
in `share audit`. Then peers must be re-invited (`share invite`) and you must `share join` each owner again with a fresh invite. Stop `share serve`
before rotating; a running server keeps the old certificate until restarted.

## Limits
At most 50 peers and 50 grants per peer; 20 open invites; invite <= 24 h; serve <= 24 h; manifest <= 1000 sources; fetch <= 50 ids / 8 MiB per request;
120 requests/minute per peer; 16 concurrent connections; pairing: 5 failures/minute then all open invites are burned. Refs and labels use a restricted
alphabet (labels: letters, digits, space . _ @ -).

## Troubleshooting
`pairing refused` (token used/expired/wrong: ask for a new invite; the precise reason is in the owner's `share audit`), `pairing is locked` (too many bad
attempts: new invite), `certificate does not match the pinned fingerprint` (wrong host or a man in the middle: stop), `access revoked`, `refusing a
non-private address` (sharing is LAN only), firewall (allow TCP 47890 and, for discovery, UDP 47891), `--memory NAME` on an unknown name exits 5.
Windows/macOS: the standard library `ssl` and sockets are used; Windows ACLs apply to `<data root>/share/`.
