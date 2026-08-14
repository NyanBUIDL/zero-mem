# Zero-Mem v1.1.0 — Hướng dẫn và lộ trình

## Trạng thái hiện tại

Nền tảng phát hành là **v1.0.0**. Dự án đang ở giai đoạn **V1.1.0 RE-PLANNING**: mã nguồn được đóng băng, WP-00 là work package duy nhất đang hoạt động (`READY FOR REVIEW`), và chưa có hạng mục triển khai nào được phép bắt đầu.

v1.1.0 nhằm biến Zero-Mem thành một sidecar bộ nhớ cục bộ, độc lập agent, với dữ liệu truy nguyên được, quyền truy cập rõ ràng và giao diện công khai ổn định. Hermes vẫn là adapter tùy chọn.

## Mục tiêu của v1.1.0

Phiên bản này giải quyết hai nhóm việc:

1. Khoảng trống quan sát được ở v1.0.0: độ bền, độ mới dữ liệu, mở rộng, đồng thời, đóng gói, cấu hình, quan sát và tương thích.
2. Các yêu cầu sản phẩm chưa có trong kế hoạch cũ: sidecar/MCP cục bộ, profile/knowledge space, Obsidian có review/write-back và traceability đầy đủ.

## Kiến trúc mục tiêu

```text
Hermes (tùy chọn) ─┐
Agent / ứng dụng khác ─┼─> Giao diện Zero-Mem ─> lõi lưu trữ, quyền và truy xuất
Người dùng / Obsidian ─┘                                  │
                                                            v
                              trace append-first + metadata canonical
                                                            │
                                                            v
                           chỉ mục / đồ thị / Obsidian có thể dựng lại
```

Các nguyên tắc bắt buộc:

- Bí mật được che hoặc từ chối trước mọi điểm lưu trữ.
- Dữ liệu trace chuẩn giữ lịch sử/provenance theo append-first; chỉ mục và bản chiếu có thể dựng lại.
- Kiểm tra quyền xảy ra trước mọi khả năng ảnh hưởng đến kết quả, kể cả số lượng, điểm, cache và lỗi thời gian.
- Không bắt buộc gọi LLM hay mạng ngoài cho thao tác bộ nhớ thông thường.
- Obsidian là bản chiếu dành cho con người, không phải raw store hay retrieval engine.

## Lộ trình theo work package

| Chặng | Work package | Kết quả dự kiến |
|---|---|---|
| 0. Đối chiếu nền tảng | WP-00 | Xác nhận v1.0.0, `master`, F-001–F-014, nguồn yêu cầu và quy tắc phê duyệt. |
| 1. Ranh giới kiến trúc | WP-01, WP-02 | Lõi độc lập agent, ownership runtime và ranh giới import/state. |
| 2. Cấu hình và dữ liệu chuẩn | WP-13, WP-04 | Cấu hình có kiểu; JSONL append-first, metadata SQLite, freshness, retention, delete, replay/rebuild. |
| 3. Hiệu năng và truy xuất | WP-03, WP-05, WP-20, WP-06 | Truy xuất có quyền và giới hạn, profile/knowledge space, xếp hạng xác định được, ngân sách ngữ cảnh. |
| 4. Hợp đồng agent và sidecar | WP-08, WP-11, WP-12, WP-14, WP-15, WP-21 | API, lifecycle sync/async, đa tiến trình, recovery, observability và MCP cục bộ. |
| 5. Tích hợp và migration | WP-07, WP-09, WP-17, WP-10 | Hermes adapter tùy chọn, tương thích ngược, migration/rollback và đóng gói. |
| 6. Obsidian | WP-22 | Vault quản lý, provenance, bản chiếu, review/write-back và xử lý xung đột. |
| 7. Bảo đảm chất lượng | WP-16, WP-18, WP-19 | Kiểm thử, benchmark, tài liệu và quyết định go/no-go. |

Đường găng:

```text
WP-00 → WP-01 → WP-02 → WP-13 → WP-04 → WP-08 → WP-11 → WP-12
      → WP-14 → WP-15 → WP-21 → WP-07 → WP-17 → WP-10 → WP-16/WP-18 → WP-19
```

## Giao diện đọc công khai dự kiến

| Khả năng | Mục đích |
|---|---|
| `zero_mem.search` | Tìm trace trong phạm vi được cấp quyền. |
| `zero_mem.get_trace` | Đọc trace cùng provenance và trạng thái. |
| `zero_mem.get_task_state` | Khôi phục trạng thái nhiệm vụ. |
| `zero_mem.get_decisions` | Lấy quyết định liên quan đã biết. |

`zero_mem.expand`, `zero_mem.propose_memory` và `zero_mem.project_to_obsidian` được dành tên nhưng hoãn sau MVP.

## Điều kiện phát hành

v1.1.0 chỉ được phát hành khi dữ liệu chuẩn có thể replay/rebuild; mọi mode profile được kiểm thử chống rò rỉ; API/MCP/Hermes/generic client có conformance; Hermes fail-safe; Obsidian có review/write-back không tạo vòng lặp; bảo mật, migration/rollback, tương thích, cài đặt và benchmark đều có bằng chứng tái lập.

## Tài liệu gốc

| Mục đích | Tài liệu |
|---|---|
| Trạng thái vận hành | [STATUS.md](v1.1.0/STATUS.md) |
| Kế hoạch đầy đủ | [MASTER_PLAN.md](v1.1.0/MASTER_PLAN.md) |
| Baseline v1.0.0 | [V1.0.0_BASELINE.md](baseline/V1.0.0_BASELINE.md) |
| Audit và phát hiện | [FINDINGS_INDEX.md](audit/FINDINGS_INDEX.md) |
| Quy tắc thay đổi | [AGENTS.md](../AGENTS.md) |
