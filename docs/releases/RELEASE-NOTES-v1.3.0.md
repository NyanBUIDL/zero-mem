# Zero-Mem v1.3.0 — Release Notes

**Date:** 2026-08-23 | **Branch:** `release/v1.3.0` | **Local release (no remote push)**

## Runtime requirement

- **SQLite ≥ 3.35** cho migration `down` của migrate_11 (`ALTER TABLE DROP COLUMN`).
  Migration `up` không có yêu cầu này — deploy trên SQLite cũ: up OK, down sẽ
  fail-closed với thông điệp rõ ràng. Đã kiểm tra môi trường phát triển:
  SQLite 3.53.1 (`.venv-v124`).

## Behavior changes (người dùng cần biết)

1. Multi-term FTS query giờ có OR-fallback khi AND rỗng → query từng trả 0 kết quả
   có thể trả hit; kết quả mang metadata `match_mode="or_fallback"`. Caller muốn
   probe zero-result dùng single nonce term.
2. Cursor fingerprint bao gồm `match_mode` + `knowledge_space_id` → cursor cũ từ
   phiên trước v1.3.0 bị từ chối (`cursor_query_mismatch`) là hành vi đúng
   (versioned cursor).
3. NULL `knowledge_space_id` = unscoped = visible theo global-default-read (D-03).
   KHÔNG siết deny-by-default.
4. State active trong PROJECT route được promote vào primary evidence (V130-03) —
   recall@k cho câu hỏi trạng thái dự kiến tăng; benchmark case B01/B06/B09 đo
   before/after.
5. EvidenceSet có field annotation `temporal` (as-of read M8.4) — annotation-only,
   không đổi selection/order/budget.

## Benchmark summary (trung thực về phạm vi)

- Synthetic N=5.000 seeded deterministic: OR-fallback recall ✓, precision guard ✓,
  ks leak=0 ✓, state promotion ✓ budget giữ nguyên, temporal as-of ✓.
- Real corpus token-savings: **83.53%** (42 vs 255 tokens naive) — sanity check trên
  n=25 events; con số đại diện cần corpus ≥500 events hoặc synthetic long-history
  scenario (open question cho v1.4).
- Final suite **3.424 passed / 0 failed** ≥ baseline 3.378.

## Tham chiếu

- Closure handoff: `docs/v1.3.0/CLOSURE.md`
- Decisions D-01..D-06: `docs/v1.3.0/plans/DECISIONS.md`
- Selection-shape registry: `docs/v1.3.0/selection-shape-registry.md`
- Evidence đầy đủ: `docs/v1.3.0/EVIDENCE.md`
