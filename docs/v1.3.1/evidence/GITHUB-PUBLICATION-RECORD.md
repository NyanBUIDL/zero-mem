# v1.3.1 GitHub Publication Record

**Status:** PUBLISHED — 2026-08-23

## Identity & invariant (§5 GITHUB-POLICY)

- MASTER_SHA = RELEASE_BRANCH_SHA = TAG_TARGET = `07ab93edf6f91e07b0467cce121fcdabec18257f`
  (annotated tag object `357761d` → commit `07ab93e`)
- ARTIFACT_SOURCE_SHA = `07ab93e` (release notes from tree at that SHA; no binary assets)

## Authorization

- APPROVE-RELEASE-V131.md (user-signed, workspace root) — tag + push + GitHub
  Release approved; master merge allowed via ff-only (policy §5 SHOULD).
- Open question WP-8 closed by user decision (Option A done in v1.3.2 WP-01).

## Policy clauses checked (docs/governance/GITHUB-POLICY.md)

| § | Clause | Compliance |
|---|---|---|
| 2 | canonical remote verified | `git@github.com:NyanBUIDL/zero-mem.git`, ls-remote matched |
| 3 | branch model / no history rewrite | ff-only merge `8264711..07ab93e`, 0 divergent commits on master side |
| 4 | clean classified worktree | pre-state log clean at mutation time |
| 5 | normative order + SHA invariant | merge → verify → tag → verify → push → verify → release; invariant held |
| 6 | immutable tag, release after tag verify | new annotated tag; release created after remote ref verified |
| 7 | explicit refs push only, no force | `git push github <3 explicit refs>`; no force flags |
| 13/14 | stop conditions n/a; mutation recorded | this file + evidence/v132/publish-v131-*.log |

## Refs after publish

```
refs/heads/master                        07ab93e
refs/heads/release/v1.3.1-remediation    07ab93e
refs/tags/v1.3.1                         357761d (→ 07ab93e)
GitHub Release: https://github.com/NyanBUIDL/zero-mem/releases/tag/v1.3.1
```

Evidence: zero-mem-dev-data/evidence/v132/publish-v131-{prestate,tag,push}.log
