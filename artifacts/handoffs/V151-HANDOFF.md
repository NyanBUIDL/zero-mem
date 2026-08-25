# V151 HANDOFF — Zero-Mem v1.5.1 Finish (candidate, chưa commit)

## Observed

- Cây `zero-mem-v123-engineering` dirty trên baseline tag `v1.5.0` @ 10ad8da: code WP01/02/03/05/06 (DEF-020..025) đã có nhưng evidence thiếu; Phase 4 (deadline/admission) chưa recon.
- Suite candidate trước phiên: 3551/12/0.

## Changed (phiên này)

| # | Thay đổi | File |
|---|---|---|
| 1 | DEF-026 recon: Graphify snapshot + grep ownership + probe thực nghiệm → **CLOSED no-defect** (cancel-before-start thật); thêm pin tests | `tests/unit/test_v151_phase4_async_cancellation.py` (mới), `docs/defects/DEFECT-REGISTRY.md` |
| 2 | **DEF-027 mới phát hiện trong B3**: structured keyset pagination mất dữ liệu sau trang 1 — keyset không được truyền vào `_select_m3`. Fix nhỏ nhất: wire `keyset` vào call-site duy nhất + RED-first tests | `src/access/authorized_read.py` (+1 dòng), `tests/unit/test_v151_finish_def027_keyset.py` (mới), registry |
| 3 | Version bump 1.5.0 → 1.5.1 đồng bộ toàn bộ pin | `zero_mem/version.py`, `release_helpers/release_common.py`, `test_pkg{1,2}_packaging.py`, `test_pkg6_upgrade_lifecycle.py` |
| 4 | Release notes với cursor incompatibility bắt buộc | `docs/releases/RELEASE-NOTES-v1.5.1.md` (mới) |
| 5 | Evidence verbatim toàn gói | `docs/v1.5.1/EVIDENCE.md` (mới) |

(Kèm các thay đổi WP01-06 có từ trước phiên: `authorized_read.py`, `search.py`, `models.py`, `registry.py`, CI workflow, README, pyproject — xem git status.)

## Verified

- Full suite ×2 liên tiếp isolated HOME: **3555 passed / 12 skipped / 0 failed** (85.83s / 85.95s) — baseline 3535/12/0, zero failure.
- Packaging tests (pkg1+pkg2+pkg6+version integrity): 28 passed. Doctor honesty: 9 passed. `check_machine_state.py`: machine state OK.
- DEF-027: RED 2 failed → fix 1 dòng → GREEN 2 passed + regression 201 passed auth/retrieval/pagination + repro 300/300 events qua 60 trang.
- Bằng chứng hiệu năng: SQL trace `limit=1`→`LIMIT 2`, 0 unbounded page query; tracemalloc single-page peak flat ~20.6KB từ 1k→100k rows; registry benchmark per-source ms flat (O(1) amortized, old-model ×502 bytes tại N=5000). Verbatim trong `docs/v1.5.1/EVIDENCE.md`.
- Independent fail-closed review (B5): **APPROVE for v1.5.1 candidate** — 0 blocking; PASS trên cả 8 risk-area (canonical/derived, authorization-before-ranking cả structured+FTS, DEF-027 fix đúng với proof no-gap, path safety, error sanitization + fingerprint_extra chỉ feed hash, blob-first concurrency, secret scan sạch, test integrity). Report verbatim: `zero-mem-dev-data/evidence/v151f-b5-independent-review.md`.
  - Finding LOW duy nhất (non-blocking, backlog): `register_source_with_blob` không upgrade `blob_ref` cho record đã tồn tại registered-without-blob → blob mới bị orphan, binding mất âm thầm (fail-safe, edge-case). Đề nghị xử lý ở phiên sau hoặc ghi backlog.

## Risk

- **Cursor incompatibility chủ đích**: cursor ≤v1.5.0 thành mismatch (fingerprint giờ gắn effective scope) — client phải restart page 1. Đã ghi trong release notes.
- **Divergence với master (cho Gate PUSH)**: `v1.5.1-hotfix` phân kỳ từ 10ad8da; master có d40d273 (publication record) + 3bc5ba4 (DEF-019 doctor honesty) mà nhánh v1.5.1 chưa mang — cây đang chứa code doctor + test bản TRƯỚC DEF-019, mâu thuẫn registry đã ghi DEF-019 FIXED. Trước push cần merge/rebase master vào hotfix (additive) và chạy lại suite.
- In-flight dispatcher work không cancel giữa chừng (thiết kế hiện tại); queued-cancelled work-item rác nằm trong SimpleQueue tới khi worker rảnh (bounded per-burst, O(1) dequeue).
- Review LOW backlog: `register_source_with_blob` không upgrade blob_ref cho record registered-without-blob (orphan blob, fail-safe).
- tracemalloc walk 100k dừng giữa chừng do timeout script — memory-flat đã chứng minh, completeness chứng minh ở scale nhỏ hơn.
- CI workflow mới chưa chạy trên GitHub (cần Gate PUSH).
- `project-state.yaml` chưa đụng — chỉ cập nhật overlay sau push + CI xanh theo Gate.

## Next

1. ⛔ **GATE COMMIT** — chờ `GATE-V151-COMMIT-APPROVAL.md` ở workspace root. Commit plan đề xuất bên dưới.
2. Sau commit: ⛔ **GATE PUSH** — chờ `GATE-V151-PUSH-APPROVAL.md`; push master; xác nhận CI 9-cell xanh trên GitHub.
3. Chỉ sau push + CI xanh: cập nhật project-state overlay v1.5.1. KHÔNG tự đánh RELEASED_PUBLISHED.
4. Backlog: admin CLI đa-agent (ADR-V141-01 Opt B); maintenance tooling cho orphan blob.

## Authorization status

- Toàn bộ thay đổi local-only, KHÔNG git add/commit/push/tag (đúng rule #3 prompt).
- Graphify read-only ngoài repo (snapshot `zero-mem-dev-data/graphify/v151-finish-b1/`), không vào runtime/dependencies/tests.
- Không đổi canonical JSONL format/schema; không thêm runtime dependency; không sửa Hermes core; không đụng `project-state.yaml`.
