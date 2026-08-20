# 06 — Test, evidence, and release gates

## Required test layers

| Layer | Required proof |
|---|---|
| Unit | Contract validation, deterministic ordering, typed failures, no raw secret/path errors. |
| Integration | Canonical writer → projection → authorized read, sidecar, Hermes lifecycle. |
| Security | Redaction, deny-before-discovery, scope leakage, symlink/reparse and artifact-secret scans. |
| Concurrency | Multi-process append/project/recover, bounded lock/queue/deadline, crash/restart. |
| Benchmark | WP-33 deterministic lexical benchmark through real authorized-read/FTS path. |
| Packaging | Wheel/sdist build, checksum, clean install and public smoke test. |

## Mandatory platform matrix

| OS | Python | Required jobs | v1.2.2 status |
|---|---|---|---|
| Linux | 3.11 execution environment | full suite, process lock, recovery, clean install | QUALIFIED |
| macOS | future supported versions | POSIX path/lock, clean install | DEFERRED_TO_v1.2.3 |
| Windows | future supported versions | reparse/lock, clean install | DEFERRED_TO_v1.2.3 |

The maintainer decision `MAINTAINER-DECISION-PLATFORM-SCOPE-v1.2.2` authorizes Linux-only v1.2.2 qualification. Windows/macOS remain pending real-platform qualification; no skipped or unavailable platform row is a green result.

## Minimum end-to-end scenarios

1. Capture a redacted event, restart runtime, search it through direct API, then sidecar and Hermes.
2. Force projection lag and assert `STALE` vs `READY` semantics for every transport.
3. Deny profile/project access and assert zero candidate IDs, counts, snippets and source metadata leak.
4. Corrupt/delete derived SQLite, prove canonical JSONL remains unchanged, rebuild, then query again.
5. Exhaust queue/deadline/lock contention and assert bounded typed failures without hanging workers.
6. Enable/disable/restart Hermes and assert registrations are idempotent and disabled state does not create a DB/writer/query.
7. Repeat capture/recovery/benchmark path on Windows, Linux and macOS.

## Evidence layout

Create immutable records under:

```text
artifacts/evidence/v1.2.2/<candidate-sha>/
  manifest.md
  commands.txt
  environment.txt
  logs/<os>-py<version>-<suite>.log
  hashes/SHA256SUMS.txt
  sbom.<format>
  independent-audit.md
```

`manifest.md` must list tag, source SHA, parent SHA, clean-tree state, build command, wheel/sdist checksum, exact tests, pass/fail/skip counts and every exception. A release is `NO-GO` if an exception cannot be reproduced from that record.

## Final release decision

The following are all required:

- [ ] V122-00 through V122-05 are `VERIFIED` with current-SHA evidence.
- [ ] Windows, Linux and macOS matrix is green for the declared support set.
- [ ] Full suite has no collection error, unexplained failure or hidden skip.
- [ ] Direct API/sidecar/Hermes E2E and security scenarios pass.
- [ ] Wheel/sdist hashes match the source manifest and clean-install smoke tests pass.
- [ ] Independent audit finds no open blocker.
- [ ] Maintainer explicitly authorizes tag and private GitHub Release.

Only then may the status change to `RELEASE_QUALIFIED` and the tag `v1.2.2` be proposed.
