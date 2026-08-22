# v1.3.0 — Decision Log

## D-2026-08-22-01 — ks filter: cột đơn hay multi-value set trong `zm_meta`

- **Quyết định:** Cột đơn `knowledge_space_id TEXT` additive trên `zm_meta` (migration 11) + index; enforce qua `_EQUAL_FILTERS` và `search_text` structured filter.
- **Ngày:** 2026-08-22
- **Lý do:** Toàn bộ hệ thống hiện tại (zm_corpus_units migrate_10, zm_graph_nodes/zm_temporal_index migrate_9, access CHECK migrate_8, AuthorizedScope `src/corpus/retrieval.py`) đều mô hình hóa ks là single-value. Multi-value là phát minh yêu cầu không truy ngược được về finding/spec/ADR (vi phạm checklist §B.4). Query indexed WHERE đơn giản hơn EXISTS/join, rebuild từ canonical JSONL giữ nguyên tính derived-rebuildable.
- **Phương án bị loại:** multi-value set (bảng nối `zm_event_ks` / JSON column) — phức tạp migration + runtime cao hơn, không có consumer nào cần.
- **Trạng thái:** ĐÃ QUYẾT — user-approved tại Gate A (GATE-A-APPROVAL.md, 2026-08-22).

## D-2026-08-22-03 — Chính sách NULL knowledge_space_id

- **Quyết định:** NULL `knowledge_space_id` = "unscoped" = visible theo global-default-read; KHÔNG siết deny-by-default.
- **Ngày:** 2026-08-22
- **Nguồn:** User approval tại Gate A (GATE-A-APPROVAL.md, Điều kiện 2); master spec L51 ("Default có thể truy cập toàn cục nhưng retrieval luôn profile-first…") — xem `docs/v1.3.0/MASTER-SPEC-RECONCILIATION.md` mục 2.
- **Ràng buộc trong spec V130-02:** (1) invariant ghi tường minh; mọi thay đổi hướng deny-by-default là NEEDS DECISION riêng ngoài scope v1.3.0; (2) test bắt buộc: event NULL-ks xuất hiện trong search không-filter, bị loại khi filter ks cụ thể, authorization không leak ks-b vào query ks-a (kể cả NULL events).
- **Phương án bị loại:** deny-by-default cho NULL ks — trái global-default-read của AGENTS.md + master spec, không có yêu cầu nguồn.
- **Trạng thái:** ĐÃ QUYẾT (user-approved).

## D-2026-08-22-06 — Verification-strength cho memory type ngoài bảng closed (state)

- **Quyết định:** `derive_verification_strength` fallback: memory type không có row trong `VERIFICATION_STRENGTH_VALUES` → dùng strength của `verification_status` của chính item qua bảng mới `VERIFICATION_STATUS_STRENGTH` (giá trị tái sử dụng từ bảng đã duyệt: none=0.5, direct_tool_output=0.9, deterministic_verification=1.0, user_confirmation=0.9, approval=1.0). Không phát minh số mới.
- **Ngày:** 2026-08-23 (user chốt qua clarify trong V130-03).
- **Lý do:** V130-03 promotion làm state vào primary → M8.5 lần đầu phải score 'state' → CalibrationError (bảng closed thiếu) → score=None. User chốt: strength = strength_lookup(event.verification_status); phương án unscored/hằng số bị loại vì làm mất calibration metadata cho một loại evidence hợp lệ và phá invariant "mọi primary có score" trong test m8_6.
- **Phương án bị loại:** unscored + nới test m8_6 (user: "Không nới test"); thêm hằng số mới 0.85 cho state (phát minh số).
- **Trạng thái:** ĐÃ QUYẾT (user-directed).

## D-2026-08-22-05 — ProjectArtifactView.lifecycle_status mặc định "active"

- **Quyết định:** `ProjectArtifactView` thêm field `lifecycle_status` với giá trị tường minh `"active"`; `EvidenceItem.lifecycle` không bao giờ None từ đường artifact.
- **Ngày:** 2026-08-23 (phát hiện trong V130-03; user chốt xử lý qua clarify)
- **Lý do:** `zm_project_artifacts` (migrate_7) không có cột lifecycle — artifact linkage là current-truth record (tạo active, update tại chỗ, không supersede). Trước V130-03 latent bug chưa lộ vì ART1 bị cắt khỏi bounded set; promotion đổi selection làm nó vào supporting với `lifecycle=None`, vi phạm well-formed authority fields (9 test m8_6 fail). User chốt: fix ở view (artifact lifecycle = active), KHÔNG nới allowed_life nhận None.
- **Phương án bị loại:** thêm None vào allowed_life trong test m8_6 (nới lỏng assertion authority); loại artifact thiếu lifecycle khỏi eligibility set (mất evidence hợp lệ).
- **Trạng thái:** ĐÃ QUYẾT (user-directed).

## D-2026-08-22-02 — V130-01 và V130-02 tách hay gộp WP

- **Quyết định:** TÁCH thành 2 WP độc lập (V130-01 FTS OR-fallback; V130-02 ks schema+enforce).
- **Ngày:** 2026-08-22
- **Lý do:** (1) V130-01 thuần tầng `search.py`, không schema — rollback/review độc lập; V130-02 có schema migration 11 + backfill + rebuild test — rủi ro và review surface khác hẳn. (2) Verifier-loop yêu cầu verdict per WP; gộp làm verdict khó fail-closed vì một finding schema sẽ chặn cả fix retrieval thuần túy. (3) Dependency thực chỉ tồn tại V130-04→V130-02 (temporal cần ks), không phải 01↔02.
- **Phương án bị loại:** gộp WP — giảm số lần gate nhưng mất khả năng rollback/review tách bạch giữa "không-schema" và "có-schema".
- **Trạng thái:** ĐÃ QUYẾT — user-approved tại Gate A.
