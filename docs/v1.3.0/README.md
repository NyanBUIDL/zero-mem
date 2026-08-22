# Zero-Mem v1.3.0 — <tên ngắn>

**Status:** `PLANNING`
**Branch:** `release/v1.3.0` (chưa tạo; tạo khi bắt đầu)
**Purpose:** <1-2 câu: v1.3 giải quyết gì — ví dụ: nâng retrieval quality, đóng các P1 findings (FTS-AND brittleness, state-as-primary, knowledge-space filter), scale benchmark lên production>

> Khung này được tạo từ `docs/VERSION-TEMPLATE.md`. Điền đầy đủ **trước khi code**.
> Xoá các dòng `<...>` và ghi chú.

## Đọc theo thứ tự
1. [`ROADMAP.md`](ROADMAP.md) — lộ trình
2. [`ARCHITECTURE.md`](ARCHITECTURE.md) — kiến trúc
3. [`TECH_STACK.md`](TECH_STACK.md) — công nghệ
4. [`DEVELOPMENT.md`](DEVELOPMENT.md) — cách phát triển
5. [`EVIDENCE.md`](EVIDENCE.md) — bằng chứng

## Work packages
| ID | Nội dung | Status |
|---|---|---|
| V130-01 | ... | PLANNED |

## Kế thừa từ v1.2.4 (P1 findings chưa đóng)
- FTS-AND brittleness (query nhiều từ, 1 từ không có → 0 kết quả) — cần OR/fallback/normalization mở rộng.
- State-as-primary: quyết định nâng state active lên primary trong PROJECT route (đang chờ triển khai).
- Knowledge-space filter chưa enforced trên memory events (`search_text` không truyền ks; zm_meta không có cột ks) — cần quyết định schema/design.
- Benchmark hiện là functional baseline trên corpus tổng hợp nhỏ; cần scale lên corpus lớn hơn (N=5.000+) để có token-savings production.
- History/as-of read (B29) chưa wired vào EvidenceSet (cần M8.4 temporal_read integration).
