# P1-01 — FTS-AND brittleness (OR-fallback / normalization)

**Status:** PENDING USER REVIEW (Gate A)
**Date:** 2026-08-22
**Scope:** V130-01. Không đụng vùng khác.

## 1. Hiện trạng code chính xác

- `src/retrieval/search.py:46-53` — `_normalize_fts_query()`: chỉ collapse whitespace + thay `-` bằng space. Không xử lý multi-term AND.
- `src/retrieval/search.py:144-150` — SQL: `WHERE zm_fts MATCH ?` với text chuẩn hóa truyền thẳng. FTS5 mặc định là **implicit AND**: query `"docker build step"` chỉ hit khi TẤT CẢ 3 token cùng xuất hiện → 1 từ hiếm thiếu = 0 kết quả (brittle).
- `src/retrieval/search.py:159-163` — lỗi FTS engine → `malformed_fts_expression`, không fallback.
- Cursor fingerprint (`search.py:126`, `cursor_mod.make_fingerprint(req, text=text)`) bind text ĐÃ normalize — mọi fallback phải xảy ra TRƯỚC fingerprint để cursor vẫn nhất quán.
- Index: `zm_fts` fts5 unicode61 (`src/storage/migrations/migrate_5.py:33`), tokenizer tách `-` thành token riêng — đã xử lý ở v1.2.4.
- Benchmark hiện tại: `benchmarks/run_memory_benchmark.py`, corpus nhỏ functional (P1 finding số 5 xử lý scale ở V130-05).

## 2. Root cause

FTS5 MATCH mặc định AND-ngầm mọi term. `search_text` không có chiến lược recall-fallback: multi-term query với 1 term hiếm/đánh máy sai trả về rỗng, và caller không phân biệt "0 hit thật" với "query quá chặt".

## 3. Phương án thiết kế

### Option A — OR-expansion + precision guard (khuyến nghị)
Chuẩn hóa text thành term list; chạy MATCH với implicit AND trước. Nếu 0 hit và query có ≥2 term: chạy lại với các term nối ` OR `, đánh dấu kết quả bằng metadata mới trên `SearchResult` (ví dụ `match_mode: "and" | "or_fallback"`). Guard precision: giữ AND-hit khi có; OR-fallback chỉ khi AND rỗng; giữ nguyên thứ tự deterministic `(created_at, event_id)`; giữ nguyên structured filters + deleted-exclusion + pagination (cursor fingerprint phải bao gồm cả match_mode để không trả cursor sai chế độ).

### Option B — Client-side term scoring (bm25 + rank)
Dùng `bm25()` FTS5, query OR toàn phần, rank lại, cắt theo limit.
- Ưu: recall cao nhất, relevance ordering.
- Nhược: phá hợp đồng deterministic ordering `(created_at, event_id)` đang được test chặt (M3.3); bm25 score phụ thuộc corpus → kết quả thay đổi khi ingest thêm dữ liệu (không reproducible cho benchmark); thay đổi lớn hơn contract.

| Tiêu chí | A (OR-fallback) | B (bm25 rank) |
|---|---|---|
| Storage | 0 | 0 |
| Token cost | 0 (metadata 1 field) | 0 |
| Runtime | +1 query chỉ khi AND=0 | OR query luôn + sort |
| Reversibility | cao (thuần tầng retrieval, không schema) | trung bình (đổi contract ordering) |
| Độ chính xác precision | giữ AND ưu tiên → cao | thấp hơn (noise OR) |
| Test impact | nhỏ, cộng thêm | lớn, phá test ordering hiện có |

## 4. Khuyến nghị

**Option A.** Lý do: smallest compliant change, giữ nguyên mọi invariant deterministic, không schema change, dễ rollback (xóa 1 hàm + 1 nhánh).

## 5. Schema / migration impact

Không. Thuần tầng `src/retrieval/search.py`. `SearchResult`/`SearchHit` thêm field optional `match_mode` (default `"and"`) — additive, không phá caller hiện có. Cần kiểm tra `src/retrieval/models.py` và mọi nơi construct `SearchResult` để thêm giá trị mặc định.

## 6. Rủi ro

- OR-fallback làm tăng hit noise → giảm precision đo lường. Giảm thiểu: chỉ fallback khi AND rỗng; ghi `match_mode` để benchmark đo riêng.
- Cursor: fingerprint cũ (trước fix) vẫn tồn tại trong client → validate_cursor_binding từ chối cursor cũ là hành vi đúng (versioned cursor).
- Không được để text do caller đưa vào SQL ngoài parameter `MATCH ?` — OR-expansion phải build từ token đã escape/quote an toàn (quote mỗi term bằng `"..."` FTS5 để không inject cú pháp).

## 7. Test plan dự thảo

1. Unit: multi-term query mà AND rỗng, OR có hit → trả hit + `match_mode="or_fallback"`.
2. Unit: AND có hit → không fallback, `match_mode="and"` (guard precision).
3. Unit: single term → không fallback.
4. Unit: term chứa ký tự FTS5 đặc biệt (`"`, `(`, `*`) trong fallback → không `malformed_fts_expression` ngoài ý muốn, không SQL injection.
5. Unit: cursor tạo ở chế độ AND không dùng được cho cùng text (fingerprint khác) và ngược lại.
6. Regression: toàn bộ test M3.3 hiện có phải pass không sửa assertion.

## 8. Gate criteria

- G0: contract `match_mode` chốt trong spec V130-01 trước khi code.
- G1: unit test mới xanh; C7 (regression fail khi revert fix) được chứng minh.
- G2: full suite ≥ baseline 3378 passed / 0 failed.
- Benchmark (V130-05): case nhắm OR-fallback cho precision/recall đo được before/after.

## 9. Rollback plan

Revert commit WP (thuần 1 file + test). Không data migration → rollback tức thời, an toàn tuyệt đối.

## 10. Migration plan

Không cần. Field `match_mode` optional với default — DB không đổi, JSONL canonical không đổi.
