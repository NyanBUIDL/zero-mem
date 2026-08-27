# v1.6.0 Roadmap

## Mục tiêu

Đưa Multi-KS đi trọn đường từ capture đến canonical, derived storage,
authorization, retrieval và projection mà không rewrite lịch sử hoặc phá dữ
liệu singular cũ.

## Work packages

| WP | Kết quả | Trạng thái |
|---|---|---|
| C01 | Capture contract `knowledge_space_ids` | DONE |
| C02 | Migration v13 và junction `zm_event_spaces` | DONE |
| C03 | Rebuild junction từ canonical | DONE |
| C04 | Structured authorization qua junction | DONE |
| C05 | FTS authorization parity | DONE |
| C06 | Graph dùng PRIMARY-KS | DONE |
| C07 | `list_knowledge_space` đọc junction | DONE |
| C08 | Projection xuất `knowledge_spaces` | DONE |
| C09 | Corpus singular boundary được pin/document | DONE |
| C10 | Legacy/E2E/benchmark/version/qualification | DONE LOCALLY |
| DX01 | Guided wizard/onboarding và Hermes identity guidance | DONE LOCALLY |

Chi tiết và commit nằm trong [`work-packages/`](work-packages/) và
[`EVIDENCE.md`](EVIDENCE.md).

## Gate còn lại

1. Push exact branch SHA không force.
2. Workflow `.github/workflows/v1.6.0-qualification.yml` xanh trên 3 OS × 3 Python
   tại exact SHA chứa DX01.
3. Reconcile remote logs của DX01 vào evidence index.
4. Chỉ tạo tag/release khi maintainer phê duyệt riêng và release SHA invariant đúng.

## Ngoài phạm vi

- Public trace-union surface.
- Multi-KS cho một corpus unit.
- Rewrite canonical cũ hoặc di chuyển evidence đã nghiệm thu.
- Tự động suy luận project/profile/KS từ cwd, repo hoặc nội dung hội thoại.
