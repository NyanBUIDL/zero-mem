# 00 — Start Here

## Hợp đồng vận hành v1.2.4

Zero-Mem là sidecar bằng chứng local-first cho Hermes. Hermes vẫn điều phối agent, quyết định gọi tool và tạo câu trả lời cuối. Zero-Mem quan sát, khử bí mật, ghi canonical event, dựng derived index và cung cấp kết quả đọc có authorization/provenance.

```text
Hermes / direct caller
        │
        ▼
capture boundary ── redact + validate + append
        │
        ▼
canonical JSONL ── projection ──► derived SQLite/FTS5
        │                              │
        └──────── evidence ────────────┤
                                       ▼
                             authorized read result
```

## Quy tắc không được phá

- JSONL là canonical append-only truth cho memory events; SQLite/FTS5 là derived và phải rebuild được.
- `observe` chỉ capture; tuyệt đối không đăng ký automatic injection.
- User message và assistant message phải có event type khác nhau.
- Capture thành công không được bị đổi thành thất bại chỉ vì projection lỗi.
- Một runtime chỉ sở hữu một topology: canonical stream, derived DB, projection watermark và read service phải cùng nguồn.
- Memory operations mặc định không gọi LLM.
- Authorization phải xảy ra trước retrieval/discovery.
- Không ghi raw secret; phải redact hoặc reject trước persistence.
- Hermes sở hữu SOUL, Crons và nội dung Skill; Zero-Mem chỉ quan sát lifecycle/provenance.
- Mọi sửa, supersede hoặc delete-request memory phải qua HITL; không silent overwrite và không xóa canonical trace.

## Luồng làm việc bắt buộc

```text
Chọn đúng V124 package
  → kiểm tra dependency
  → ghi baseline SHA + dirty paths
  → đọc authority + code map
  → viết/điều chỉnh acceptance test
  → sửa vertical slice nhỏ nhất
  → focused + negative + integration tests
  → ghi evidence
  → cập nhật trạng thái package
```

Chỉ một package được `IN_PROGRESS`. Không bắt đầu package sau nếu predecessor chưa `IMPLEMENTED_VERIFIED` hoặc chưa có maintainer waiver bằng văn bản.

## Điều kiện dừng

Dừng và báo `BLOCKED` khi:

- hành vi Hermes host thực tế không khớp contract fixture;
- cần sửa sâu Hermes core thay vì sidecar/plugin boundary;
- phải đổi schema/public semantics nhưng chưa có migration/version decision;
- canonical và derived path không thể chứng minh cùng topology;
- test cần bỏ qua security gate để pass;
- có dirty path không xác định hoặc cần rewrite lịch sử Git;
- không thể chạy gate bắt buộc trên một platform được tuyên bố hỗ trợ.

