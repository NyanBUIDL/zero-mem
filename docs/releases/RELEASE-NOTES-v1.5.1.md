# RELEASE NOTES — Zero-Mem v1.5.1

**Trạng thái:** CANDIDATE (chưa phát hành — cần Gate COMMIT/PUSH + CI 9-cell xanh trước khi đánh dấu released)

## Defect đã sửa

| ID | Tóm tắt | Mức độ |
|---|---|---|
| DEF-020 | FTS `search_text` giờ mang **effective scope** (base + grant knowledge spaces) vào candidate SQL qua `_effective_scope_predicate`, dùng chung semantics authorization với structured path. Cross-profile space grant giờ authorize được FTS hit; event khác KS không còn là FTS candidate. | CAO |
| DEF-021 | `query_events`: limit hợp lệ bắt buộc ở public boundary (`invalid_limit` cho 0/negative/MAX+1/bool/float/str); `limit=None` → default 50 là trần server-owned, không còn `LIMIT -1` + fetchall toàn bộ. | CAO |
| DEF-022 | FTS multi-scope: một query candidate duy nhất với effective-scope predicate; kết quả không bao giờ vượt `limit` bất kể số scopes/grants; union paginate đúng, không duplicate. | CAO |
| DEF-023 | `register_source_with_blob`: blob-first (put blob trước), registry append-only một dòng; hết full-rewrite per ingest → O(1) amortized (benchmark: per-source 0.11-0.18 ms flat tới N=5000). | TRUNG BÌNH |
| DEF-024 | CI workflow mới `.github/workflows/v1.5.1-qualification.yml` (ubuntu/windows/macos × Python 3.11/3.12/3.13). | CAO |
| DEF-025 | README bỏ version claim sai ("v1.2.0"); pyproject license chuyển SPDX string `"MIT"`; project-state duplicate key sạch. | THẤP |
| DEF-027 | **Structured keyset pagination mất dữ liệu sau trang 1** — `query_events` decode cursor nhưng không truyền keyset vào `_select_m3`; mỗi trang re-fetch từ đầu và lọc Python-side làm rơi mọi row giữa ranh giới trang. Đã wire `keyset` vào SQL layer; walk đầy đủ 300/300 events qua ~61 trang. | CAO |

## Điều tra không tạo thay đổi code

- **DEF-026 (async deferred cancellation):** điều tra đầy đủ với probe thực nghiệm xác nhận cancel-before-start của CPython hoạt động đúng trên async timeout path — operation chưa start chưa hề chạm canonical storage (20 timeouts → 0 side effect). Không có defect hành vi; thêm pin tests `tests/unit/test_v151_phase4_async_cancellation.py`. Sync sidecar admission invariants giữ nguyên.

## ⚠️ BREAKING: cursor incompatibility

Cursor phân trang sinh từ **≤ v1.5.0 sẽ bị từ chối (`cursor_query_mismatch`) trên v1.5.1**: fingerprint của FTS cursor giờ gắn thêm effective scope (`fingerprint_extra = "v151|" + clause + params + grant_refs`) và structured cursor fingerprint gắn effective-scope text. Client đang giữ cursor cũ phải **bỏ cursor và restart từ trang 1**. Đây là chủ đích bảo mật: cursor cũ sinh dưới scope khác không được tái sử dụng.

## Known limitations

- In-flight dispatcher work vẫn không thể cancel giữa chừng (Python không kill thread an toàn) — admission giữ slot đến khi work xong; queued work bị timeout vẫn chạy nếu đã start. Cancel-before-start là thật (đã verify).
- Per-request SQLite connection ownership chưa proven → không thêm progress handler có thể bị race.
- DEF-005 (enrichment wiring), DEF-013 backlog admin CLI đa-agent vẫn mở.

## Rollback

- Retrieval/pagination: revert code; schema unchanged. Cursor v151 trở lại vô nghĩa sau revert — restart page 1.
- Registry: revert blob-first; canonical registry format vẫn đọc được; KHÔNG xoá orphan blob khi chưa có maintenance tooling.
- CI/docs/version bump: độc lập, revert riêng từng phần.
