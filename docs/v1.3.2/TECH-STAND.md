# v1.3.2 — Tech-stack & vận hành (thiết kế sườn, ổn định trước khi triển khai)

## Nguyên tắc stack: KHÔNG thêm gì mới
v1.3.2 là remediation line. Stack giữ nguyên 100% so với v1.3.1:

| Lớp | Thành phần | Thay đổi v132 |
|---|---|---|
| Canonical | JSONL append-only | Không đổi |
| Derived | SQLite + FTS + zm_meta + zm_temporal_index | Không đổi (không migration) |
| Retrieval/eligibility | `src/integration/m7/eligibility.py` (pure, deterministic) | WP-1: 1 dòng logic |
| Security | Redaction gate (`benchmarks/v130_real_corpus_pipeline.py`) | WP-2: pattern chặt hơn |
| Governance state | project-state.yaml (+ implementation-plan.json vai trò record) | WP-5 |
| Tooling | scripts/*.py stdlib-only | +2 script nhỏ (WP-5 validator, WP-6 hash-check), không dependency |
| Test | pytest, .venv-v124 | WP-8: summary hook stdlib |

Kiểm chứng "nhẹ & mượt": mọi thay đổi src/ chỉ chạm **2 file**, cả hai đều pure/deterministic
→ không race, không halfway-write, không đụng canonical store.

## Chi phí dự kiến mỗi WP (token/storage/runtime)
- WP-1: +~15 LOC test, ±3 LOC code; runtime cost = 0 (cùng O(1) check).
- WP-2: +4 test case; gate chạy trong benchmark pipeline — chi phí như cũ.
- WP-5/6: +2 script stdlib (~50 LOC mỗi cái) + unit tests; chạy trong suite <0.5s.
- Storage tăng chỉ do docs/evidence — không có growth runtime nào mới.

## Rủi ro thiết kế sườn đã được Measurer (Pha A) kiểm tra lại trước khi implement
Mỗi WP phải có ≥2 rủi ro dự phán kèm test phát hiện — xem
`docs/v1.3.2/analysis/ARCH-MEASURE-PRE.md` sau Gate A0. Mẫu rủi ro cần soi:
1. WP-1: hành vi retrieval thay đổi số lượng event primary → có thể lệch benchmark
   v130 snapshot nếu benchmark phụ thuộc eligibility → Measurer phải xác nhận
   benchmark có gọi eligibility hay không TRƯỚC khi merge.
2. WP-2: pattern marker quá chặt làm pipeline real-corpus block nhiều hơn → đo
   trước/sau trên fixture nhỏ để định lượng, không chỉ pass/fail.
3. WP-6: hash-check fail-closed có thể phá CI nếu docx đổi line-ending khi copy →
   hash tính trên bytes, test với CRLF/LF cả hai.
