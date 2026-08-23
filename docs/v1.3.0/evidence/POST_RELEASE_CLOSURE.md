# Zero-Mem v1.3.0 — Post-Release Closure Record (local release)

**Status:** `RELEASED_LOCAL` — no remote push
**Date:** 2026-08-23
**Operator:** Builder (v1.3.0 lifecycle) under user approval `APPROVE-RELEASE-V130.md`

## 1. Release identity (verified verbatim)

```text
$ git rev-parse master
498375668ff8fdad07a536826b15a213eec194b7

$ git rev-parse release/v1.3.0
498375668ff8fdad07a536826b15a213eec194b7

$ git rev-list -n 1 v1.3.0
498375668ff8fdad07a536826b15a213eec194b7

MASTER_SHA = RELEASE_BRANCH_SHA = TAG_TARGET = 498375668ff8fdad07a536826b15a213eec194b7
```

- Fast-forward: `975b268` → `4983756` (--ff-only, OK).
- Tag: annotated `v1.3.0`, immutable, target = release commit.
- **No push performed** — local-only release per user approval §4.
- ARTIFACT_SOURCE_SHA: no wheel/sdist built in this local release; the qualified
  source revision is the release commit itself (`4983756…`). If artifacts are
  later built for publication, they MUST be rebuilt from this exact SHA and the
  invariant re-verified per GITHUB-POLICY §5.

## 2. Qualification evidence

- Final suite at release SHA: **3.424 passed / 0 failed** ≥ baseline 3.378
  (`zero-mem-dev-data/evidence/v130-gateD-final-suite.log`).
- Gate D e2e review: PASS-WITH-NOTES, findings remediated (`fb0fab7`).
- Benchmark: synthetic N=5,000 all-fix green; real corpus token-savings 83.53% (n=25 sanity).

## 3. Runtime requirement (release notes)

SQLite ≥ 3.35 for migrate_11 down; up unaffected. Tracker 3/3 ticked in
EVIDENCE.md Known limitations before tag. Dev environment verified SQLite 3.53.1.

## 4. Remaining open items (for v1.4)

- selection-shape registry #4/#5: is_verified vs M1 VerificationStatus enum mismatch
  (baseline behavior; NEEDS DECISION if changed).
- Representative token-savings corpus (≥500 events or synthetic long-history).
