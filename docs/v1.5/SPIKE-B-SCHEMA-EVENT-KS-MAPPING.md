# V150-WP1 — SPIKE: B-schema (mapping event↔knowledge-space cấp row)

**Trạng thái:** Hoàn tất — đầu vào cho GATE-V150-2 · **Ngày:** 2026-08-25
**Phương pháp:** đo trên corpus quant_lab THẬT (read-only, 1.070 sources / 217.256 units, 1 KS) + phân tích schema migrate_10.

## Kết quả đo được

| Thao tác | Chi phí đo thực tế |
|---|---|
| Group units theo source_ref | 10,4 ms / 217k rows |
| Digest toàn bộ authorization-subset (units) | **469 ms** / 217k rows |
| Point-lookup theo `knowledge_space_id` ×1000 | 2,5 ms (~2,5 µs/lần, có index `idx_zm_corpus_units_scope`) |

## Nhận định kỹ thuật

1. **B-schema khả thi về hiệu năng.** Mapping row-level dùng bảng liên kết
   `zm_event_spaces(event_id, knowledge_space_id)` (canonical-side, đi qua ingest)
   hoặc cột trực tiếp — point-lookup có index chỉ ~µs; chi phí ghi tăng O(1)/event.
2. **Chi phí digest gate ở scale hiện tại:** 469 ms/full-corpus là quá đắt để chạy
   per-request. Option A đã giảm nhẹ rủi ro này vì gate chỉ armed khi cấu hình
   expectation; khuyến nghị cho enterprise: cache digest theo `(mtime, size)` của
   store file, invalidate khi thay đổi — không tính lại mỗi request.
3. **Schema:** `zm_corpus_units` đã có sẵn `knowledge_space_id` + index scope ⇒
   phần corpus của B-schema đã xong từ v1.4. Phần việc còn lại nằm ở **event store**
   (`zm_meta` chưa có cột ks — nguyên nhân gốc DEF-004 chọn Option B). Migration
   additive kiểu migrate_12 (`ALTER TABLE zm_meta ADD COLUMN knowledge_space_id` +
   backfill từ provenance) là đường ngắn nhất, đúng pattern migration v12 của DEF-007.
4. **Backfill:** events cũ không có ks → NULL = non-authorizing (fail-closed tự
   nhiên), không cần suy diễn.

## Ước lượng công sức Option B đầy đủ

- Migration v13 (zm_meta.ks + index): ~1 increment, rủi ro thấp (pattern có sẵn).
- Wire capture path ghi ks vào event envelope: 1–2 increment (chạm capture contract).
- AuthorizedRead predicate per-row theo ks + bỏ coarsening: 1 increment + acceptance.
- Admin CLI đa-agent (ADR-V141-01 Option B thật): 1–2 increment riêng.
- Tổng: ~4–6 increment, phù hợp một WP v1.5.x riêng, KHÔNG nhồi vào v1.5.0.

## Khuyến nghị GATE-V150-2

v1.5.0 giữ Option A (đã implement trong WP này). Lên kế hoạch **V150-WP2 = Option B
event-store mapping** làm WP tiếp theo khi bắt đầu tier enterprise; spike này chứng
minh không có blocker hiệu năng hay schema.
