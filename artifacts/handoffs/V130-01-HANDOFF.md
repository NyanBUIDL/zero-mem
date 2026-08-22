# V130-01 HANDOFF — FTS OR-fallback + precision guard

**WP:** V130-01 | **Commit:** `620e76b` | **Branch:** `release/v1.3.0` | **Date:** 2026-08-22
**Status:** IMPLEMENTED + FULL SUITE XANH — chờ Verifier re-audit (verdict trước đó DEVIATED, đã remediate)

## Changed paths
- `src/retrieval/search.py` — OR-fallback logic + `_run_match` refactor + mode-aware cursor binding.
- `src/retrieval/cursor.py` — `make_fingerprint(..., match_mode=)`.
- `src/retrieval/models.py` — `SearchResult.match_mode` field (additive, default `"and"`).
- `tests/unit/test_v130_01_fts_or_fallback.py` — 10 contract tests (mới).
- `tests/integration/test_v123_sidecar_composition.py` — probe zero-result đổi sang single nonce (theo GATE-A-REPLY-V130-01.md).
- `docs/v1.3.0/plans/V130-01-SPEC.md` — probe contract ghi vào Invariants.

## Data flow
`search_text(text)` → normalize → AND MATCH (parameterized) → nếu 0 hàng và ≥2 term → OR MATCH với từng term FTS5-quoted → `match_mode="or_fallback"`. Ordering `(created_at ASC, event_id ASC)`, structured filters, deleted-exclusion, pagination giống hệt cả hai chế độ. Cursor fingerprint bao gồm match_mode: cursor AND không dùng được ở OR-fallback và ngược lại; limit/structural errors surface nguyên bản (chỉ `cursor_query_mismatch` mới fallthrough sang qf_or).

## Evidence
- RED trước implement: 5 failed (AttributeError match_mode).
- GREEN focused: 49 passed (unit mới + M3 FTS + sidecar integration).
- Full suite run3: **3388 passed / 5 skipped / 0 failed** ≥ baseline 3378 (`zero-mem-dev-data/evidence/v130-wp01-full-suite-run3.log`).
- C7 regression: revert fix → 8 failed; restore → xanh (cả 3 log trong evidence dir).
- Graphify pre/post: `zero-mem-dev-data/graphify/v130/phase-a-baseline` / `wp01-post`.
- Verifier audit #1: DEVIATED (fingerprint chưa bind mode; test cross-mode yếu) → remediated trong commit; re-audit đang chạy.

## Risks
- OR-fallback làm tăng hit trên multi-term query có term phổ biến — đây là behavior có chủ đích (Gate A duyệt). Caller muốn zero-result probe phải dùng single nonce term (contract đã ghi).
- Integration test `test_sidecar_advertises_and_dispatches_the_same_public_reads` đổi probe — ý đồ test cũ bảo toàn (EMPTY status cho zero-result vẫn được assert với probe mới).

## Next integration
- V130-02 (ks filter) thêm cột vào `ZM_META_COLUMNS` — `_run_match` build SELECT từ list nên tự thấy; cursor fingerprint đã bao gồm structured filters qua req.
- V130-05 benchmark đo precision/recall riêng cho case AND-hit (không fallback) và OR-fallback.
