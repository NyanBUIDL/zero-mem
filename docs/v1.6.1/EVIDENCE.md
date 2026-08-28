# v1.6.1 — Additive Patch Evidence

## Scope

Licensing, research provenance, packaging metadata, PKG-1 version portability,
PKG-2 Windows test-environment portability, and minimal security/contribution
documentation. Product behavior, canonical schema and authorization boundaries
are unchanged.

## Local qualification

- Platform: Windows; CPython 3.12.13.
- Version RED-first: `2 failed` at `1.6.0`, then `2 passed` after the two
  authoritative runtime/release-layer version sources changed to `1.6.1`.
- DEF-047 machine-state reconciliation RED-first: `1 failed`, then `1 passed`.
- v1.6.1 workflow regression RED-first: `1 failed`, then `1 passed`.
- Compile gate: PASS.
- Machine-state validator: PASS.
- Packaging-focused: **36 passed, 0 failed**.
- Artifact-contract checker: `2 passed` (matching artifacts accepted; missing
  sdist `NOTICE` rejected).
- Full suite after the remote-harness regressions: **3651 passed, 38 skipped,
  0 failed**.
- Junction benchmark retained the covering primary-key query plan; median
  point lookup was 10.5 / 10.8 / 14.3 µs at 1k / 10k / 100k events.

One later exact-tree full-suite attempt recorded an environment-sensitive
Windows Application Control denial (`WinError 4551`) while verifying the
installed console executable. The exact failed PKG-2 test passed immediately on
retry with the same source and artifact-building path. This is retained as an
environment-policy observation, not converted into a product PASS or code fix;
publication still requires a fresh zero-failure full-suite run and remote
Windows qualification.

These results qualify the release candidate working tree. After the release
commit is created, artifact build/acceptance is repeated from that clean exact
commit before any tag or GitHub Release is created.

## Artifact contract

- Distribution version: `1.6.1` from `zero_mem.version.__version__`.
- Wheel and sdist must both contain `LICENSE` and `NOTICE`.
- Wheel metadata author must be `NyanBUIDL`.
- Fresh-wheel acceptance must prove path-with-spaces, optional `pypdf`, and
  repository-independent imports.
- Artifact hashes and exact source SHA are recorded in the GitHub Release.

## Remote qualification

The exact release commit must pass Ubuntu, Windows and macOS on CPython
3.11/3.12/3.13 before tag or publication. The GitHub Actions run URL and verdict
are recorded in the GitHub Release; no remote PASS is claimed in this source
file before that run completes.

The first release-branch run, `33143783958`, correctly blocked publication at
source SHA `23515e4652e88759dbac3b0db2b6fcbdde572e21`. All nine cells built the
artifacts and passed the LICENSE/NOTICE/metadata contract. It exposed two test
harness defects: a shared-prefix false positive in PKG-1 on Linux/Windows and an
unresolved `/tmp` alias in the macOS PKG-2 fixture. Both received RED-first
regressions and minimal fixes; the active workflow also moved the official
checkout, setup-python and upload-artifact pins to v7 after GitHub runners
warned that the prior pins targeted deprecated Node 20. A successor exact-commit
9/9 run remains mandatory.

## Release invariant

Publication requires:

```text
MASTER_SHA = RELEASE_BRANCH_SHA = TAG_TARGET = ARTIFACT_SOURCE_SHA
```

The published v1.6.0 tag and assets remain immutable.
