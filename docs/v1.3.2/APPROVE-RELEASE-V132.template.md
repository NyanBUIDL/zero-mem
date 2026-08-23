# APPROVE-RELEASE-V132 — TEMPLATE (chưa ký)

> Điền và lưu thành `APPROVE-RELEASE-V132.md` để mở khóa tag/publish v1.3.2.
> KHÔNG tag/push/release trước khi file này tồn tại với nội dung duyệt.

```
APPROVAL — Release Zero-Mem v1.3.2

Branch:      release/v1.3.2-remediation
Head at approval: <SHA>
Tag đề xuất: v1.3.2
Release notes: docs/releases/RELEASE-NOTES-v1.3.2.md
Evidence:    docs/v1.3.2/EVIDENCE.md · final suite 3474 passed / 6 skipped
             zero-mem-dev-data/evidence/v132/final-suite.log

[ ] Tôi đã đọc docs/v1.3.2/CLOSURE.md và EVIDENCE.md
[ ] Chấp nhận behavior change WP-02 (redaction gate hardening)
[ ] Chấp nhận D-01..D-04 như ghi trong DECISIONS-V132.md
[ ] Lưu ý: v1.3.1 CHƯA publish — thứ tự publish mong muốn:
      ( ) v1.3.1 trước (cần APPROVE-RELEASE-V131.md riêng), sau đó v1.3.2
      ( ) chỉ v1.3.2

Ký tên / ngày: ______________  2026-__-__
```

Điều khoản thực thi sau approval (theo GITHUB-POLICY): tag v1.3.1 (nếu duyệt)
trên đúng commit của release/v1.3.1-remediation, push branch+tag, merge master
fast-forward-only, GitHub Release từ release notes, publication record cập nhật.
