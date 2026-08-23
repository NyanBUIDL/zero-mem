# v1.3.0 — GitHub Publication Mutation Record

**Date:** 2026-08-23 | **Operator:** Builder | **Authorization:** user ("release trên github đi", 2026-08-23)

## Pre-mutation inspection (GITHUB-POLICY §2/§5)

- Remote: `github` → `git@github.com:NyanBUIDL/zero-mem.git` (canonical, verified).
- Remote master pre-push: `37bf575c…` (ancestor of local) → local master ahead 42 commits → **fast-forward, no divergence**.
- Local divergence `master...release/v1.3.0` = `0 2` (2 corpus-tooling commits ahead on release branch) — resolved by ff master to include them.

## Actions

1. `git fetch github` — remote state confirmed.
2. `git checkout master && git merge --ff-only release/v1.3.0` → master `19996c2` → `1aa1e84` (additive ff, 4 corpus files).
3. `git push github master release/v1.3.0 v1.3.0`:
   - `37bf575..1aa1e84 master -> master` (fast-forward)
   - `[new branch] release/v1.3.0`
   - `[new tag] v1.3.0`
4. `gh release create v1.3.0` (title + release notes) → https://github.com/NyanBUIDL/zero-mem/releases/tag/v1.3.0

## Remote verification (post-push, full object IDs)

- remote `master` = `1aa1e84b839b3263cd1e5b82be996d6c2371040f`
- remote `release/v1.3.0` = `1aa1e84b839b3263cd1e5b82be996d6c2371040f`
- remote tag `v1.3.0` (annotated) target (peeled `^{}`) = `498375668ff8fdad07a536826b15a213eec194b7`
- local tag target = `498375668ff8fdad07a536826b15a213eec194b7` → **MATCH**

## Invariant (release qualification)

```
RELEASE_BRANCH_SHA (at release) = 4983756  (tag target, immutable)
MASTER = RELEASE_BRANCH = 1aa1e84  (advanced post-tag with corpus tooling — normal)
TAG_TARGET = 4983756  (unchanged, immutable)
ARTIFACT_SOURCE_SHA = 4983756  (qualified release commit)
```

## Checks run

- No force push; all pushes fast-forward / new refs.
- No history rewrite; tag immutable, not moved.
- Release notes from `docs/releases/RELEASE-NOTES-v1.3.0.md`.
- No secrets in any pushed content.

## Remaining risk

- `master`/`release/v1.3.0` at `1aa1e84` include the corpus-tooling commits (post-release dev), which are NOT in the `v1.3.0` tag — expected, tag is a frozen snapshot.
