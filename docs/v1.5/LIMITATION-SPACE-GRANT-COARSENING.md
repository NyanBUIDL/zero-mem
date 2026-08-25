# V150-WP1 — Documented Limitation: Space-Grant Coarsening (DEF-010)

**Trạng thái:** ACTIVE limitation (chấp nhận có chủ đích theo ADR-V150-01 Option A)
**Ngày:** 2026-08-25 · **Liên quan:** DEF-010 · Đóng khi: Option B (granular mapping) được duyệt

## Hành vi hiện tại

Knowledge-space grant trên event path hoạt động theo cơ chế resolution
(DEF-004 Option B): space được resolve thành tập `(profile_id, project_id)` sở hữu
corpus resource trong space đó, sau đó mọi event row thuộc cặp đó đều được authorize.

**Hệ quả:** grant đọc 1 knowledge_space hẹp ⇒ thực tế cấp quyền đọc toàn bộ events
của mọi (profile, project) có resource trong space đó. Grant space ≡ grant project
(về hiệu lực trên event store).

## Biên an toàn giữ nguyên

- Fail-closed đúng: không corpus conn, space rỗng, hoặc digest mismatch (V150-WP1
  DEF-011 gate armed) ⇒ DENY, không bao giờ over-authorize ngoài dữ liệu projection.
- Không ảnh hưởng cross-profile/cross-project policy base — chỉ mở rộng qua grant
  tường minh do maintainer cấp.
- Corpus path (`corpus_unit_search`) vẫn granular đúng theo `knowledge_space_id`
  trong schema.

## Ai bị ảnh hưởng

Tier cá nhân / single-agent: chấp nhận được (grant do chính user quản).
Tier enterprise (post-v1.5): KHÔNG đạt yêu cầu granular ủy quyền — phải dùng
Option B (mapping event↔ks cấp row, canonical-side) trước khi commercialize.

## Chẩn đoán

Doctor check `corpus_authorization` PASS/WARN như v1.4.1. Coarsening là thuộc tính
thiết kế hiện tại, không phải lỗi cấu hình — không có cảnh báo riêng để tránh noise;
limitation này là tài liệu tham chiếu chính thức.
