# V122-00 — Baseline and Evidence Integrity

**Status:** VERIFIED
**Review:** `V122-00-EXACT-TREE-REPLACEMENT-REVIEW-001`
**Baseline SHA:** `af01e494a29410b11dd6d5c4c78275e6e08604df`
**Approval:** `MAINTAINER_APPROVAL_V122_00_2026_08_20`
**Audit IDs closed:** A-02 verification, A-07 evidence provenance
**Prerequisites:** Clean detached worktree from `github/release/v1.2.2`; no predecessor package.
**Allowed scope:** Baseline/tag/artifact/WP-33 verification, package evidence, verifier and package tests.
**Forbidden scope:** V122-01 through V122-06, product runtime/API/schema/architecture changes, remote mutation, tag/release/PyPI mutation.

## Authority read

- [x] Repository `AGENTS.md` and GitHub policy
- [x] Architecture, Spec Amendment 001, ADR-009
- [x] v1.2.2 agent-development-system `00` through `07`
- [x] External execution system `MASTER-EXECUTION.md`, shared gates, and `03-V122-00.md`

## Contract and implementation boundary

The verifier now validates both the source-bound JSON manifest and the required evidence schema: mandatory evidence files, required metadata markers, sanitized hash paths, source-SHA presence, and per-command raw-log/hash linkage. It does not inspect or mutate canonical memory, SQLite, runtime state, public APIs, or release refs.

Changed owners are limited to:

- `scripts/verify_v122_evidence.py`
- `tests/unit/test_v122_evidence_verifier.py`
- this package record
- `artifacts/evidence/v1.2.2/<baseline-sha>/`

## Acceptance evidence

- v1.2.1 tag and canonical remote identity were verified; tag resolves to `d1dfc9e144cf822e8db919ee260a267c6e37fc91`.
- v1.2.1 GitHub release assets were downloaded and checked against the published `SHA256SUMS.txt`.
- WP-33 imported and passed its three existing tests.
- WP-33 ran twice with corpus size 25/repeats 3 and produced equal deterministic non-latency results and digest `3d2490032cce9d63d25c16b5ec50709a7690b9b48b1c31d78f4fc715b7c87fd4`.
- The new verifier passed its valid fixture and negative source/log/asset/collection cases, including collection-count, malformed-record, unsafe/backslash-path, and elapsed-linkage probes.
- The current focused suite passed 7 tests with zero failures; two final collection runs each reported 3,279 tests and zero collection errors.
- The verifier accepted the source-bound package manifest at the exact baseline SHA.

## Known exception

An initial collection command executed without an explicit `cd` collected against the surrounding workspace and returned 989 import-collection errors. It was excluded from source-bound evidence because its diagnostics exposed host paths. The final controlled commands executed from the exact worktree and each collected 3,279 tests with zero errors.

## Status transition

`PLANNED → APPROVED → IN_PROGRESS → IMPLEMENTED → VERIFIED` is supported by the maintainer approval reference, exact baseline, bounded changed paths, focused tests, self-review, source-bound evidence verification, and replacement review `V122-00-EXACT-TREE-REPLACEMENT-REVIEW-001` with no blocking findings.
