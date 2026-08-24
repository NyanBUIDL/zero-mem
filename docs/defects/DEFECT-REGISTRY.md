# DEFECT-REGISTRY — Hệ thống file lỗi bắt buộc của Zero-Mem

> **Vai trò:** Single source of truth cho mọi lỗi (defect) được phát hiện trong Zero-Mem — mở, đang sửa, đã sửa, đã đóng. Mọi fix PHẢI có entry tại đây TRƯỚC khi sửa code, và entry chỉ được đóng khi có bằng chứng test thực tế.
> **Nơi lưu:** `docs/defects/` (registry này + mỗi defect một file `DEFECT-XXX-*.md` khi cần chi tiết).
> **Quy tắc bắt buộc (MUST):**
> 1. Mọi lỗi phát hiện (audit, review, grep, test) → thêm entry vào bảng dưới với trạng thái `OPEN`.
> 2. Mọi fix phải đi theo thứ tự: **DEFECT entry (OPEN) → test RED-first → fix → test GREEN → cập nhật entry (FIXED + evidence) → mới được commit.**
> 3. Không được đóng entry bằng tự báo cáo — phải có lệnh test + kết quả nguyên văn.
> 4. Không xoá entry (append-only); supersede bằng ghi chú `SUPERSEDED-BY`.
> 5. Thiếu DEFECT entry mà có fix code trong commit → commit KHÔNG hợp lệ theo policy này.

## Bảng theo dõi (append-only)

| ID | Phát hiện | Mô tả | Mức độ | Loại | Trạng thái | Fix version | Evidence |
|---|---|---|---|---|---|---|---|
| DEF-001 | 2026-08-23 (GLM 5.3 review) | `budget.py:51` `verified_rank` so tuple `("verified","confirmed")` — KHÔNG thành viên nào của `VerificationStatus` tồn tại trong đó → item verified thật (`direct_tool_output`, `user_confirmation`, `deterministic_verification`, `approval`) KHÔNG BAO GIỜ được rank 0; ranking ưu tiên verified hoàn toàn chết. **Nặng hơn đánh giá cũ** (cũ nghĩ behavior-neutral — sai, vì `"verified"` cũng không phải enum value). | TRUNG BÌNH (retrieval ordering) | Thuật toán/logic enum | FIXED (v1.3.3) | v1.3.3 | RED: `1 failed in 0.38s` (assertion `verification='direct_tool_output' must yield verified_rank 0`) → fix (frozenset từ enum, tái dùng pattern eligibility.py) → GREEN: `51 passed in 0.90s` (DEF-001 4 test + test_m7_3_evidence_builder + test_v130_03_state_primary) |
| DEF-002 | 2026-08-23 (GLM 5.3 review) | `zero_mem/version.py` = `1.3.1` trong khi tag `v1.3.2` đã RELEASED_PUBLISHED → version-state mismatch; sdist/wheel build ra metadata sai version. | THẤP (packaging/audit noise) | Biến/state | FIXED (v1.3.3) | v1.3.3 | `__version__ = "1.3.3"`; pyproject dynamic version (attr zero_mem.version.__version__) — không hardcode nào khác; packaging tests `4 passed` |
| DEF-003 | 2026-08-23 (review; đã ghi nhận trong AUD-003) | M2.6 crash/power-loss durability chưa có proof test (malformed replay đã fail-closed tại `f2cce27`, nhưng chưa có kill-mid-write + journal replay test). | TRUNG BÌNH (durability) | Test coverage gap | CLOSED (v1.3.4) | v1.3.4 | `tests/unit/test_v134_def003_crash_durability.py`: (1) SIGKILL subprocess mid-ingest → canonical JSONL byte-identical + resume deterministic + full replay == clean ingest (logical digest, timestamp-normalized); (2) torn canonical tail (partial last line) never projected + repaired replay converges. 5/5 runs stable. FULL SUITE `3479 passed, 7 skipped, 0 failed` |
| DEF-004 | 2026-08-23 (review; kiến trúc đã ghi nhận) | Knowledge-space grants non-authorizing trong `_scope_allows()` (zm_meta không có cột knowledge_space_id). Fail-closed đúng, nhưng chức năng chưa work. **SCOUT V140-02: chỉ ảnh hưởng event-store path; corpus path ĐÃ hoạt động.** | TRUNG BÌNH (feature gap) | Kiến trúc | **FIXED (v1.4.0, V140-02, Option B)** | v1.4.0 | RED→GREEN `test_v140_02_ks_resolution.py` (9 tests); full suite `3412 passed, 7 skipped, 0 failed` (isolated HOME, Py 3.13.15). Resolution layer `src/access/knowledge_space_resolver.py` + facade expand (no zm_meta schema change, GATE-2 CHỌN B). |
| DEF-005 | 2026-08-23 (review) | `enrichment.py` `KeywordEnrichmentAdapter` viết xong nhưng chưa wire vào pipeline. | THẤP (optional) | Dead-path | OPEN (deferred — chỉ wire khi có retrieval-quality metric) | backlog | — |
| DEF-006 | 2026-08-23 (full-suite run sau DEF-002) | Version bump v1.3.1→v1.3.3 chưa propagate: hardcode `"1.3.1"` còn sót ở 8 chỗ — `release_helpers/release_common.py:127` (manifest pin, làm installer từ chối bundle mới), `tests/unit/test_pkg1_packaging.py:30`, `test_pkg2_packaging.py:159/172/177/179/207`, `test_pkg6_upgrade_lifecycle.py:148`. | TRUNG BÌNH (chặn packaging suite) | Hệ quả DEF-002 / hardcoded pin | FIXED (v1.3.3) | v1.3.3 | RED: pkg1+pkg2+pkg6 = 13 failed → fix 8 pins → GREEN: toàn bộ PASS (xem evidence V133) |
| DEF-007 | 2026-08-23 (full-suite run sau DEF-001) | `zm_verifications` (migrate_7) THIẾU cột provenance `trace_id`/`session_id`/`profile_id` mà mọi bảng M4 khác đều có; projector nhận `VerificationOp.profile_id` nhưng âm thầm drop khi INSERT. Hệ quả: EvidenceItem từ verification rows có `profile_id=None`, `lifecycle=None` (non-enum) → M8.5 scope calibration phân loại nhầm item in-scope là `excluded_unauthorized_scope` (score unavailable), vi phạm closed lifecycle enum mà M8.6 assert. | TRUNG BÌNH (retrieval scoring + authority enum) | Schema/provenance | FIXED (v1.3.3) | v1.3.3 | Migration v12 (additive, rebuildable) + projector persist + VerificationView expose + `_to_evidence_item` normalize None→"active" (match eligibility convention). RED: m8_6 = 9 failed; sau fix chain: FULL SUITE `3477 passed, 7 skipped, 0 failed` (Python 3.13.15, isolated HOME) |
| DEF-008 | 2026-08-23 (báo cáo model ngoài; đã xác minh trên tree) | Dead code `src/retrieval/cursor.py:99-100`: 2 dòng `canonical = json.dumps(...)` + `return hashlib.sha256(...)` lặp sau `return` đầu tiên trong `make_relation_fingerprint`. Không ảnh hưởng behavior (unreachable), chỉ noise audit. | THẤP (code hygiene) | Dead code | FIXED (v1.3.4) | v1.3.4 | Xóa 2 dòng; focused regression test_m3_pagination + test_m3_query: `80 passed` |
| DEF-009 | 2026-08-23 (báo cáo model ngoài; đã xác minh) | (a) `CorpusSourceRegistry._update_record` đọc toàn bộ JSONL mỗi lần update — O(n)/update, bottleneck nếu registry >10k records; (b) `authorized_read.py:343 fp_request` gán nhầm field name (`profile_id=project_filter`) — behavior-neutral vì chỉ feed cursor fingerprint versioning (scope thật nằm trong `eff_text`), nhưng dễ gây hiểu lầm khi audit. | THẤP→TRUNG BÌNH khi scale | Hiệu suất / đặt tên sai | OPEN (deferred) | v1.4.x (planned) | — (cần ADR: SQLite index cho registry là derived state thứ 2 của cùng dữ liệu canonical; fix (b) chỉ rename biến, làm cùng WP khi chạm file) |

## Quy trình fix chuẩn (per defect)

```
1. Ghi DEFECT entry (mô tả, root cause, phạm vi ảnh hưởng, biên an toàn).
2. Viết test thất bại trước (RED-first) bọc đúng hành vi sai.
3. Sửa code — thay đổi nhỏ nhất (smallest change), không mở rộng phạm vi.
4. Chạy test tập trung (focused test) → PASS.
5. Chạy full suite (isolated HOME) → 0 fail.
6. Cập nhật trạng thái + evidence + commit (thông điệp tham chiếu DEFECT-ID).
7. Chỉ đóng (CLOSE) khi có bằng chứng full-suite.
```

## Tech-stack fix (định hướng kỹ thuật cụ thể)

- **DEF-001:** tái sử dụng `_VERIFIED_STATUSES` pattern từ `eligibility.py:183` (import `VerificationStatus` từ `src/capture/event_types.py`, frozenset loại trừ `"none"`). KHÔNG hardcode chuỗi. Test: construct `EvidenceItem` với `verification="direct_tool_output"` vs `"none"`, verify `_order_key` ranking và `select_evidence` ordering. Python stdlib + pytest, không thêm dependency.
- **DEF-002:** bump `__version__` → `"1.3.3"`; đồng bộ `pyproject.toml` nếu có hardcode; verify qua import + kiểm tra metadata build nếu build trong scope.
- **DEF-003 (v1.3.4):** harness `subprocess` kill -9 mid-ingest + replay JSONL → assert digest; stdlib only.
- **DEF-004 (v1.4.x):** ADR trước — chọn giữa (A) thêm cột `knowledge_space_id` vào zm_meta (migration v11, schema-first) hoặc (B) resolution layer ánh xạ space → resource ids từ derived state. Không code trước ADR.
- **DEF-006:** mọi version pin đi qua `zero_mem.version.__version__` (single source); test pins dùng cùng import, KHÔNG hardcode lại trong lần bump sau.
- **DEF-007:** migration v12 additive (`ALTER TABLE ADD COLUMN` ×3, idempotent theo PRAGMA table_info); `_recreate_m4_tables()` phải re-apply migration mới nhất sau migrate_7 khi thêm migration tương lai; VerificationView expose provenance + lifecycle marker "active" (convention ProjectArtifactView).

## Lịch sử

- 2026-08-23: registry tạo theo chỉ đạo của maintainer (chat, 2026-08-23) — quyền tự quyết full-cycle cho gói v1.3.3 (fix DEF-001/002 → test → publish GitHub v1.3.3) được cấp trong chat, ghi vào mutation record.
