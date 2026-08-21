# 01 — Ordered remediation ledger

Work on one row at a time, in order. A later row cannot claim completion when an earlier dependency remains `OPEN`.

| Order | ID | Required change | Code owner(s) | Black-box acceptance | Status rule |
|---:|---|---|---|---|---|
| 0 | R-00 | Repair release evidence model before product claims. | `scripts/verify_v122_evidence.py`, `docs/v1.2.3/evidence/` | A clean clone of the candidate tag verifies manifest, logs, source SHA and asset hashes without external developer paths. | Blocks tag/release. |
| 1 | R-01 | Make four public reads usable from a documented public composition path. | [`zero_mem/api.py`](../../../zero_mem/api.py), public runtime/factory module, [`src/integration/public_read_adapter.py`](../../../src/integration/public_read_adapter.py) | A consumer importing only `zero_mem` opens a local client, captures/ingests fixture data, then gets authorized `READY` responses from all four methods. | `PublicClient.open()` returning unavailable without configured runtime may remain valid, but the documented public factory must work. |
| 2 | R-02 | Make sidecar discovery and dispatch canonical. | [`zero_mem/sidecar.py`](../../../zero_mem/sidecar.py), [`src/integration/sidecar.py`](../../../src/integration/sidecar.py) | `capabilities` advertises exactly the callable read names; direct and sidecar outputs match for READY, EMPTY, DENIED, STALE, TIMEOUT and UNAVAILABLE. | No legacy name may be advertised as the canonical replacement. |
| 3 | R-03 | Build one real Hermes host composition. | [`src/integration/hermes_plugin.py`](../../../src/integration/hermes_plugin.py), [`zero_mem/hermes_integration.py`](../../../zero_mem/hermes_integration.py), read/capture adapters | Supported host factory registers capture and reads, then proves capture → projection → read → restart → shutdown. | A factory returning capture-only `RegistrationAdapter` is `PARTIAL`. |
| 4 | R-04 | Qualify the platform contract on Windows and macOS. | [`src/storage/platform.py`](../../../src/storage/platform.py), storage callers/tests | Real Windows and macOS CI runs exercise capture, lock timeout, short write, promotion, recovery and link/reparse safety. | No support claim before green rows. |
| 5 | R-05 | Release qualification and reconciliation. | package/release scripts, evidence, release notes | Exact release tag agrees with branch, source SHA, asset SHA, docs and published release state. | Blocks publication. |

## R-00 — Evidence must be part of the release truth

The tag must contain a small, immutable evidence bundle under:

```text
docs/v1.2.3/evidence/<full-source-sha>/
  manifest.json
  manifest.md
  commands.txt
  environment.txt
  logs/<platform>-<python>-<suite>.log
  hashes/SHA256SUMS.txt
  independent-audit.md
```

The manifest must name the same full SHA as the tag target. Release assets may mirror this bundle, but the source tag cannot refer to an absent local path. Post-release reconciliation is an additive commit for the next release; it must never rewrite an existing tag.

## R-01 — Public composition rule

The public API may stay storage-neutral internally, but an external user needs one supported public construction path. Before implementing, choose and approve one stable form, for example a `zero_mem` factory that owns runtime construction and returns a `PublicClient` configured with an authorized read service.

Required tests use no `src.*` import in the caller. They must use real canonical JSONL + derived SQLite fixtures, not an injected mock `ReadService` only.

## R-02/R-03 — One semantic path

Direct API, sidecar and Hermes must call the same public-read/authorization contract. Tests compare normalized results and prohibited leakage. Hermes host tests must use the full supported plugin context contract, not a capture-only fake context.

## R-04 — Platform rule

Windows tests requiring symbolic-link privilege must run in a configured CI runner (Developer Mode or equivalent documented privilege). If privilege is unavailable, report `SYMLINK_PRIVILEGE_UNAVAILABLE` as a failed qualification prerequisite, not as a passing test. macOS must run on an actual runner, not inferred from Linux/POSIX behavior.
