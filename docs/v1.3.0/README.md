# Zero-Mem v1.3.0 — Retrieval Quality & Temporal Correctness

**Status:** `IN_PROGRESS` (Pha B)
**Branch:** `release/v1.3.0` (tạo tại Gate B)
**Purpose:** Đóng 5 P1 findings kế thừa từ v1.2.4 — nâng chất lượng retrieval (FTS OR-fallback, knowledge-space filter, state-as-primary promotion), tích hợp temporal read vào EvidenceSet, và chứng minh trên benchmark quy mô thực (N=5.000+ synthetic + real corpus đã redact).

## Đọc theo thứ tự
1. [`ROADMAP.md`](ROADMAP.md) — lộ trình
2. [`ARCHITECTURE.md`](ARCHITECTURE.md) — kiến trúc
3. [`TECH_STACK.md`](TECH_STACK.md) — công nghệ
4. [`DEVELOPMENT.md`](DEVELOPMENT.md) — cách phát triển
5. [`EVIDENCE.md`](EVIDENCE.md) — bằng chứng
6. [`MASTER-SPEC-RECONCILIATION.md`](MASTER-SPEC-RECONCILIATION.md) — đối chiếu master spec .docx

## Work packages
| ID | Nội dung | Status |
|---|---|---|
| V130-01 | FTS OR-fallback + normalization, giữ precision guard | PLANNED |
| V130-02 | Knowledge-space filter: schema zm_meta + enforce search_text | PLANNED |
| V130-03 | State-as-primary promotion (PROJECT route) | PLANNED |
| V130-04 | Temporal read integration: B29 → EvidenceSet | PLANNED |
| V130-05 | Hybrid corpus benchmark N=5.000+ | PLANNED |

## Kế thừa từ v1.2.4 (P1 findings chưa đóng)
- FTS-AND brittleness → V130-01.
- State-as-primary promotion → V130-03.
- Knowledge-space filter chưa enforced → V130-02.
- Benchmark functional nhỏ → V130-05.
- Temporal/as-of read (B29) chưa wired vào EvidenceSet → V130-04.

## Quyết định thiết kế
Xem `plans/DECISIONS.md`: D-01 ks cột đơn; D-02 tách V130-01/02; D-03 NULL-ks = unscoped visible (user-approved Gate A).
