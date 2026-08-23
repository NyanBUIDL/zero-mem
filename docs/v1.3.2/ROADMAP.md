# v1.3.2 — Lộ trình (scaffold, CHƯA triển khai — chờ Gate A0 + điều kiện tiền đề)

## Mục tiêu version
Đóng toàn bộ P1–P3 từ audit 2026-08-23: fix bug `is_verified` thật sự (retrieval
correctness), harden redaction gate chống marker-abuse, publish v1.3.1 để đóng drift
remote, dọn workspace hygiene, hợp nhất machine state về một nguồn.

## Phạm vi
- **Trong phạm vi:** 9 WP V132-01..09 đúng bảng dưới; 4 quyết định D-01..D-04;
  thay đổi `src/` chỉ ở eligibility.py:178 và redaction-gate semantics (WP-2);
  còn lại là governance/docs/tooling.
- **Ngoài phạm vi:** canonical JSONL format; enum VerificationStatus; schema migration;
  bm25/retrieval nâng cấp; Obsidian projection; dependency runtime mới; release v1.3.2
  publication (chờ user duyệt riêng).

## Nguyên tắc / invariant không được phá
JSONL canonical append-only; SQLite/FTS derived rebuildable; zero-LLM memory ops;
authorization-first (M5); redact-before-persist với chiều fail-closed KHÔNG yếu đi;
Obsidian projection boundary; không tự nâng assistant_claim thành fact.

## Work-packages (dependency order)
| ID | WP | Depends on | Trạng thái | Gate |
|---|---|---|---|---|
| A0 | Measurer subagent: đo kiến trúc + dự phán lỗi sườn | B-preconditions | PLANNED | GATE-A0 |
| V132-01 | is_verified alignment (D-01) | A0 | PLANNED | G0→G2 |
| V132-02 | Redaction marker-abuse hardening | A0 | PLANNED | G0→G3 |
| V132-03 | Publish v1.3.1 (governance) | approval user | PLANNED | GATE-PUB |
| V132-04 | Workspace tmp cleanup + policy inventory | — | PLANNED | GATE-W4 |
| V132-05 | Machine state consolidation (D-02) | — | PLANNED | G0→G2 |
| V132-06 | Master spec freeze + hash check (D-03) | — | PLANNED | G0→G2 |
| V132-07 | Benchmarks inventory + legacy archive | — | PLANNED | G0→G2 |
| V132-08 | Skip-count transparency | — | PLANNED | G0→G1 |
| V132-09 | Venv strategy (D-04) | — | PLANNED | GATE-W9 |
| Z | Closure + EVIDENCE/CLOSURE + APPROVE template | tất cả | PLANNED | G6 |

Gate order có thể chạy song song các nhóm độc lập: {01}, {02}, {05..08}; {03} theo
approval; {04}/{09} theo gate policy-edit.

## Milestone / gate
G0 Contract → G1 Unit → G2 Integration → G3 Security/Failure → G4 Platform →
G6 Release (dừng trước tag/publish chờ user).

## Verifier-loop
Như v130/v131: Measurer trước → Reviewer sau mỗi diff → Verifier sau mỗi commit.
Verdict nguyên văn vào VERIFIER-LOG trong `docs/v1.3.2/EVIDENCE.md`.

## Open questions
- D-01..D-04 chờ Builder đề xuất + user duyệt tại gate tương ứng.
- Điều kiện bắt đầu: trạng thái release v1.3.1 phải rõ trước khi dựng nhánh.
