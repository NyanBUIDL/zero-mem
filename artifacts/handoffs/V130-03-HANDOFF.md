# V130-03 HANDOFF — State-as-primary promotion (PROJECT route)

**WP:** V130-03 | **Commits:** `20bbe3e` (fix m4/m8-6) + `ffaf7ba` (promotion) | **Branch:** `release/v1.3.0`
**Status:** IMPLEMENTED + FULL SUITE XANH — chờ Verifier audit

## Changed paths
Core promotion (`ffaf7ba`):
- `src/integration/m7/eligibility.py` — `is_eligible` thêm `promote_state_in_project: bool = False`; promotion block đặt SAU toàn bộ guard; chỉ nâng khi PROJECT + resource_type=state + lifecycle active.
- `src/integration/m7/evidence_builder.py` — build_evidence_set truyền `promote_state_in_project=(route is MemoryRoute.PROJECT)`.
- `src/m8/calibration.py` — D-06: `VERIFICATION_STATUS_STRENGTH` table (reuse giá trị đã duyệt) + fallback trong `derive_verification_strength`; CalibrationCandidate thêm observation field `verification_status`.
- `src/m8/retrieval_metadata.py` — build_candidate điền verification_status observation.
- Tests: `tests/unit/test_v130_03_state_primary.py` (12), `tests/unit/test_m8_5_calibration.py` (+2, sửa 1 theo D-06).

Latent-bug fix (`20bbe3e`, tách riêng theo yêu cầu user):
- `src/project_memory/reader.py` — D-05: ProjectArtifactView.lifecycle_status = "active" tường minh.
- `tests/unit/test_m8_6_integration.py` — authority well-formedness đổi sang closed VERIFICATION_STATUS_ENUM + snapshot-diff mutation-check (theo user chỉ định); KHÔNG nới assertion vô tội.

## Invariants 1–6 (APPROVE-V130-03) — đáp ứng
1. Promotion sau mọi guard ✓ (block cuối hàm, chỉ False→True).
2. assistant_claim không bao giờ primary ✓ (`test_assistant_claim_never_promoted_in_project`; non-promotable check đứng trước).
3. Non-PROJECT byte-for-byte ✓ (param default False; route≠PROJECT không vào nhánh; test parametrize).
4. Budget 5/3/8 giữ nguyên ✓ (`test_budget_bounds_preserved_with_promotion`).
5. Optional param default ✓.
6. C7 ngược: stash eligibility/builder/reader → 10 failed; stash calibration → 1 failed; restore xanh ✓.

## Lần gãy thứ ba cùng gốc — quét sạch hard-code memory_type/verification (theo yêu cầu user)
Bảng/liệt kê hard-code đã audit:
- `src/m8/calibration.py`: SCOPE_PRIORITY_VALUES, VERIFICATION_STRENGTH_VALUES (đã xử lý bằng fallback D-06), PROVENANCE_COMPLETENESS_VALUES, TEMPORAL_VALIDITY_VALUES, RELATION_RELEVANCE_VALUES (keyed theo class/scope/temporal — không phải memory-type), `_reason_codes` memory_type=="assistant_claim" (guard đúng hướng, giữ).
- `src/integration/m7/eligibility.py`: promotable-set `(decision, verified_state, tool_observation)` và `_NON_PROMOTABLE_TYPE` — đây là CHÍNH sách role, promotion rule của WP này chủ động đặt state vào primary qua đường riêng; các set khác không cần 'state'.
- `src/integration/m7/budget.py`: state_rank check `resource_type == "state"` — đã là đường cho state.
- `src/m8/graph_access.py`: resource_type routing per-read (không phải scoring table).
- Kết luận: sau D-05/D-06 không còn con đường nào để một item hợp lệ rơi ra ngoài metadata/authority vì thiếu row trong bảng hard-code. Types còn thiếu row strength (artifact, charter, event, relation, trace, corpus_*) đều được cover bởi fallback D-06.

## Evidence
- RED trước implement: 10 failed (TypeError promote_state_in_project).
- GREEN focused: 122 passed (v130_03 + m8_5 + m8_6).
- Full suite run2: **3410 passed / 5 skipped / 0 failed** ≥ baseline — `zero-mem-dev-data/evidence/v130-wp03-full-suite-run2.log`.
- C7: 2 hướng revert đều fail; restore xanh.
- Graphify post: sẽ chạy lại nếu Verifier yêu cầu (diff nhỏ, 2 vùng đã có graphify wp02-post làm base).

## Risks
- D-06 thay đổi score cho các type chưa từng được score (state, artifact…) — deterministic, tái lập được; benchmark V130-05 đo before/after.
- m8_6 test refactor: snapshot-diff mạnh hơn list hard-code, nhưng cần Verifier xác nhận không weaken ý đồ chống mutation.

## Next integration
- V130-04 (temporal→EvidenceSet): EvidenceSet giờ chứa promoted states với lifecycle='active' đầy đủ.
- V130-05: benchmark case PROJECT-route hit-rate B01/B06/B09.
