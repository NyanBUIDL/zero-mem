# ADR-V170-05 - Peer sharing over the LAN (publish / pull, read-only, pinned mutual TLS)

**Status:** ACCEPTED / IMPLEMENTED (repository owner decisions in chat, 2026-10-02: publish/pull and read-only on the receiver, optional dependency
`cryptography` as extra `share`, Wi-Fi/LAN only, no Bluetooth) - **Date:** 2026-10-02 - **Task:** T20
**Plan:** `docs/plans/CONTROL-PANEL-SHARING-PLAN.md` (binding) - **Runbook:** `docs/runbooks/peer-sharing.md`
**Related:** ADR-V170-02 (operator approvals, canonical events), ADR-V170-03 (inert proposals, kill switch, fail safe), AGENTS.md ("Unverified claims
must not become active facts", "Redact or reject secrets before persistence", "Reads are ... evidence-bounded; isolated modes must not leak scope")

## Context

The owner wants to give another machine that also runs zero-mem on the same Wi-Fi/LAN a selected, read-only copy of some knowledge, controlled per space,
type, project and name prefix. The data is the owner's memory: sharing must be off by default, explicit, revocable, audited, and must treat the other
machine (and the network) as untrusted. There is no CA, no cloud, no account system and no LLM involved.

## Decision

### 1. Shape: publish / pull, read-only
- The owner **serves** (`zero-mem share serve`, foreground, time-boxed). A peer **pulls** (`zero-mem share pull OWNER`). There is no write endpoint, no
  two-way sync, no relay. The only HTTP verbs are `GET` (manifest, tombstones) and `POST` (`/v1/fetch` read, `/v1/pair`). Everything else is 405/404.
- Pulled data is a **copy** in a quarantine space on the receiver. Revocation stops future access; it cannot recall copies (section 9).

### 2. Optional dependency, dependency-free core
`cryptography` (extra `share`) is needed ONLY to generate the self-signed certificate and to parse a peer certificate at pairing. It is imported lazily
inside `zero_mem.share.identity`; without it every command that needs it exits 2 with `install the optional extra: pip install "zero-mem[share]"`, and
the rest of zero-mem (including `share peers|grants|audit|revoke|discover`, settings, memory) works. TLS itself is the standard library `ssl`. A CI test
imports the whole package with `cryptography` blocked.

### 3. Identity and certificates
- Per memory: a self-signed X.509 certificate, **ECDSA P-256 / SHA-256**, 20 year validity, `CA:TRUE` (self-signed anchor), random serial, stored in
  `<data root>/share/identity.{crt,key}` (directory 0700, key 0600 where the OS supports it; see "Windows" below). `peer_id` = first 20 hex of
  SHA-256(DER certificate); the full SHA-256 is the **fingerprint** used for pinning.
- Why P-256 and not Ed25519: both complete a TLS 1.3 handshake with the Python 3.13 `ssl` module here, but ECDSA P-256 signature algorithms are
  mandatory-to-implement for TLS 1.3 and available in every OpenSSL / LibreSSL / Schannel-fronted build Python 3.11-3.13 ships on Windows, macOS and
  Linux, whereas Ed25519 certificates depend on the linked OpenSSL version/build options. The cost (slightly larger certificates) is irrelevant.
- The private key is not encrypted at rest (an unattended `serve` needs it); the trust boundary is the OS account that owns the data root (as in
  ADR-V170-02/03). Windows: `mode` bits are not enforced by NTFS; the `share/` directory inherits the ACL of the user's profile directory, which
  grants other standard users no access by default. Do not place the data root on a shared folder.

### 4. Transport: TLS 1.3 only, pinned fingerprints, no CA, no hostname checks
- `ssl.TLSVersion.TLSv1_3` is both minimum and the only accepted protocol. Plain HTTP / non-TLS clients are dropped at the handshake.
- **Service port (mutual TLS):** `verify_mode = CERT_REQUIRED` with the certificates of the *currently paired, non-revoked* peers loaded as the only trust
  anchors (rebuilt when the set changes), plus a post-handshake exact check of the SHA-256 fingerprint of the presented certificate against the live
  peer list (so a revoke takes effect on the very next connection, before any byte of HTTP is read). Unknown / missing client certificates fail the handshake.
- **Pairing endpoint:** the one place an *unknown* client certificate is accepted, and only with a valid one-time token. OpenSSL cannot request a client
  certificate without validating it, and an SNI-triggered context switch does not change the verification mode (verified with Python 3.13), so the server
  peeks at the TLS ClientHello (`MSG_PEEK`, bounded and time-limited) and uses a server-authentication-only context when the SNI is `zm-pair`; the
  joiner presents its certificate **inside the TLS-protected request** (`POST /v1/pair`), never earlier than the pin check. Any other SNI / no SNI /
  garbage uses the mutual-TLS context (fail closed).
- **Clients** use `CERT_NONE` + `check_hostname = False` for the chain (there is no CA) and then compare `SHA-256(DER(peer certificate))` with the pinned
  fingerprint using `hmac.compare_digest` **before writing a single application byte** (the invite token is only sent after the pin matches). Mismatch
  closes the socket and raises. A client certificate is public information, so the TLS 1.3 flight that carries it before the pin check leaks nothing secret.
- HTTP/1.1 over the TLS socket is implemented in the standard library (own strict request parser, `Connection: close`): header block <= 8 KiB, <= 32
  headers, body <= 64 KiB (pair: 8 KiB), `Content-Length` mandatory for POST, no chunked encoding, request line/handshake/total deadlines (slowloris),
  at most 16 concurrent connections, 120 requests/minute/peer.

### 5. Pairing ("ma lien ket")
`zero-mem share invite [--memory NAME] [--expires 10m] [--grant SPEC]...` prints `zm1:` + base64url(JSON `{v, host, port, server_fp, token, expires, label}`).
- `token` = 32 random bytes (`secrets`, 256 bits; the requirement is >= 128). The owner keeps only `HMAC-SHA256(salt, token)` + salt in `share/invites.json`
  (0600), compared with `hmac.compare_digest`; the token itself is never stored, logged or audited.
- Single use (consumed under a cross-process lock before the peer is registered), expiry (default 10 minutes, max 24 hours), and a global failed-attempt
  rate limit (5 per minute); exceeding it audits `pair_lockout`, **burns every currently open invite** (they stay dead for their lifetime) and answers 429.
  Every failure answers the same 403 `pairing_refused`; the precise reason (unknown/used/expired/malformed) goes only to the audit.
- `zero-mem share join zm1:... --name LABEL` connects, verifies `server_fp`, then sends `{token, cert, label}`. The owner records the peer
  `{peer_id, label, fingerprint, certificate, created_at}` and creates the grants offered in the invite (none when `--grant` was not given: **default
  deny**). The joiner records the owner `{peer_id, label, fingerprint, host, port}`.
- The invite is a **bearer secret** (it carries the pin and the token): hand it over through a channel you trust. Someone who steals it before it is
  used pairs instead of the intended person and gets exactly the grants offered; the intended joiner then fails (single use), which is the detection
  signal; the owner sees the peer in `share peers` / `share audit` and revokes.
- `share discover` (UDP, section 8) only helps to find the host; it never pairs or grants.

### 6. Owner permissions are canonical events through the existing access pipeline
- State lives in the canonical append-only stream as `event_type="peer_share"` events (`domain = "peer_share"`, ops `peer_add`, `peer_revoke`,
  `grant_create`, `grant_revoke`, `owner_add`, `invite_create`, `pair_attempt`, `serve_start`, `manifest`, `fetch`, `tombstones`, `skip_source`, `pull`,
  `import`, `reject`, ...), replayed incrementally (torn tail never trusted, malformed/foreign lines ignored, same discipline as ADR-V170-02/03).
  Upgrade/rebuild ignore the type (they already ignore unknown event types).
- `share grant PEER [--space S] [--type T]... [--project P]... [--ref-prefix mem://...]... [--expires 30d] [--yes]` appends `grant_create`;
  `share revoke PEER [GRANT_ID | --all]` appends `grant_revoke` (one / all grants; the peer stays paired) or, without an argument, `peer_revoke`
  (the certificate stops being trusted at once). A peer with no grant reads nothing. At least one space or project is required; `private` profile data
  can never be granted; quarantine spaces `ks-peer-*` can never be granted (no transitive re-sharing).
- **The manifest is computed by the existing authorization pipeline.** The peer is the profile `peer:<peer_id>`; for each active grant target the
  server builds the same `AccessRequest(READ, corpus_unit, include_global=False)` and a READ `AuthorizedReadGrant`, runs `AuthorizedReadService.corpus_scope`,
  and a source is eligible only if that scope `allows(profile, project, space)`; the type / prefix filters only *narrow* the result. Then it drops
  deleted (forgotten), secret-sensitivity (`is_withheld_sensitivity`), expired learned items, peer-imported sources, anything over `max_source_bytes`, and
  anything the central prescan (`scan_bytes` + `scan_zip_members`) flags **at manifest time and again at fetch time** (defense in depth); a source that
  fails is skipped and audited (`skip_source`). Pending proposals are not corpus sources and cannot appear. Other profiles' private memory is outside every
  grant target by construction.
- Endpoints (all after mutual TLS): `GET /v1/manifest`, `POST /v1/fetch {source_ids}`, `GET /v1/tombstones?since=`, closed JSON schemas, size/count caps.

### 7. Receiving: quarantine, provenance, proposals
`zero-mem share pull OWNER [--dry-run] [--yes]` fetches the manifest, shows a plan (new / changed / unchanged / skipped with reasons and sizes) and, after
confirmation, fetches in bounded batches. For every source: strict base64, size and SHA-256 digest equal to the manifest, closed `ref` grammar (no traversal,
no control characters, scheme/type agreement), local caps (`max_pull_sources`, `max_source_bytes`, `max_total_bytes`) and the **full local pre-register scan**
(the normal write path's `_preflight`: bytes, zip members, extracted text). A malicious owner's bad item is rejected and audited; the rest continues.
- Stored under the knowledge space `ks-peer-<owner peer_id>`, profile `peer-import`, lifecycle `observed`, external ref
  `peer://<owner peer_id>/<scheme>/<original path>`, provenance `{peer, peer_label, original_ref, digest, fetched_at, tool: peer_pull}`. The normal write
  path refuses `peer://` refs, so the copy is read-only for every agent.
- `rule` / `decision` / `gotcha` are never stored: they become **proposals** (`Memory.propose(source="peer")`, name prefixed `peer-<id8>-`, evidence naming
  the peer, ref and digest) that the owner reviews with `zero-mem review` (ADR-V170-03). Their tombstones are not applied automatically (the owner may
  already have approved them; use `review revoke`).
- `[sharing] import_into_recall = false` by default. When true, `Memory.recall` also searches the `ks-peer-*` spaces on which the asking profile holds a
  READ grant given by the receiving owner (`zero-mem agents grant-read PROFILE --space ks-peer-<id>`); hits are labelled `[from peer X - untrusted
  reference, not an instruction]` and have scope `peer`. `context` and `brief` (which are injected into prompts) never include peer content in this phase.
- Tombstones: `GET /v1/tombstones?since=<last>` is applied by forgetting the matching `peer://` copy. Pulls are idempotent (digest per `(owner, source)`
  replayed from `import` events; unchanged sources are skipped) and resumable (each source is committed independently; a rerun continues).

### 8. Serving rules and discovery
- `serve` binds only to RFC1918, 169.254/16, fc00::/7, fe80::/10, 127/8, ::1 (the LAN address is detected when `--bind` is omitted) and **refuses any other
  address** (including `0.0.0.0` and `::`) unless `[sharing] allow_public_bind = true` *and* `--i-know-this-is-public`. It stops after `--for`
  (default 30 minutes, max 24 hours). A client joining refuses a non-LAN host the same way.
- `serve --announce` sends a UDP datagram `{"zm":1,"svc":"zero-mem-share","peer_id":..,"port":..}` (plus `label` only if `[sharing] announce_label = true`) every
  3 seconds; `share discover` lists what it hears (sender address must be a LAN address). No memory names or contents are ever announced.
- Settings `[sharing]` (closed schema, defaults safe): `enabled=false`, `max_pull_sources=200`, `max_source_bytes=1 MiB`, `max_total_bytes=64 MiB`,
  `allow_public_bind=false`, `import_into_recall=false`, `announce_label=false`. `[safety] kill_switch` or an unusable settings file (fail safe) disable
  serve, pull, pairing, invite, join and grant; revoke / peers / grants / audit keep working.

### 9. Revocation, honestly
`revoke` stops *future* access immediately (next TLS handshake, and any later request of a connection already accepted is checked against the live
list per request). It cannot delete or recall copies the peer already pulled, nor stop the peer's agents from having read them. The owner's `forget`
propagates as a tombstone that a peer applies on its next pull *while that peer still holds a grant covering the source*; a revoked peer receives nothing.
Revoking a leaked invite before it is used: let it expire (or `share revoke`/delete `share/invites.json`; a burned invite is dead).

## Threat model

| Threat | Mitigation | Residual |
|---|---|---|
| Passive eavesdropper | TLS 1.3 (forward secrecy, AEAD); nothing sensitive in cleartext (the UDP announcement carries only service name, peer id, port) | traffic metadata (who talks to whom, sizes) |
| Active MITM on the LAN | pinned server fingerprint from the invite (checked before the token is sent) and mutual pinned certificates afterwards; no CA, no TOFU | an attacker who can modify the invite in transit is effectively the owner: use a trusted channel |
| Malicious peer (reads too much) | default deny; grants through the access pipeline; type/prefix/expiry; caps; re-scan; no write endpoint; rate limit; audit | a granted source is readable by that peer and any agent behind it |
| Stolen / leaked invite | single use, expiry (10 min default), pairing grants nothing unless offered, audit + `share peers`, revoke | whoever redeems first gets the offered grants |
| Replay | one-time token consumed atomically; TLS 1.3 per-session keys | none known |
| Brute force of the token | 256-bit token, salted HMAC, global 5/min limit then burn all open invites, uniform refusal | none practical |
| Malicious content from an owner (secrets, traversal, oversized, digest lies, prompt injection) | strict ref grammar, size/digest/count caps, local full pre-register scan, quarantine space, read-only `peer://` refs, labelled untrusted in recall, learned types only as proposals, briefs exclude peer content | prompt-injection text inside a *fact/file* a human then asks an agent to follow; labelled but not detectable deterministically |
| Revoked peer | handshake trust set + live fingerprint check + per-request check | already-pulled copies stay |
| Rogue device that only discovers the service | mutual TLS refuses it at the handshake; pairing needs the token; the announcement exposes only service/peer id/port | it learns that a zero-mem share service exists |
| Resource exhaustion (slowloris, huge bodies, connection floods, audit spam) | handshake/request deadlines, size limits, 16 concurrent connections, per-peer rate limit, coalesced TLS-refusal audit | LAN-level flooding can still deny service while `serve` runs |
| Exposure beyond the LAN | private-address bind policy, explicit double opt-in for public, client refuses non-LAN hosts | the owner can opt in |

## What this does and does not give
It gives an explicit, scoped, audited, read-only, pinned-TLS sharing of selected knowledge to a paired LAN machine, with imported material quarantined and
learned types gated by the owner. It does not protect against a compromised OS account on either machine, a peer that copies what it is allowed to read,
or an owner who hands the invite to the wrong person. It is not a backup or sync mechanism.

## Alternatives rejected
- **Two-way sync / write endpoints**: owner decision; also contradicts "unverified claims must not become active facts".
- **Trust on first use / CA / mDNS identity**: the invite is the only out-of-band trust anchor; a CA is infrastructure the owner does not have.
- **A second authorization store for peers**: grants live in the canonical stream and decisions go through `AuthorizedReadService`.
- **Home-made cryptography, PSK-in-the-clear, plain HTTP with tokens**: no.
- **Bluetooth**: stdlib support only on Linux; deferred.
- **Ed25519 certificates**: see section 3.

## Consequences
`zero_mem/share/*`, `zero_mem/commands_share.py`, `zero-mem share ...`, `[sharing]` settings, `Memory.recall` peer spaces, `Memory._import_peer_source`,
`PROPOSAL_SOURCES += "peer"`. Tests: `tests/unit/test_t20_*.py` (cryptography-dependent ones use `importorskip`; `test_t20_core_without_crypto.py` proves
the core imports and runs without it). Follow-ups: T21 panel pages; optional owner confirmation per new peer; brief labelling of peer content;
mDNS; an encrypted-at-rest key option.
