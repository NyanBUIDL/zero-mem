# ADR-V160-01 — Multi-Knowledge-Space per event

**Trạng thái:** ACCEPTED / IMPLEMENTED (C1–C10)

## Quyết định

Canonical event mới dùng optional `knowledge_space_ids: list[str]`. Derived
SQLite dùng junction `zm_event_spaces`; singular `zm_meta.knowledge_space_id`
giữ PRIMARY-KS để tương thích. Structured và FTS authorization dùng junction
với UNION request semantics và fail-closed khi membership thiếu. Graph/temporal
dùng PRIMARY-KS; corpus unit giữ singular trong v1.6.0.

## Lý do

Junction cho phép index, rebuild và kiểm tra authorization theo row mà không
nhân bản event. Giữ singular PRIMARY-KS tránh phá consumer cũ. Canonical list
vẫn là authority nên derived state có thể tái dựng.

## Hệ quả

- Thêm migration derived v13 và một bảng junction.
- Cursor phải bind tập KS đã canonicalize.
- Consumer singular phải ghi rõ chỉ nhìn PRIMARY-KS.
- Multi-KS corpus unit và public trace-union được hoãn sang increment khác.

Bản proposal/decision đầy đủ và lịch sử review được giữ tại
[`../../v1.6/ADR-V160-01-MULTI-KS-PROPOSAL.md`](../../v1.6/ADR-V160-01-MULTI-KS-PROPOSAL.md).
