# v1.3.2 GitHub Publication Record

**Status:** PUBLISHED — 2026-08-23

## Identity & invariant (§5 GITHUB-POLICY)

- MASTER_SHA = RELEASE_BRANCH_SHA = TAG_TARGET = `6352c1f3138c03e8b938366504e1e475a7e2ce95`
  (annotated tag object `22d59ab` → commit `6352c1f`)
- ARTIFACT_SOURCE_SHA = `6352c1f` (release notes from tree at that SHA; no binary assets)
- Precondition: v1.3.1 RELEASED_PUBLISHED trước khi tag v1.3.2 (đúng thứ tự
  APPROVE-RELEASE-V132).

## Authorization

- APPROVE-RELEASE-V132.md (user-signed, workspace root) — tag + push + GitHub Release.

## Divergence handled (§10)

- Nguyên nhân: commit docs publication-record v1.3.1 (`ff8772e`) được tạo trên
  local master SAU khi push v1.3.1 → master lệch 1 commit so với remote.
- Xử lý additive: cherry-pick `ff8772e` vào release/v1.3.2-remediation
  (conflict giải theo phía published record), repoint local master về
  `07ab93e` (== github/master, before-state lưu trong evidence), rồi ff-only
  merge lại. Không force-push, không rewrite lịch sử đã publish.
- Evidence: zero-mem-dev-data/evidence/v132/publish-v132-divergence.log

## Policy clauses checked (docs/governance/GITHUB-POLICY.md)

| § | Clause | Compliance |
|---|---|---|
| 2 | canonical remote verified | ls-remote khớp NyanBUIDL/zero-mem |
| 3/5 | ff-only merge + SHA invariant | held: master=branch=tag=`6352c1f` |
| 6 | immutable tag; release sau verify ref | GH Release tạo sau khi ls-remote xác nhận tag |
| 7 | explicit refs only, no force | push 3 refs tường minh |
| 10 | divergence inspected & preserved | cherry-pick + before-state log |
| 13/14 | mutation recorded | this file + publish-v132-*.log |

## Refs after publish

```
refs/heads/master                        6352c1f
refs/heads/release/v1.3.2-remediation    6352c1f
refs/tags/v1.3.1                         357761d (→ 07ab93e) — không đụng
refs/tags/v1.3.2                         22d59ab (→ 6352c1f)
GitHub Releases: .../releases/tag/v1.3.1 · .../releases/tag/v1.3.2
```
