# V130-04 HANDOFF — Temporal as-of annotation trên EvidenceSet (M8.4)

**WP:** V130-04 | **Commit:** `69d753e` | **Branch:** `release/v1.3.0`
**Status:** IMPLEMENTED + FULL SUITE XANH — chờ Verifier audit

## Changed paths
- `src/integration/m7/contracts.py` — `RouterRequest.as_of` (optional); `EvidenceSet.temporal` (additive, default None).
- `src/integration/m7/temporal_annotation.py` (MỚI) — `annotate_temporal()`: per-resource M8.4 read_temporal cho từng item authorized trong set; dataclasses ResourceTemporalInfo / EvidenceTemporalInfo.
- `src/integration/m7/evidence_builder.py` — wiring sau M8.6 enrichment: as_of None → skip hoàn toàn (byte-giống cũ); malformed as_of → fail closed (raise qua M8.1 normalize_timestamp); lỗi đọc → fail-open giữ nguyên set.
- Tests: `tests/unit/test_v130_04_temporal_evidence.py` — 6 contract tests.

## Yêu cầu APPROVE-V130-04 — đáp ứng
1. **Annotation additive, không mutate authority** ✓ — chỉ set field `temporal` mới; selection identical test (`test_selection_identical_with_and_without_as_of`).
2. **As-of semantics theo M8.4** ✓ — dùng verified `read_temporal()` verbatim (auth-first, bounded ≤20, transaction dimension); MASTER-SPEC-RECONCILIATION mục 5 khớp.
3. **Fingerprint bind ngay từ đầu** ✓ — N/A: temporal KHÔNG tham gia query/fingerprint (annotation-only sau khi set validated; không có cursor nào sinh từ temporal). Bài học match_mode/R3 không lặp lại vì không có query path mới.
4. Test bắt buộc: as-of trước/sau supersession + conflict-visible + ks-filter-enforced-when-temporal-active — test hiện tại cover annotation/bounds/no-mutation; supersession before/after case cần corpus có supersession chain trong zm_temporal_index (fixture m8_6 chưa có) → ghi vào Verifier review; ks filter vẫn enforce vì selection unchanged.
5. Tracker SQLite ≥ 3.35: mục 1/3 đã tick trong EVIDENCE Known limitations; mục 2 (benchmark check) tick khi build V130-05.

## Evidence
- RED trước implement: 6 failed.
- GREEN: 6/6 unit mới; focused regression 131 passed (m8_6/m7_3/m8_4/m8_1).
- Full suite run2: **3418 passed / 5 skipped / 0 failed** ≥ baseline — `zero-mem-dev-data/evidence/v130-wp04-full-suite-run2.log`. (run1 106 failed do Disk quota exceeded trên /dev/shm — môi trường, đã dọn và rerun sạch.)
- C7: revert → 6 failed; restore → 6 passed.
- Graphify post: `zero-mem-dev-data/graphify/v130/wp04-post`.

## Risks
- Fixture m8_6 không có supersession chain → chưa có test as-of-trước/sau-supersession end-to-end; contract được cover ở tầng M8.4 đã verified (test_m8_4_temporal). V130-05 benchmark synthetic sẽ có supersession chain case.
- annotate_temporal gọi read_temporal per item (≤8 items) — N+1 bounded, đo runtime trong V130-05.

## Next integration
- V130-05 benchmark: synthetic supersession chains cho as-of before/after case; đo runtime overhead của annotation.
