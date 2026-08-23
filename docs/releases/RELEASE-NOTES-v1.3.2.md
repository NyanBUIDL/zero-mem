# Zero-Mem v1.3.2 — Release Notes (DRAFT, chưa release)

**Branch:** `release/v1.3.2-remediation` · **Date:** 2026-08-23
KHÔNG tag/push cho tới khi user duyệt APPROVE-RELEASE-V132.md.

## Security-adjacent behavior change (an toàn hơn — chỉ block thêm)

### Redaction gate marker-abuse hardening (WP-02 / audit P1-3)

- **Cũ (v1.3.1 WP-6):** gate strip mọi nội dung khớp mẫu lỏng
  `«redacted:…»` trước secret-scan → nội dung attacker-control giống marker
  (kèm token thật bên trong) đi vòng qua scan.
- **Mới (v1.3.2):** dòng chỉ được bỏ qua scan khi chứa marker đúng format
  production phát ra: `«redacted:[REDACTED:<rule>]»` với `<rule>` thuộc bộ
  rule đóng của redactor (api_key_assignment, authorization_header,
  bearer_token, credential_url_userinfo, oauth_secret, password_assignment,
  private_key_block). Mọi biến thể gần-dúng (đổi case, thêm khoảng trắng,
  chữ lạ, rule không hợp lệ, nội dung tự do) đều bị scan bình thường.
- Chiều thay đổi: CHỈ block nhiều hơn, không mở lối đi nào mới. Case
  fail-closed (secret thuần vẫn block) giữ nguyên.

## Bug fixes

### is_verified enum alignment (WP-01 / audit P1-1, D-01 Option A)

- `src/integration/m7/eligibility.py`: `is_verified` so khớp enum
  VerificationStatus thật (mọi giá trị ≠ none) thay vì tuple
  `("verified","confirmed")` không bao giờ khớp → event verify chuẩn giờ
  classify PRIMARY đúng; lifecycle check `"confirmed"` giữ nguyên taxonomy.
- Ghi nhận OPEN QUESTION (không sửa ngoài phạm vi):
  `src/integration/m7/budget.py:51` còn cùng kiểu conflates trong
  verified_rank (ranking-only, behavior-neutral hôm nay).

## Governance

- WP-03: publish v1.3.1 PENDING — không có APPROVE-RELEASE-V131.md trong
  vòng này; publish làm riêng sau approval (quyết user 2026-08-23).
- Machine state: project-state.yaml là nguồn duy nhất;
  implementation-plan.json chuyển RECORD-LỊCH-SỬ (WP-05).
- Master spec .docx freeze + hash-anchor ADR (WP-06).
