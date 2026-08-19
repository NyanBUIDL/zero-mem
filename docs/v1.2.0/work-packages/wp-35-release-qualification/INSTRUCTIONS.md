# WP-35 Instructions

**WP:** WP-35 Release Qualification
**Status:** `VERIFIED`
**Dependencies:** WP-24 through WP-34; all dependencies must be VERIFIED before final qualification.

## Objective

Qualify the current v1.2 working tree as a release candidate without publishing it: end-to-end lifecycle evidence, failure/recovery coverage, clean-install/package checks, reproducibility/provenance, and explicit support/limitation reporting.

## Scope

- Verify direct API, sidecar, Hermes runtime, capture receipt, projection, authorized retrieval, context, restart, and recovery paths through existing tests and bounded smoke harnesses.
- Run the full isolated regression and required targeted security/failure suites.
- Build wheel and sdist without changing the public version; verify contents, hashes, repeatability, and clean installation in a fresh local venv.
- Scan artifacts for credentials, developer paths, temp paths, tests, caches, and unintended files.
- Record unsupported chaos cases honestly when they require destructive/system-wide actions or cannot be safely reproduced.

## Out of scope / prohibited

- `git tag`, push, GitHub Release, PyPI/package publication, announcement, or final version bump.
- Destructive canonical-data operations, real-vault writes, system-wide installs, sudo, or network-dependent release actions.
- New architecture, dependency, migration, feature implementation, or release automation.

## Required invariants

- JSONL/event log remains canonical; SQLite/FTS/projections/checkpoints are derived and rebuildable.
- Authorization precedes discovery/render/context influence.
- Receipt success implies canonical durability.
- Recovery is read-only to canonical sources, bounded, deterministic, idempotent, and non-destructive.
- Hermes/sidecar failures are bounded and fail closed without process-wide corruption.
- Artifacts are reproducible and contain no secret, developer path, temporary runtime state, or test-only payload.

## Required outputs

A complete evidence package containing exact commands/results, artifact SHA-256 hashes, package content/provenance checks, clean-install result, E2E/failure matrix, regression result, known baseline limitation, and final independent review.

## Escalation conditions

Escalate any unresolved critical/high security finding, canonical-data risk, unowned failure, required destructive/system-wide operation, package/version authority conflict, unsupported claim, or publication request.

## Completion conditions

All executable release gates pass, unsupported cases are explicitly bounded, artifacts are locally qualified, no publication occurs, and `ZERO_MEM_V1_2_STATUS: RELEASE_CANDIDATE_READY` is recorded only after independent review.
