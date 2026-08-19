# WP-24 Instructions — Correctness Backport

**WP ID:** WP-24
**Objective:** Correct the v1.1 capture acknowledgement and recovery defects without changing the approved canonical-storage boundary.

## Dependencies

- None in the v1.2 roadmap.
- Baseline: current canonical repository state at planning start.

## Scope

- Make capture success depend on a durable append receipt from the canonical JSONL writer.
- Preserve duplicate classification and durable sequence information.
- Make recovery diagnose the repository's real derived SQLite schema (`zm_*`, including `zm_meta`/checkpoint metadata) rather than an obsolete `memories` table.
- Add executable regression and failure-path tests.
- Record reproducible artifact/release evidence without tagging, publishing, or changing release version.

## Out of scope

- `ZeroMemRuntime`, projection workers, public read API, authorization, sidecar, Hermes production composition, context/ranking, profiles, or retrieval evolution; those belong to later WPs.
- Destructive migration or canonical-history repair.
- New runtime dependencies, vector/graph databases, cloud services, release publication, tag/push.
- Rewriting historical v1.1 governance or acceptance evidence.

## Required invariants

1. JSONL append-only event log is canonical memory-event truth for v1.2+.
2. Capture success is impossible when canonical append/durability fails.
3. Projection/SQLite state is derived and may be missing, stale, corrupt, or unavailable.
4. Recovery diagnoses from actual schema and never repairs canonical JSONL from SQLite.
5. Errors are typed/sanitized; no secrets or developer-specific paths enter evidence.
6. Existing v1.1 API compatibility is preserved unless the correction is required by the approved contract.

## Allowed changes

- `zero_mem/core.py`, `zero_mem/recovery.py`, and the smallest related public/storage adapters.
- New or amended WP-24 tests and WP-24 planning/evidence documentation.
- Non-destructive project-state metadata required to record this authorized execution.

## Prohibited changes

- Changes to the unified specification, approved amendment, ADR-009, historical v1.1 evidence, or unrelated WPs' implementation.
- Treating SQLite/indexes/Obsidian as canonical memory truth.
- Silent fallback from a failed append to `CAPTURED`.
- Broad refactoring, dependency installation, destructive filesystem/Git operations, or publication.

## Required inputs

- Unified specification, Spec Amendment 001, ADR-009, v1.2 Master Plan.
- Current source/tests and current repository SHA.
- User authorization: `AUTONOMOUS_EXECUTION_AUTHORIZATION`, scope `WP-24..WP-35`.

## Required outputs

- Corrected capture/recovery behavior with tests.
- Completed WP planning package.
- Executable acceptance evidence and artifact baseline evidence.
- Updated WP-24 state only after acceptance passes.

## Security and data-integrity boundaries

Authorization is not implemented in WP-24, but no new read/write bypass may be introduced. Canonical JSONL must remain append-only. Test fixtures use isolated temporary roots; no real Hermes home, secrets, or external corpus.

## Escalation conditions

Escalate immediately for architecture/spec/ADR conflict, canonical corruption or destructive migration requirement, security weakening, unowned scope, required system-wide mutation, or three repeated unresolved failure fingerprints.

## Completion conditions

WP-24 may become `VERIFIED` only after focused functional/failure tests, recovery-schema tests, artifact/reproducibility checks, relevant regression tests, diff/path/security review, and evidence bound to the tested state all pass.
