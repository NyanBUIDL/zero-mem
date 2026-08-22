# v1.3.0 — Chỉ mục bằng chứng

> Tạo từ `docs/VERSION-TEMPLATE.md` (mục EVIDENCE). Điền khi chạy gate.

## Tested SHA
- Product SHA: `<40 hex>` (CI-tested)
- Branch head: `<40 hex>`

## Matrix
| Gate | Kết quả | Lệnh | Log/Checksum |
|---|---|---|---|

## Work-package evidence
| WP | Evidence | Verdict |
|---|---|---|

## Verifier
- Independent verifier verdict: PENDING — link artifact khi có.

## Git protocol
- Commits: chỉ stage exact paths; `git diff --check` sạch; không `git add .`.
- Release invariant: `MASTER_SHA = RELEASE_BRANCH_SHA = TAG_TARGET = ARTIFACT_SOURCE_SHA`.

## Known limitations
- <ghi trung thực: thứ chưa chạy, thứ bị skip có lý do, platform chưa test>
- Baseline P1 (v1.2.4): functional, corpus tổng hợp nhỏ; chưa phải gate release.
