# v1.3.0 — Lộ trình

## Mục tiêu version
Retrieval quality & temporal correctness trên quy mô thực: đóng 5 P1 findings (FTS-AND brittleness, ks filter enforcement, state-as-primary promotion, temporal→EvidenceSet) và chứng minh bằng benchmark hybrid N=5.000+ với số liệu precision/recall + token-savings không tô hồng.

## Phạm vi
- **Trong phạm vi:** 5 WP V130-01..05 đúng bảng dưới; migration schema duy nhất là zm_meta.knowledge_space_id; annotation temporal trên EvidenceSet.
- **Ngoài phạm vi:** deny-by-default cho NULL ks (NEEDS DECISION riêng — D-03); multi-value ks trên zm_meta (spec note, NEEDS DECISION nếu cần thật); Obsidian corpus projection (deferred từ M10); bm25 relevance ordering; mọi thay đổi JSONL canonical format; release publication (chờ user phê duyệt riêng).

## Nguyên tắc / invariant không được phá
- Dẫn `AGENTS.md` + ADR-009 + `docs/v1.2.0/SPEC-AMENDMENT-001`; đối chiếu master spec: `MASTER-SPEC-RECONCILIATION.md`.
- JSONL canonical append-only; SQLite/FTS derived rebuildable; Obsidian projection.
- Zero LLM cho memory operations; authorization-before-discovery; redact trước persist.
- Không tự nâng assistant_claim thành fact; stale/conflict không bị che.

## Work-packages (dependency order)
| ID | Tên | Depends on | Trạng thái | Gate |
|---|---|---|---|---|
| V130-01 | FTS OR-fallback + normalization (precision guard) | — | PLANNED | G0→G2 |
| V130-02 | Knowledge-space filter: zm_meta cột đơn + enforce search_text/query | — | PLANNED | G0→G2 |
| V130-03 | State-as-primary promotion (PROJECT route, Option B nửa sau) | — | PLANNED | G0→G2 |
| V130-04 | Temporal read integration: M8.4 → EvidenceSet (annotation) | V130-02 | PLANNED | G0→G3 |
| V130-05 | Hybrid corpus benchmark N=5.000+ (synthetic seeded + real redacted) | V130-01..04 | PLANNED | G0→G5 |

## Milestone / gate
- G0 Contract → G1 Unit → G2 Integration → G3 Security/Failure → G4 Platform → G5 Benchmark/Packaging → G6 Release (dừng trước tag/publish chờ user).

## Verifier-loop
WP N commit xong → Verifier audit (verdict vào EVIDENCE.md VERIFIER-LOG) trong khi Builder chuẩn bị WP N+1 (test khung contract-first, Graphify impact-set). WP N+1 không bắt đầu khi WP N đang DEVIATED/BLOCKED.

## Open questions
- Đã quyết hết (DECISIONS.md D-01..03). Mới phát sinh sẽ ghi tại đây kèm owner + deadline.
