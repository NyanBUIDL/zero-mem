# v1.4.0 PUBLICATION RECORD — RELEASED_PUBLISHED

**Date:** 2026-08-25 · **Operator:** Zero-Mem build agent (authorized by GATE-FINAL APPROVAL)
**Policy:** docs/governance/GITHUB-POLICY.md (§2,§5,§6,§7,§13)

## Mutation record (GITHUB-POLICY §14)

- **Repository identity:** NyanBUIDL/zero-mem (verified: `git@github.com:NyanBUIDL/zero-mem.git`)
- **Canonical remote:** github (fetch+push → NyanBUIDL/zero-mem) ✓
- **Branch:** master (local + remote)
- **Authorization:** GATE-FINAL APPROVED (GATE-FINAL-APPROVAL.md, 2026-08-25) — push master ff từ 83194ba + tag v1.4.0 + GH Release.

## Inspection before mutation (§2/§5)

| Check | Value |
|---|---|
| git rev-parse --show-toplevel | /home/lenovo/Hermes Workspace/zero-mem-v123-engineering |
| branch --show-current | master |
| HEAD (local) | 246a2f1 (pre-publish) / 83194ba (release commit) |
| status --short | clean |
| remote get-url github | git@github.com:NyanBUIDL/zero-mem.git ✓ |
| remote master (ls-remote) | 789db918 |
| local tag v1.4.0 | 83194ba |

## SHA invariant (§5/§13)

```
MASTER_SHA        = 83194ba0761066fa3de47a05a4ca72937e6c691f
RELEASE_BRANCH    = 83194ba (ff from remote 789db918, verified)
TAG_TARGET        = 83194ba (v1.4.0 annotated, deref)
ARTIFACT_SOURCE   = 83194ba
=> ALL EQUAL ✓
```

## Mutations performed

1. **Push master (ff-only, no force):**
   `git push github 83194ba:refs/heads/master`
   → `789db91..83194ba` (fast-forward, exit 0)

2. **Push tag v1.4.0 (annotated, →83194ba):**
   `git push github v1.4.0`
   → `[new tag] v1.4.0 -> v1.4.0` (exit 0)
   Note: `git ls-remote` shows `cd10e430` for `refs/tags/v1.4.0` (annotated tag
   OBJECT sha); `refs/tags/v1.4.0^{}` = `83194ba` (commit). Verified deref matches
   master — invariant HOLDS (false-alarm cleared before any corrective action).

3. **GitHub Release created:**
   `gh release create v1.4.0 --title "Zero-Mem v1.4.0" --notes-file docs/releases/RELEASE-NOTES-v1.4.0.md`
   → URL: https://github.com/NyanBUIDL/zero-mem/releases/tag/v1.4.0
   → publishedAt: 2026-08-24T18:41:16Z, isDraft=false, isPrerelease=false,
     targetCommitish=master.

## Post-mutation verification (§5)

- Remote master = `83194ba` ✓
- Remote tag v1.4.0^{} = `83194ba` ✓
- Invariant MASTER_SHA = TAG_TARGET = ARTIFACT_SOURCE_SHA = `83194ba` ✓
- GitHub Release exists, tagName=v1.4.0, targetCommitish=master, URL confirmed.

## Publication record (status update)

- project-state.yaml: `v140_status: RELEASED_PUBLISHED` + v140_release_tag/sha/url/invariant/final_suite.
- docs/v1.4/EVIDENCE.md: V140-05 status RELEASED_PUBLISHED + Publication record block.
- docs/v1.4/CHECKLIST.md: V140-05 ticked, Gate log GATE-FINAL row.
- Local commit `2891c1d` carries the above; intentionally NOT pushed to remote
  master to preserve the published SHA invariant (remote master = tag = 83194ba).
  Publication record is also present in EVIDENCE.md at the released commit 83194ba.

## Remaining risk / notes

- Local master HEAD (`2891c1d`) is 1 commit ahead of remote master (`83194ba`).
  This is the post-release publication-record commit, intentionally unpushed to
  keep the immutable release invariant intact. No remote divergence, no conflict.
- No force-push, no tag move, no history rewrite, no secret leakage.
- DEF-010/011 remain OPEN/deferred (v1.5+), per maintainer decision.

## Evidence artifacts

- RELEASE-NOTES: docs/releases/RELEASE-NOTES-v1.4.0.md
- EVIDENCE: docs/v1.4/EVIDENCE.md (V140-05 publication record)
- GitHub Release: https://github.com/NyanBUIDL/zero-mem/releases/tag/v1.4.0
- Tag SHA: 83194ba0761066fa3de47a05a4ca72937e6c691f
