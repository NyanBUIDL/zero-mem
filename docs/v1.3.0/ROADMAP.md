# v1.3.0 — Lộ trình

> Tạo từ `docs/VERSION-TEMPLATE.md` (mục ROADMAP). Điền trước khi code.

## Mục tiêu version
- <mục tiêu chính, ví dụ: chứng minh retrieval quality + token-savings trên corpus production>

## Phạm vi
- Trong phạm vi: ...
- Ngoài phạm vi: ... (ghi rõ, kể cả thứ đã đề xuất nhưng bị hoãn)

## Nguyên tắc / invariant không được phá
- Dẫn `AGENTS.md` + ADR-009 + `docs/v1.2.0/SPEC-AMENDMENT-001`.
- JSONL canonical append-only; SQLite/FTS derived rebuildable; Obsidian projection.
- Zero LLM cho memory operations; authorization-before-discovery; redact trước persist.
- Không tự nâng assistant_claim thành fact; stale/conflict không bị che.

## Work-packages (dependency order)
| ID | Tên | Depends on | Trạng thái | Gate |
|---|---|---|---|---|
| V130-01 | ... | — | PLANNED | G0/G1 |

## Milestone / gate
- G0 Contract → G1 Unit → G2 Integration → G3 Security/Failure → G4 Platform → G5 Packaging → G6 Release

## Open questions
- <câu hỏi cần quyết định; mỗi câu có owner + deadline>
- Kế thừa từ P1: state-as-primary (đã chọn Option B; cần triển khai primary promotion), knowledge-space filter, FTS-AND fallback, scale N=5.000, temporal read integration.
