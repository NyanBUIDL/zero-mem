# Selection-Shape Registry — danh mục giả định ngầm về loại bằng chứng

> QUY TẮC: Bất kỳ WP nào thêm memory type / verification value / lifecycle value mới
> BẮT BUỘC đọc và cập nhật file này trước khi merge.
> Đây là danh mục mọi nơi hệ thống hard-code giả định về loại bằng chứng.
>
> Nguồn enum chuẩn:
> - Verification: `src/capture/event_types.py::VerificationStatus` (none, direct_tool_output,
>   user_confirmation, deterministic_verification, approval) + `src/project_memory/contracts.py::VERIFICATION_STATUS_ENUM`.
> - Lifecycle (memory): `LIFECYCLE_ENUM` trong `src/project_memory/contracts.py`
>   (candidate/active/superseded/conflicted/archived/deleted/...).
> - Lifecycle (corpus): `src/corpus/query_planner.py::_VALID_LIFECYCLE` (mirror SourceLifecycle).
> - Resource types: `src/m8/vocabulary.py::RESOURCE_TYPES`.

## Bảng registry

| # | Vị trí (file:line) | Giả định cũ | Trạng thái | Fix | Commit |
|---|---|---|---|---|---|
| 1 | `src/project_memory/reader.py` ProjectArtifactView + `_artifact_view` | artifact không có lifecycle → EvidenceItem.lifecycle=None | FIXED | đặt tường minh `lifecycle_status="active"` (current-truth record, D-2026-08-22-05) | `20bbe3e` |
| 2 | `tests/unit/test_m8_6_integration.py` allowed_ver (trước đây dòng 349, 398) | hard-code selection cũ `(None,"none","verified")` | FIXED | snapshot-diff mutation-check + import VERIFICATION_STATUS_ENUM từ contracts; thêm test injection chứng minh diff bắt mutation | `20bbe3e`, `e656ecf` |
| 3 | `src/m8/calibration.py` VERIFICATION_STRENGTH_VALUES | không có 'state' → CalibrationError → score=None | FIXED | strength_lookup(event.verification_status) qua bảng VERIFICATION_STATUS_STRENGTH, D-2026-08-22-06 | `ffaf7ba` |
| 4 | `src/integration/m7/budget.py:51` verified_rank | `"verified", "confirmed"` — giá trị ngoài M1 enum ("verified" không có trong VerificationStatus) | OPEN | Chưa sửa: rank chỉ ảnh hưởng thứ tự trong pool, không phải authority. Ghi nhận: nếu enum mở rộng cần rà lại. Không gãy trong V130-03 vì so sánh trên EvidenceItem.verification vốn đến từ stored verification_status. | — |
| 5 | `src/integration/m7/eligibility.py:178` is_verified | `"verified", "confirmed"` — cùng vấn đề #4; "confirmed" trùng lifecycle value chứ không phải verification | OPEN | Chưa sửa (behavior hiện tại là baseline đã duyệt M7.3). Lưu ý: verification_status thực của hệ thống là none/direct_tool_output/deterministic_verification/user_confirmation/approval → is_verified hiện luôn False cho memory events! Điều này có nghĩa promotion V130-03 là con đường CHÍNH để state vào primary. Đánh giá lại khi có yêu cầu thay đổi role classification. | — |
| 6 | `src/integration/m7/eligibility.py:182` promotable set `(decision, verified_state, tool_observation)` | chỉ 3 memory type được primary mặc định | OPEN (by-design) | Đây là chính sách role đã duyệt; V130-03 thêm đường riêng cho state qua opt-in flag. WP thêm type mới phải quyết định có thêm vào set này không. | — |
| 7 | `src/integration/m7/eligibility.py` `_NON_PROMOTABLE_TYPE` = {assistant_claim, inference, user_statement} | 3 type cấm primary | OPEN (by-design, guard) | Guard đúng hướng; V130-03 đã thêm defense-in-depth trong promotion block (F2 fix) | `e656ecf` |
| 8 | `src/integration/m7/eligibility.py` `_NON_CURRENT_LIFECYCLE`, `_SUBORDINATE_LIFECYCLE`, `_INELIGIBLE_LIFECYCLE` | lifecycle sets hard-code | OPEN (by-design) | Khớp LIFECYCLE_ENUM; mirror thủ công — nếu enum đổi phải đồng bộ tay. Calibration có bản mirror riêng (`INELIGIBLE_LIFECYCLE` calibration.py:186, comment ghi rõ nguồn). | — |
| 9 | `src/m8/calibration.py:186` INELIGIBLE_LIFECYCLE {"deleted"} | mirror của M7 rule | OPEN (by-design) | Đã có comment dẫn nguồn; hai bên phải đổi cùng nhau nếu enum đổi. | — |
| 10 | `src/m8/graph_access.py:233-237,281-285` resource_type routing | if/elif per resource type chọn authorized read method | OPEN (by-design) | Routing per-type là thiết kế M8.3; thêm resource type mới phải thêm nhánh + method tương ứng. Không phải selection-shape assumption về giá trị. | — |
| 11 | `src/integration/m7/evidence_builder.py:36-44` _M4_RT map | map domain→resource_type 6 giá trị | OPEN (by-design) | Thêm M4 domain mới phải cập nhật map này + `_route_resource_type`. | — |
| 12 | `src/integration/m7/m8_integration.py:96` _IDENTITY_ATTR_FOR_RESOURCE_TYPE | identity attr per resource type, default "id" | OPEN (by-design) | `.get(rt, "id")` fail-open sang id chung — an toàn; thêm type mới nên thêm attr cụ thể. | — |
| 13 | `src/projection/engine.py:113-119` PROJECTABLE_RESOURCE_TYPES | 5 M4 types projectable ra Obsidian | OPEN (by-design) | Set closed theo thiết kế M9.2; artifact/corpus cố tình không project. | — |
| 14 | `src/corpus/query_planner.py:43` _VALID_LIFECYCLE | corpus lifecycle enum riêng (có "confirmed" mà memory enum cũng có) | OPEN (by-design) | Hai enum song song (memory vs corpus) — trùng tên nhưng ngữ cảnh khác; đã mirror đúng SourceLifecycle. | — |
| 15 | `src/corpus/retrieval.py:295` + query_planner `_EXCLUDED_LIFECYCLE={"deleted"}` | excluded deleted | OPEN (by-design) | Khớp invariant deleted-exclusion toàn hệ thống. | — |
| 16 | `src/integration/hermes_read_adapter.py` / m6 tools resource routing | per-type dispatch | OPEN (by-design) | Routing, không phải giá trị authority. | — |

## Lịch sử sự cố (bài học)

- **V130-03 gãy 3 lần cùng gốc**: promotion làm state vào bounded set lần đầu → lộ (a) artifact view thiếu lifecycle, (b) m8_6 allowed_ver hard-code selection cũ, (c) M8.5 strength table thiếu 'state'. Cả 3 đã FIXED (#1–#3).
- Quy tắc phòng ngừa: mọi WP chạm selection/role/authority PHẢI chạy audit kiểu hạng mục 1 và cập nhật file này.

## Quy tắc cập nhật
- Thêm memory type mới → rà từng hàng, cập nhật chỗ bị ảnh hưởng, tick trạng thái.
- Phát hiện chỗ hard-code mới → thêm hàng ngay trong cùng WP phát hiện.
