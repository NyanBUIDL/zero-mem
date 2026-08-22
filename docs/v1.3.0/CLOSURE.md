# Zero-Mem v1.3.0 — Closure Handoff

**Status:** `IMPLEMENTATION_COMPLETE` — chờ Gate D verdict + user phê duyệt release
**Branch:** `release/v1.3.0` | **Baseline SHA:** `e2c0d7ac` | **Date:** 2026-08-23
**Scope:** Đóng 5 P1 findings kế thừa v1.2.4 + benchmark production-grade.

## Kiến trúc & data flow cuối cùng

JSONL canonical (append-only, KHÔNG đổi format) → ingest (zm_meta +23 cột cũ
+`knowledge_space_id` mới) → derived SQLite (zm_fts / zm_scopes / zm_temporal_index
/ zm_project_*) → retrieval (FTS OR-fallback + ks exact-filter) → M7 eligibility
(route-conditioned state promotion) → EvidenceSet (+ field annotation `temporal`)
→ Hermes.

Không thay đổi: canonical JSONL schema, zero-LLM memory ops, authorization-first
(M5), redact-before-persist, Obsidian projection boundary. Toàn bộ derived state
rebuildable từ JSONL (đã test cho cột ks mới).

## Changed paths theo WP

| WP | Commit(s) | Nội dung |
|---|---|---|
| V130-01 | `620e76b` | FTS OR-fallback precision-guarded; `SearchResult.match_mode`; cursor fingerprint bind match_mode; probe contract (single nonce) |
| V130-02 | `cdada94` | migrate_11 zm_meta.knowledge_space_id + idx; enforce qua _EQUAL_FILTERS/_build_where; NULL=unscoped visible (D-03) |
| V130-03 | `20bbe3e`, `ffaf7ba`, `e656ecf` | Route-conditioned active-state promotion (PROJECT); D-05 artifact lifecycle='active'; D-06 verification-strength fallback; m8_6 snapshot-diff authority check; mutation-injection test |
| V130-04 | `69d753e`, `c179f79` | EvidenceSet.temporal annotation qua M8.4 read_temporal verbatim; fail-open/fail-closed matrix đúng spec |
| V130-05 | `26651fc`, `0ded61b` | Synthetic generator N=5000 seeded deterministic; benchmark runner per-fix case sets; real-corpus pipeline redaction gate fail-closed |

Docs/decisions: D-01..D-06 (`plans/DECISIONS.md`), MASTER-SPEC-RECONCILIATION.md,
selection-shape-registry.md (16 hard-code sites), 5 WP specs, handoffs
`artifacts/handoffs/V130-0{1..4}-HANDOFF.md`.

## Evidence per WP (đầy đủ trong EVIDENCE.md)

| WP | Verdict | Full suite | Ghi chú |
|---|---|---|---|
| Baseline | — | 3378 passed / 0 failed | v124-post-release-closure HEAD |
| V130-01 | PASS-WITH-NOTES (re-audit) | 3388 / 0 | C7 2 hướng; RED→GREEN log đủ |
| V130-02 | PASS-WITH-NOTES | 3396 / 0 | R1 rebuild ✓, R2 NULL policy ✓, R3 fingerprint từ đầu ✓ |
| V130-03 | PASS-WITH-NOTES | 3412 / 0 | F1/F2/F4 remediated; registry 16 sites |
| V130-04 | PASS-WITH-NOTES | 3418 / 0 | Annotation-only; auth-first; F1→V130-05 done |
| V130-05 | (này) | — | Xem benchmark results bên dưới |

## Benchmark results (raw, không tô hồng)

Synthetic N=5,000 (`v130-wp05-synthetic-results.json`):
- OR-fallback recall: mode=or_fallback, 50 hits ✓; precision guard: AND giữ nguyên khi có hit ✓
- ks filter leak = 0 (ks-0: 50 hits, ks-1: 50 hits, giao = 0) ✓
- State promotion: 5 active states vào primary, budget ≤5/3/8 ✓, t_build 24.6ms
- Temporal as-of trước supersession: valid=true; sau: facts=1 ✓ (F1 của V130-04 đã đóng)
- temporal_index_rows 4,866; m4_projected 832; t_ingest ≈4.2s

Real corpus (25 events export từ `_archive/` wp33):
- Redaction gate fail-closed (5 gate tests xanh; known-secret blocked)
- Token-savings: naive full-context 255 tokens vs EvidenceSet 42 tokens = **83.53% savings**

## Risks còn mở

1. **Registry hàng #5 (OPEN):** eligibility `is_verified` check `"verified"/"confirmed"`
   không khớp M1 VerificationStatus enum → is_verified luôn False cho memory events.
   Behavior baseline đã duyệt; sửa sẽ đổi role classification toàn cục — NEEDS DECISION.
2. **SQLite ≥ 3.35:** migration down yêu cầu DROP COLUMN. Tracker: EVIDENCE Known
   limitations ✓; benchmark chạy cùng môi trường dev-data ✓; release notes phải ghi
   rõ khi đóng version (chờ phê duyệt release).
3. Real corpus nhỏ (25 events, synthetic-labeled wp33 data). Token-savings là chỉ số
   cấu trúc; corpus production thật lớn hơn sẽ cho ratio thực hơn.
4. Graphify post-WP: wp01–wp04 có extract; wp05 không rerun (chỉ thêm benchmarks/,
   không đổi src runtime).

## Hướng tích hợp tiếp

1. User review Gate D verdict + closure → quyết định release.
2. Release theo GITHUB-POLICY (invariant SHAs) — CHỈ sau phê duyệt riêng.
3. v1.4 candidates: registry hàng #5 (role classification), multi-value ks
   (master spec L148), real production corpus benchmark.
