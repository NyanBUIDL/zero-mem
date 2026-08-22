# P1-04 — Temporal/as-of read (B29) chưa wired vào EvidenceSet (M8.4)

**Status:** PENDING USER REVIEW (Gate A)
**Date:** 2026-08-22
**Scope:** V130-04. Depends on V130-02 (ks filter schema) vì EvidenceItem cần mang ks đúng trục scope.

## 1. Hiện trạng code chính xác

- `src/m8/temporal_read.py:1-70` — M8.4 as-of/history read ĐÃ verified: authorization-first (M5 `AuthorizedReadService`), bounded `MAX_HISTORY_VERSIONS=20` (L67), as-of predicate `as_of_match()` (L224), `read_temporal()` (L405), đọc từ derived `zm_temporal_index` (migrate_9:151).
- `src/m8/__init__.py:6` — ghi rõ M8.4 temporal **chưa** tích hợp EvidenceSet: "(temporal), M8.5 (calibration), and M8.6 (EvidenceSet integration) are NOT …".
- `src/m8/retrieval_metadata.py:68,131-151,305-321` — có sẵn `as_of` trên request metadata + `classify_temporal_validity` dùng `as_of_match` — nhưng đây là tầng metadata, KHÔNG phải EvidenceSet.
- `src/integration/m7/evidence_builder.py:356-375` — M8.6 integration hiện chỉ gọi `enrich_evidence_set` (M8.3 graph, chỉ khi có seed; temporal/calibration KHÔNG chạy). `EvidenceSet` (`src/integration/m7/contracts.py`) không có field temporal.
- Kết luận: primitive B29 tồn tại, verified, nhưng không consumer nào ở tầng EvidenceSet → agent nhận evidence mà không thấy stale/superseded theo thời gian.

## 2. Root cause

M8.6 dừng ở graph enrichment; temporal read không được nối vào `build_evidence_set` vì thiếu quyết định contract: as-of đặt ở đâu (request? EvidenceSet field?), kết quả as-of biểu diễn thế nào mà không tự nâng claim và không phá bounded budget.

## 3. Phương án thiết kế

### Option A — Temporal annotation trên EvidenceSet (khuyến nghị)
Mở rộng `RouterRequest`/`build_evidence_set` nhận `as_of: Optional[str]` (chuẩn hóa qua M8.1 `normalize_timestamp`, fail closed khi malformed). Khi có `as_of`:
1. Sau khi EvidenceSet dựng xong (đã authorization-first), chạy `read_temporal()` cho TỪNG resource đã có trong set (chỉ authorized — tái dùng đúng descriptor M8.4).
2. Gắn kết quả vào field MỚI additive trên `EvidenceSet`: `temporal: Optional[EvidenceTemporalInfo]` — chứa per-resource `{resource_id, valid_at_as_of, history_count(bounded ≤20), superseded_by(provenance verbatim)}`.
3. KHÔNG loại item, KHÔNG đổi selection/order — chỉ annotation hiển thị stale/superseded (invariant "stale/conflict phải nhìn thấy được").
- Ưu: không đụng budget/eligibility; fail-open an toàn (lỗi temporal → set giữ nguyên, giống pattern M8.3 enrichment `evidence_builder.py:366-374`).
- Nhược: EvidenceSet dataclass đổi (additive field + default None — backward compatible).

### Option B — As-of filtering trong selection
Lọc bỏ item không hợp lệ tại as_of ngay trong eligibility.
- Nhược: thay đổi behavior selection (ít item hơn), đụng budget/omitted_count, rủi ro che mất thông tin thay vì hiển thị; lệch nguyên tắc "không chọn truth by recency" của M8.4.

| Tiêu chí | A (annotation) | B (filter) |
|---|---|---|
| Token cost | + annotation nhỏ, bounded | ít hơn chút (bớt item) |
| Behavior risk | thấp (không đổi selection) | cao (đổi selection) |
| Reversibility | cao | thấp |
| Khớp invariant stale-visible | đúng | sai hướng |

## 4. Khuyến nghị

**Option A.** Temporal info là annotation bounded, không phải bộ lọc; giữ nguyên mọi invariant M4/M8.4 (không tự nâng, không chọn theo recency).

## 5. Schema / migration impact

Không DB schema (zm_temporal_index đã có từ migrate_9). Dataclass `EvidenceSet` + `to_dict/from_dict` mở rộng additive (kiểm tra serialization tests hiện có).

## 6. Rủi ro

- Gọi read_temporal cho từng item có thể N+1 → bound: chỉ annotate resource có temporal row; giới hạn bằng MAX_HISTORY_VERSIONS sẵn có; đo trong benchmark.
- as_of malformed phải fail closed ở tầng request (normalize_timestamp), không nuốt vào except-generic.
- Phụ thuộc V130-02: EvidenceTemporalInfo cần ks để authorization seed đúng — làm sau khi schema ks chốt.

## 7. Test plan dự thảo

1. Unit: build_evidence_set với as_of hợp lệ → field temporal có, per-resource đúng valid_at_as_of từ fixture zm_temporal_index.
2. Unit: as_of malformed → QueryError/TemporalError fail closed (không trả set).
3. Unit: không as_of → EvidenceSet byte-giống hiện tại (regression).
4. Unit: resource không authorized → không xuất hiện trong temporal info (authorization-first).
5. Unit: lỗi temporal engine → set giữ nguyên (fail-open đúng pattern).
6. Unit: history_count ≤ 20; superseded_by chỉ là provenance, không thay đổi selection.
7. Full suite ≥ baseline.

## 8. Gate criteria

G0 contract field + fail-open/closed matrix → G1 → G2 → **G3** (security/failure: authorization leak test bắt buộc theo prompt GATE G0→G3).

## 9. Rollback plan

Revert WP; field additive nên rollback không phá serialization cũ.

## 10. Migration plan

Không cần DB migration; chỉ dataclass evolution có test roundtrip cũ/mới.
