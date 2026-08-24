# v1.4.1 — Lộ trình remediation (DEF-012 follow-up)

> Tình trạng hiện hành: 2 commit `69c337b` (fix DEF-012) + `3a40b7a` (docs FIXED) đã nằm trên
> master nhưng **CHƯA có gate approval, chưa bump version, chưa có overlay project-state,
> chưa tag**. Deep review lần 2 (2026-08-25) phát hiện thêm khiếm khuyết mới trong phần CLI
> đi kèm. Lộ trình này xử lý toàn bộ trước khi v1.4.1 được coi là đóng.

## Bối cảnh (đã xác minh trên cây, không phải claim)

**Đã đúng (giữ nguyên, không đụng lại):**
- Core fix DEF-012: M6Runtime `corpus_store_path` (precedence flag > env > XDG > fail-closed),
  fail-loud validation, wire `corpus_conn` vào `_open_facade` + injection_adapter +
  zero_mem_runtime. Focused test 13/13 PASS (tự chạy lại độc lập); full suite
  **3514 passed, 7 skipped, 0 failed** (~89s, Py 3.13 venv, isolated HOME).
- Biên kiến trúc giữ nguyên: read-only conn (`mode=ro` + `query_only=ON`), unconfigured → None
  → fail-closed như v1.4.0, zero dependency mới.

**Phát hiện mới (lý do có lộ trình này):**
- 🔴 Grant CLI (`zero-mem grant add/list/revoke`) ghi vào store riêng dưới XDG
  (`grants-derived.sqlite` + `grants-events.jsonl`) — KHÔNG nối vào đường ủy quyền production
  (`handlers._resolve_grants` đọc derived store chính). Grants tạo bằng CLI không bao giờ có
  hiệu lực thật ⇒ nguồn sự thật thứ hai cho grants, vi phạm ADR-009 boundary mà chính header
  file tuyên bố.
- 🟡 Connection leak: `_resolve_space_or_none` mở corpus conn rồi `finally: pass`;
  `AuthorizedReadService.close()` không đóng `_corpus_conn`.
- 🟡 Verification gap: test chấp nhận "THE DEF-012 core" tự dựng service thay vì gọi
  `_open_facade` thật; evidence lệch số (claim 3515/6 vs đo được 3514/7).
- 🟢 Hygiene: dead code trong `run_grant_list`, tên hàm sai ngữ nghĩa, `assert` trong code
  production, hack `sqlite3_error()`, doctor báo PASS chỉ dựa vào config tồn tại (không
  verify path hợp lệ lúc chạy).

## Nguyên tắc / invariant không được phá

- JSONL canonical append-only; SQLite/FTS/projection derived rebuildable (ADR-009) — áp dụng
  cho cả grants events.
- Authorization-first mọi read path; fail-closed không nới lỏng.
- Registry-first: đăng ký defect TRƯỚC khi sửa code (mọi defect mới dưới đây).
- RED-first cho mọi thay đổi product `src/` hoặc `zero_mem/`.
- Verifier luôn session độc lập; Gate chặn bằng evidence vật lý.
- KHÔNG push/tag đến khi GATE-FINAL-V141 duyệt (GITHUB-POLICY §mutation).

## Work-packages (dependency order)

| ID | Tên | Depends on | Gate |
|---|---|---|---|
| V141-R0 | Đăng ký DEF-013…016 vào registry + đối chiếu evidence lệch số + chốt phạm vi | — | GATE-R0 (duyệt registry + lộ trình này) |
| V141-R1 | ADR quyết định số phận grant CLI: (A) thu hồi khỏi v1.4.1 (revert phần CLI, giữ core fix) hay (B) wire CLI vào đúng data-root/control-plane thật | V141-R0 | GATE-R1 (maintainer chọn A/B) |
| V141-R2 | Implement theo lựa chọn R1 + fix DEF-014 (connection lifecycle) + DEF-015 (hygiene bundle) — RED-first từng defect | V141-R1 | GATE-R2 (duyệt kết quả sau Verifier) |
| V141-R3 | Đóng verification gap DEF-016: test chấp nhận đi qua handler path thật (`_open_facade` với runtime env-configured); tái lập full suite, chốt con số evidence chính thức | V141-R2 | gộp vào GATE-R2 nếu xong trước |
| V141-R4 | Closure: version bump 1.4.1 (checklist DEF-006: `version.py` + `release_common.py` pin + pkg tests), overlay V141 vào `project-state.yaml`, EVIDENCE + RELEASE-NOTES-v1.4.1, full suite cuối, Verifier độc lập | V141-R2 (+R3) | GATE-FINAL-V141 (duyệt release; tag/push là mutation riêng cần authorization tường minh) |

## Stop rules (áp dụng mọi WP)

- Cùng lỗi lặp ≥3 lần không rõ root cause → DỪNG hỏi.
- Phát hiện defect mới → DỪNG sửa, đăng ký registry trước.
- Cần dependency mới → DỪNG xin approval (không kỳ vọng).
- Mọi Gate chưa duyệt → không sang WP kế tiếp.

## Open questions (chờ quyết tại gate tương ứng)

- GATE-R1: A hay B cho grant CLI?
  - **A — thu hồi:** revert `zero_mem/cli.py` wiring + `commands_config_grant.py` +
    `commands_doctor.py` corpus-check ra khỏi v1.4.1 (hoặc đánh dấu experimental rõ ràng và
    loại khỏi claim FIXED); giữ nguyên core fix runtime/wire. Nhỏ nhất, an toàn nhất, v1.4.1
    thu hẹp thành pure DEF-012 wiring hotfix.
  - **B — wire thật:** CLI phải đọc/ghi đúng control-plane data-root của sidecar (một nguồn
    sự thật). Chạm canonical layout + lifecycle của runtime ⇒ cần thiết kế kỹ hơn, có thể
    đẩy sang v1.5 nếu thấy scope lớn.
- GATE-FINAL-V141: publish hay chỉ giữ local? (local Git mặc định; push/tag cần chỉ thị rõ).
