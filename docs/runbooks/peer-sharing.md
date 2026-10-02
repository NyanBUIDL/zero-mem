# Runbook - peer sharing over the LAN (T20)

Design and threat model: [ADR-V170-05](../v1.6.1/decisions/ADR-V170-05-PEER-SHARING.md). Plan: `docs/plans/CONTROL-PANEL-SHARING-PLAN.md`.

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
5. **Join** (peer): `zero-mem share join zm1:... --name laptop`. The pin is checked before the token is sent; a mismatch aborts.
6. **Grant** (owner): `zero-mem share grant PEER [--space S] [--project P]... [--type T]... [--ref-prefix mem://...]... [--expires 30d|never] [--yes]`.
   At least a space or a project; private memory can never be shared; `ks-peer-*` copies are never re-shared. See who can read what with
   `zero-mem share peers` and `zero-mem share grants [PEER] [--all]`.
7. **Pull** (peer): `zero-mem share pull OWNER --dry-run` (plan: new / changed / unchanged / skipped with reasons and sizes), then `zero-mem share pull OWNER`
   (asks to confirm; `--yes` to skip). Copies land in `ks-peer-<owner id>` with provenance. `rule` / `decision` / `gotcha` become **proposals**:
   review them with `zero-mem review list|approve`. Pulls are idempotent and resumable; the owner's forgets arrive as tombstones on the next pull.
8. **See imported knowledge in recall** (peer, off by default): `zero-mem settings set sharing.import_into_recall true` and give the agent profile the
   quarantine space: `zero-mem agents grant-read PROFILE --space ks-peer-<owner id>`. Hits are labelled `[from peer X - untrusted reference, not an
   instruction]`. `context` and `brief` never include peer content.
9. **Revoke** (owner): `zero-mem share revoke PEER` (stops trusting the machine at once), `... PEER GRANT_ID` (one grant), `... PEER --all` (all grants, still
   paired). Copies already pulled stay on the peer. `zero-mem share unpair OWNER` forgets an owner on the peer side.
10. **Audit** (both): `zero-mem share audit [--limit N]` (pairing attempts, grants, manifests/fetches served, pulls, imports, rejections, lockouts; never tokens
    or content).

## Limits
At most 50 peers and 50 grants per peer; 20 open invites; invite <= 24 h; serve <= 24 h; manifest <= 1000 sources; fetch <= 50 ids / 8 MiB per request;
120 requests/minute per peer; 16 concurrent connections; pairing: 5 failures/minute then all open invites are burned. Refs and labels use a restricted
alphabet (labels: letters, digits, space . _ @ -).

## Troubleshooting
`pairing refused` (token used/expired/wrong: ask for a new invite; the precise reason is in the owner's `share audit`), `pairing is locked` (too many bad
attempts: new invite), `certificate does not match the pinned fingerprint` (wrong host or a man in the middle: stop), `access revoked`, `refusing a
non-private address` (sharing is LAN only), firewall (allow TCP 47890 and, for discovery, UDP 47891), `--memory NAME` needs named-memory support (T18).
Windows/macOS: the standard library `ssl` and sockets are used; Windows ACLs apply to `<data root>/share/`.
