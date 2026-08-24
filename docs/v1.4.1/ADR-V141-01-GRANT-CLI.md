# ADR-V141-01 — Số phận grant CLI trong v1.4.1 (DEF-013)

**Trạng thái:** DRAFT — chờ maintainer chọn tại GATE-R1
**Ngày:** 2026-08-25 · **Liên quan:** DEF-013 · **WP:** V141-R1

## Bối cảnh

v1.4.1-WIP thêm `zero-mem grant add/list/revoke` + `zero-mem config …`
(`zero_mem/commands_config_grant.py`, wiring trong `cli.py`, doctor check). Deep review lần 2
+ Graphify (snapshot `v141-r1-scout`, 8876 nodes / 24905 edges) xác nhận:

- CLI chỉ nối vào `cli.py`; **không có directed path** tới `m6/handlers.py`.
- Đường ủy quyền production: `_open_facade` → `_resolve_grants` → `resolve_read_grants`
  đọc grants từ **derived store chính** của sidecar (`runtime.open_grants()`).
- CLI ghi/đọc store riêng (`$XDG_DATA_HOME/zero-mem/grants-derived.sqlite` +
  `grants-events.jsonl`) ⇒ grants tạo bằng CLI không bao giờ có hiệu lực thật; hai nguồn
  sự thật cho cùng một loại dữ liệu ủy quyền.

## Phương án A — Thu hồi CLI khỏi v1.4.1 (revert phần admin surface)

**Nội dung:** giữ nguyên core fix DEF-012 (M6Runtime corpus_store_path + wire 3 điểm +
userconfig + config CLI); loại khỏi v1.4.1: subcommand `grant` toàn bộ
(`run_grant_*`, `_open_admin`, `_grant_roots`, `_resolve_space_or_none`) + doctor check
`corpus_authorization` (hoặc hạ thành INFO liệt kê config, không claim PASS). Test CLI
tương ứng gỡ/thay bằng test pin rằng subcommand KHÔNG tồn tại (chống tái xuất hiện vô ý).

- ✅ Nhỏ nhất, dễ review, v1.4.1 trở thành pure hotfix DEF-012-wiring như định danh ban đầu.
- ✅ Loại ngay nguồn sự thật kép — không còn bề mặt chết để ai đó tin lầm grants đã hiệu lực.
- ✅ Không chạm canonical layout hay lifecycle của runtime.
- ❌ Mất tiện ích admin thủ công vừa viết (dù chưa bao giờ hoạt động thật).
- ❌ Công sức viết CLI + test (~357 dòng + 359 dòng test một phần thành dead effort).

**Phạm vi sửa:** `zero_mem/cli.py` (gỡ wiring), `zero_mem/commands_config_grant.py` (xóa
phần grant, giữ config), `zero_mem/commands_doctor.py` (sửa check), test v141 tương ứng.
Không đụng `src/**`.

## Phương án B — Wire CLI vào control-plane data-root thật

**Nội dung:** CLI phải resolve đúng data-root mà sidecar runtime đang dùng (cùng biến
config/env với runtime), event log ghi vào canonical JSONL stream chung của control-plane,
derived projection rebuild theo đường rebuild chuẩn (`src/access/rebuild.py`). Kèm thiết kế
lifecycle: CLI chạy khi sidecar đang mở store (lock/concurrency), idempotency replay,
quyền gọi CLI = quyền admin control-plane.

- ✅ Giữ được công cụ admin, đúng một nguồn sự thật.
- ❌ Chạm canonical layout + lifecycle + concurrency — phạm vi lớn hơn nhiều so với một
  hotfix; cần thiết kế lock/replay kỹ, rà soát lại toàn bộ giả định M5/M6.
- ❌ Trái hướng v1.4.1 = smallest safe change; rủi ro trễ release và kéo defect mới.
- ❓ Nhu cầu thực tế chưa phát sinh: quản trị grant hiện làm qua control-plane nội bộ;
  CLI đa-agent/admin ngoài là yêu cầu tier enterprise (post-v1.5).

**Phạm vi sửa:** như A nhưng cộng thiết kế + implement wiring + concurrency tests; gần
như chắc chắn vượt khung hotfix.

## So sánh theo tiêu chí Decision Style của dự án

| Tiêu chí | A (revert) | B (wire thật) |
|---|---|---|
| Compliant với spec/biên | ✅ | ⚠️ cần ADR con + thiết kế |
| Kiến trúc nhất quán | ✅ khôi phục trạng thái đã verify | ⚠️ mở rộng bề mặt ủy quyền |
| Đơn giản hiểu/audit | ✅ nhỏ nhất | ❌ |
| Dễ test | ✅ | ⚠️ concurrency/lifecycle |
| Chi phí chạy | ✅ 0 | ⚠️ |
| Dễ đảo ngược | ✅ | ❌ |
| Tích hợp agent khác | trung tính | ✅ (lợi ích dài hạn) |

## Khuyến nghị

**Phương án A** cho v1.4.1; đăng ký nhu cầu "admin CLI đa-agent" vào backlog v1.5+
(cùng cụm enterprise authorization với DEF-010/011) — khi đó làm B một cách có thiết kế.

## Quyết định GATE-R1 (maintainer)

☐ CHỌN A — thu hồi grant CLI khỏi v1.4.1
☐ CHỌN B — wire CLI vào control-plane (chấp nhận scope mở rộng)
☐ Khác: ………
