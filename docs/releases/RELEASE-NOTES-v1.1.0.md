# Zero-Mem v1.1.0 Release Notes

## Scope

Zero-Mem v1.1.0 is the verified local-first evidence and memory sidecar
baseline. These notes describe the implementation present in the release
candidate; they do not claim remote publication.

## Included

- **Core/API:** a transport-neutral public client and typed lifecycle/capability
  results, with Hermes behavior isolated behind explicit adapters.
- **Configuration and storage:** validated XDG-based configuration, append-first
  canonical JSONL traces, derived SQLite/FTS state, replay/rebuild behavior, and
  backup/restore safeguards.
- **Retrieval and context:** read-only structured, FTS, relation, verification,
  lifecycle, corpus, profile, and knowledge-space retrieval with authorization
  before ranking/influence and bounded context evidence.
- **Concurrency and recovery:** local process coordination, bounded async
  behavior, failure diagnosis, staged derived rebuild, atomic activation, and
  failure-preserving upgrade behavior.
- **Sidecar/Hermes:** explicit optional Hermes integration and local sidecar
  capability boundaries; setup and doctor do not enable integration implicitly.
- **Obsidian/workspace:** curated, rebuildable projection and controlled
  write-back boundaries with provenance and path-safety checks.
- **Migration and packaging:** v1.0-to-v1.1 synthetic upgrade/backup/rollback
  coverage, installable wheel and sdist, offline bundle/install support, and
  non-destructive uninstall semantics.
- **Compatibility:** Python policy is CPython `>=3.11,<3.14`. Linux x86_64 with
  CPython 3.11.16 and SQLite FTS5 is locally verified. macOS arm64, Linux arm64,
  WSL2, and Docker remain `SUPPORTED_IF_QUALIFIED`; macOS x86_64 is
  `BEST_EFFORT_UNVERIFIED`; native Windows is `NOT_SUPPORTED`.
- **Verification:** the final supported-environment regression is run with
  isolated HOME/XDG roots. The release-preparation evidence records the exact
  command, result, raw-log hash, artifact hashes, and clean-install checks.

## Known limitations

- The compatibility matrix is not a claim that every listed environment has
  been executed; classifications remain exactly as documented in
  `artifacts/control/COMPATIBILITY-MATRIX.yaml`.
- Native Windows, network-filesystem guarantees, and cross-host distributed
  coordination are outside this release boundary.
- Remote tag creation, package-index publication, GitHub release, and other
  remote actions are not performed by release preparation.

## Maintainer action

Review the machine-readable release-preparation manifest and local checkpoint,
then independently decide whether to create `v1.1.0`, publish artifacts, and
announce the release.
