# v1.3.1 GitHub Publication Record

**Status:** PENDING — KHÔNG publish trong vòng v1.3.2.

- Ngày ghi: 2026-08-23
- APPROVE-RELEASE-V131.md: KHÔNG tồn tại (workspace root + repo) → không đủ
  điều kiện tag/push/release theo GITHUB-POLICY và stop rule V132-FULL-PROMPT #0.
- User quyết định qua chat 2026-08-23: "WP-3: ghi PENDING vào evidence
  (WP3-C2a), dừng WP-3 tại đó, các WP khác chạy tiếp bình thường. Publish
  v1.3.1 sẽ làm riêng sau khi user soạn APPROVE-RELEASE-V131.md — KHÔNG tự
  push trong vòng này."
- Trạng thái drift hiện tại: local `release/v1.3.1-remediation` ahead
  `github/master` 11 commit, chưa tag v1.3.1.
- Hành động khi có approval sau này: làm theo GITHUB-POLICY từng bước —
  tag v1.3.1 trên `release/v1.3.1-remediation`, push branch + tag, merge/
  fast-forward master, tạo GitHub Release từ RELEASE-NOTES-v1.3.1.md, cập
  nhật record này từ PENDING thành PUBLISHED kèm SHA.
