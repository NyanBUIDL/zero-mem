# P1-03 — State-as-primary promotion trong PROJECT route (Option B đã chọn)

**Status:** PENDING USER REVIEW (Gate A)
**Date:** 2026-08-22
**Scope:** V130-03.

## 1. Hiện trạng code chính xác

Finding này cần làm rõ vì v1.2.4 ĐÃ đóng một phần (P1-ORDERING, Option B, đã ship):

- `src/integration/m7/budget.py:39-60` — `_order_key()` đã có `state_rank`: trong route PROJECT, `resource_type == "state"` + lifecycle `active` được ưu tiên **trong role pool** (sau role split, trước verified/lifecycle/tie-break). Tests: `tests/unit/test_m7_3_evidence_builder.py:510-560` (`test_active_state_prioritized_in_project_route`, `test_budget_5_3_8_preserved_with_state_priority`, `test_non_project_routes_unchanged`).
- Nhưng `src/integration/m7/eligibility.py:170-191` — role classification: state records có `verification_status="none"` và `memory_type="state"` không thuộc promotable set `(decision, verified_state, tool_observation)` → `as_primary=False`. State chỉ bao giờ nằm supporting pool; với budget 5/3, nếu supporting pool đầy charter/requirement thì state vẫn bị cắt dù state_rank ưu tiên (rank chỉ áp dụng TRONG pool).
- `artifacts/handoffs/P1-ORDERING-HANDOFF.md` — xác nhận cơ chế cũ và phạm vi fix đã làm: "state-priority rank sits AFTER the primary/supporting role split … applies within each role pool".

## 2. Root cause

Option B đã chọn ở P1-ORDERING là *route-conditioned active-state priority* — giải quyết starvation do tie-break. Phần CHƯA có: **promotion tường minh của active state lên primary khi route = PROJECT**, tức state vẫn thua cuộc ở tầng role-split trước cả khi vào ordering. Finding v1.3.0 = hoàn tất nốt nửa sau: promotion có điều kiện, deterministic, không phá guard chống tự nâng assistant_claim.

## 3. Phương án thiết kế

### Option A — Route-conditioned as_primary promotion (khuyến nghị)
Trong `eligibility.py`, thêm tham số `route: Optional[MemoryRoute]` vào hàm classify; rule mới:
```
primary |= (route is MemoryRoute.PROJECT and resource_type == "state"
            and lifecycle == "active")
```
Đặt SAU toàn bộ guard hiện có (non-current lifecycle, subordinate, non-promotable) để không override bất kỳ exclusion nào — chỉ nâng từ False→True cho state đang eligible, active, PROJECT. Guard `PromotionBlockedError` (assistant_claim, `contracts.py:139-142,305-308`) KHÔNG bị đụng tới vì nó chặn lifecycle_status="active" trên M4 op, khác tầng này.
- Ưu: smallest change; tái sử dụng mọi test guard hiện có; budget 5/3 giữ nguyên.
- Nhược: eligibility giờ phụ thuộc route → chữ ký hàm đổi (cần default None để backward-compat).

### Option B — Secondary primary slot cho state
Giữ 5 primary như cũ nhưng thêm slot "state anchor" riêng (6 items khi có active state).
- Nhược: phá contract budget 5/3/8 đang được test chặt (`test_budget_5_3_8_preserved_with_state_priority`); thay đổi envelope/token budget → lan rộng sang context/envelope layer.

| Tiêu chí | A | B |
|---|---|---|
| Token cost | 0 (đổi vai trò trong budget sẵn có) | tăng khi có state |
| Contract impact | chữ ký hàm mở rộng optional | phá budget contract |
| Test impact | cộng thêm, không sửa assertion cũ | phải sửa test budget |
| Reversibility | cao | trung bình |

## 4. Khuyến nghị

**Option A**, kèm invariant ghi rõ trong spec: promotion KHÔNG BAO GIỜ áp cho item bị loại bởi guard lifecycle/non-promotable; non-PROJECT routes hành vi giữ nguyên byte-for-byte; assistant_claim vẫn không thể thành primary qua đường này (memory_type check đứng trước).

## 5. Schema / migration impact

Không schema. Thay đổi thuần `src/integration/m7/eligibility.py` (+ gọi `build_evidence_set` truyền route xuống — kiểm tra `evidence_builder.py:322` call site).

## 6. Rủi ro

- Primary pool có thể bị chiếm chỗ bởi state → decision khác rơi supporting. Đây chính là mục tiêu của finding (state trả lời "current step"), chấp nhận có chủ đích; benchmark V130-05 đo lại hit-rate B01/B06/B09.
- Route=None callers (nếu có) phải hành vi giống hệt hôm nay — test regression bắt buộc.

## 7. Test plan dự thảo

1. Unit: PROJECT route + state active + verification none → as_primary=True.
2. Unit: cùng input nhưng route SESSION/USER/None → as_primary=False (không đổi).
3. Unit: state superseded/archived trong PROJECT → vẫn không primary.
4. Unit: memory_type=assistant_claim trong PROJECT → không bao giờ primary.
5. Unit: budget tổng vẫn ≤ 5/3/8 và estimated_tokens tính đúng.
6. Regression: 3 test Option-B hiện có pass KHỎNG SỬA.

## 8. Gate criteria

G0 contract (rule + thứ tự guard) → G1 unit → G2 full suite ≥ baseline; benchmark before/after trong V130-05.

## 9. Rollback plan

Revert commit WP; không data.

## 10. Migration plan

Không cần.
