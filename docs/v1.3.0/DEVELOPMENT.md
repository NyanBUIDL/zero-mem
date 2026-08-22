# v1.3.0 — Cách phát triển

> Tạo từ `docs/VERSION-TEMPLATE.md` (mục DEVELOPMENT). Giữ nguyên quy trình/gate chuẩn.

## Quy trình (bắt buộc)
1. Chọn đúng work-package; kiểm tra dependency.
2. Ghi baseline SHA + dirty paths.
3. Đọc authority (`AGENTS.md`, master spec, ADR) + code map.
4. Viết/điều chỉnh acceptance test trước (RED).
5. Sửa vertical slice nhỏ nhất (GREEN).
6. Focused + negative + integration tests; security gate nếu xử lý content.
7. Ghi evidence (log/hash/verdict) vào `evidence/`.
8. Cập nhật trạng thái package; không bắt đầu package sau khi predecessor chưa xong.

## Gate bắt buộc
- G0..G6 (xem ROADMAP); mỗi gate có lệnh chạy thật + log + checksum.

## Điều kiện dừng (BLOCKED)
- Hành vi host không khớp contract fixture.
- Cần sửa sâu Hermes core thay vì sidecar/plugin boundary.
- Phải đổi schema/public semantics mà chưa có migration/version decision.
- Canonical và derived không chứng minh cùng topology.
- Test cần bỏ qua security gate để pass.
- Dirty path không xác định hoặc cần rewrite lịch sử Git.
- Không chạy được gate bắt buộc trên platform được tuyên bố hỗ trợ.

## Template work-package
- Tham chiếu `docs/v1.2.4/WORK_PACKAGE_TEMPLATE.md` (giữ nguyên hoặc copy sang v1.3).
