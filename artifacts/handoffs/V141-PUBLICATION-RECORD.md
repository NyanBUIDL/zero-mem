# v1.4.1 PUBLICATION RECORD — RELEASED_PUBLISHED

**Date:** 2026-08-25 · **Operator:** Zero-Mem build agent (authorized by maintainer chat: "tôi muốn bạn release 1.4.1")
**Policy:** docs/governance/GITHUB-POLICY.md (§2, §5, §6, §7, §13, §14)

## Mutation record (§14)

- **Repository identity:** NyanBUIDL/zero-mem (`git@github.com:NyanBUIDL/zero-mem.git`) ✓
- **Branch:** master (local + remote)
- **Authorization:** GATE-FINAL-V141 APPROVED (phương án 1 re-tag) + chỉ thị chat 2026-08-25 sáng: release v1.4.1.
- **Preflight:** full suite `3521 passed, 6 skipped, 0 failed` trên tree cuối
  (`/tmp/zm_v141_preflight.txt`, Py 3.11, isolated HOME); `__version__ = "1.4.1"`; tree clean.

## SHA invariant (§5)

```
MASTER_SHA     = 33eff62c8613d1097cf132cc72c4975bcbee4f66
TAG_TARGET     = 33eff62… (v1.4.1 annotated, deref)
ARTIFACT_SOURCE= 33eff62… (suite chạy đúng commit này)
REMOTE_MASTER  = 33eff62… (sau push)   [trước: 83194ba]
=> ALL EQUAL ✓
```

## Mutations performed

1. **Tag retarget trước publish (local only, hợp lệ vì remote chưa từng có tag):**
   tag cũ `v1.4.1`→`be925dd` (sáng, phương án 1) → xoá, tạo lại `v1.4.1`→`33eff62`
   để invariant MASTER_SHA = TAG_TARGET giữ nguyên sau khi push master tới HEAD.
2. **Push master (ff-only):** `git push github 33eff62:refs/heads/master`
   → `83194ba..33eff62` (10 commits, fast-forward, exit 0).
3. **Push tag:** `git push github v1.4.1` → `[new tag]` (exit 0).
4. **GitHub Release:** `gh release create v1.4.1 --title "Zero-Mem v1.4.1" --notes-file docs/releases/RELEASE-NOTES-v1.4.1.md`
   → https://github.com/NyanBUIDL/zero-mem/releases/tag/v1.4.1
   publishedAt 2026-08-25T03:33:19Z, isDraft=false, isPrerelease=false.

## Post-mutation verification (§5)

```
git ls-remote:
  refs/heads/master    = 33eff62… ✓
  refs/tags/v1.4.1     = baca3e37 (annotated OBJECT sha — expected)
  refs/tags/v1.4.1^{}  = 33eff62… ✓ (deref = master = ARTIFACT_SOURCE)
gh release view: tagName=v1.4.1, targetCommitish=master, published ✓
```

## Status updates

- `project-state.yaml`: `v141_status: RELEASED_PUBLISHED` + release_tag/sha/url/invariant/final_suite (commit kế tiếp, cố tình KHÔNG push để giữ invariant remote master = tag = 33eff62 — same pattern as v1.4.0).
- EVIDENCE: docs/v1.4.1/EVIDENCE.md publication block.

## Remaining notes

- Local master sẽ ahead 1 docs-commit so với remote sau khi ghi state — intentional,
  giống pattern v1.4.0 (publication-record commit không push để bảo toàn SHA invariant).
- No force-push, no history rewrite, no secret leakage.
