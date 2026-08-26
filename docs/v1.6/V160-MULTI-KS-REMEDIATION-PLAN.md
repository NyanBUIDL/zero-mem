# V1.6.0 REMEDIATION PLAN — Multi-KS + capture wiring (DEF-034)

**Trạng thái:** ĐANG THỰC THI — ADR-V160-01 ACCEPTED; **C1–C4 DONE** (C1: 71bb865+cfea75d; C2: 617ed92+0e3abc9+7a59758+a4a0669; C3: 082227d; C4: 8aab66d); **C5–C10 pending** (mỗi commit có gate riêng).
**Nguyên tắc:** không migration trong V1.5.1; canonical append-only; derived rebuildable; RED-first; commit nhỏ.
**Phạm vi:** commit evidence DEF-034 KHÔNG đổi production code; plan này là kế hoạch cho V1.6.0.

## Các commit đề xuất (nhỏ, tuần tự)

### C1 — Capture contract: canonical knowledge_space_ids (forward-only) — **DONE (commit 71bb865 + follow-up) — đủ điều kiện mở C2**
- `src/capture/validation.py`: `knowledge_space_ids` vào OPTIONAL_FIELDS + validate strict (list[str] non-empty, unique, MAX_KNOWLEDGE_SPACE_IDS=16, MAX_KNOWLEDGE_SPACE_ID_LENGTH=64).
- `src/capture/event_types.py`: hằng số contract bounds.
- `src/capture/adapter.py`: param `knowledge_space_ids` (payload key thắng), strict type (raise non-list/non-str), dedup lenient giữ thứ tự; None omit, [] explicit.
- `src/integration/capture_adapter.py`: `_envelope` truyền `knowledge_space_ids` (legacy singular → list).
- Evidence: RED 14 failed (0.16s) → GREEN 14 passed; follow-up edge cases (review) RED 6 failed → GREEN (23 passed); adjacent + evidence regression 146 passed; full suite 3550 passed / 5 failed (env/Windows-specific pre-classified) / 38 skipped / 11 errors (installer quirk) — không regression. Test: `tests/unit/test_v160_c1_capture_ks.py` (23 tests).

### C2 — Ingest denormalize: zm_event_spaces junction + PRIMARY-KS (migration additive) — **DONE (commit 617ed92 + follow-up 0e3abc9 + round-2 7a59758 + round-3 a4a0669)**
- Migration v13 (additive): `zm_event_spaces(event_id, knowledge_space_id, PK)` + index ks; backfill từ `zm_meta.knowledge_space_id` (legacy singular, **chỉ non-empty string** — filter Python `str.strip()` parity ingest; NULL + mọi whitespace-only KHÔNG backfill; numeric-origin promote nguyên trạng — ADR §2 amendment, xem bên dưới); down = DROP (derived, rebuildable).
- `src/storage/ingest.py`: helper `_knowledge_spaces(env)` (precedence ADR §2: list thắng; absent/empty → legacy non-empty string; else []); INSERT junction 1 row/KS; `zm_meta.knowledge_space_id` = PRIMARY-KS (first của list, NULL nếu rỗng); zm_scopes 1 knowledge_space row/KS.
- Test RED-first: RED 7 failed (0.32s) → GREEN 7 passed; schema-version assertions 12→13 cập nhật (hợp lệ — migration mới; gồm M8 describe constants + pkg5/pkg6 pins); adjacent 1456 passed (33 file schema-affected + C1/C2). Test: `tests/unit/test_v160_c2_junction.py` (8 tests).
- **Review follow-up round-1 (commit 0e3abc9):** P1 backfill lọc blank legacy — RED 1 failed → GREEN 8 passed; P2 test upgrade thật qua migration runner (`downgrade_to(12)` → insert legacy → reopen → `ensure_schema()`; assert version 13 + backfill đúng + ledger 1 row v13) + downgrade test (table+index bị loại); P3 đổi tên `test_rebuild_junction_faithful` → `test_fresh_ingest_junction_parity` (rebuild thật là C3).
- **Review follow-up round-2 (commit 7a59758):** P1-2 SQLite `TRIM()` chỉ bỏ U+0020 → tab/newline/CR/NBSP vẫn bị backfill (probe: `('\t')`, `('\n')`); TEXT affinity biến numeric legacy `123` thành text `'123'` không phân biệt được với string hợp lệ. Fix: filter Python `str.strip()` (parity chính xác ingest — RED 1 failed → GREEN 8 passed, probe xác nhận junction chỉ còn valid + numeric-as-text); numeric boundary ghi vào ADR §2 amendment (canonical replay C3 = gate dứt điểm). P2-2 đồng bộ số liệu full-suite.
- **Review follow-up round-3 (commit a4a0669):** P2 backfill memory — `fetchall()` toàn bảng → 2 bản trong RAM (OOM store lớn). Fix: stream batch cố định (`_BACKFILL_BATCH_SIZE=1000`, read cursor `fetchmany` + write cursor `executemany` riêng — INSERT không reset SELECT); semantics/ADR không đổi. RED 1 failed (guard `".fetchall(" not in src`) → GREEN 9 passed; behavioral 3007 legacy rows backfill đủ qua 4 batch.
- **Full-suite gate (raw evidence, review P4 + P2-2 + closure sync):** full suite CUỐI (sau round-3, commit a4a0669): **3568 passed / 5 failed / 38 skipped / 11 errors** (installer quirk) — con số ĐỒNG BỘ với raw log `audit/evidence-v160-c2/fullsuite-round3-5failed.txt` (số liệu round-2 3567 là chạy trước test mới round-3; giữ `fullsuite-round2-5failed.txt` làm artifact trung gian). Failing IDs là tập con của 6 pre-classified (đã baseline tại C1): 4×`test_v122_*` (multiprocessing pipes — sandbox/Windows) + `test_v151_phase4_async_cancellation::test_def026_abandoned_work_is_cancelled_before_start_when_worker_frees` (timing); `test_v134_def003_crash_durability::test_sigkill_mid_ingest_preserves_canonical_and_resumes` (flaky sigkill) **PASS run này**. **Baseline diff:** chạy chính 6 IDs này tại C1 (cfea75d, git worktree) → cả 6 đều FAIL trước C2 — pre-existing env/Windows, không regression (`c1baseline-cfea75d-6tests-same-failures.txt`). Raw logs (12 file): `audit/evidence-v160-c2/` — gồm `round3-red-1failed.txt` + `round3-green-9passed.txt` + `fullsuite-round3-5failed.txt`.

### C3 — Rebuild/replay: junction rebuild từ canonical — **DONE (commit 082227d)**
- Recovery/rebuild re-ingest canonical → junction tái tạo (không backfill từ derived).
- **RED:** `DERIVED_TABLES` chưa chứa `zm_event_spaces` → rebuild không drop junction; stale rows sống sót qua `ON CONFLICT DO NOTHING` (rebuild ev1 [A]→[B] cho junction {A,B} thay vì {B}). RED 2 failed → GREEN 3 passed.
- **Fix (tối thiểu):** thêm `zm_event_spaces` vào `src/storage/ingest.py::DERIVED_TABLES` (derived, rebuildable — drop rồi tái tạo từ canonical; không backfill từ derived).
- Test behavioral: rebuild stale → junction == canonical (stale biến mất, PRIMARY-KS theo canonical); rebuild cùng canonical → junction == fresh ingest (multi/legacy/unscoped); static guard `zm_event_spaces` ∈ DERIVED_TABLES. Test: `tests/unit/test_v160_c3_rebuild_junction.py` (3 tests).
- Evidence: RED 2 failed (0.18s) → GREEN 3 passed (2.29s); adjacent rebuild/query regression 333 passed; full suite **3571 passed / 5 failed** (tập con 6 IDs baseline C1; v134 flaky pass) / 38 skipped / 11 errors. Raw logs (4 artifact C3): `audit/evidence-v160-c2/c3-red-2failed.txt`, `c3-green-3passed.txt`, `c3-adjacent-333passed.txt`, `c3-fullsuite-5failed.txt`. DEF-034 stays OPEN.

### C4 — Authorization: union read + per-row grant qua junction — **DONE (commit 8aab66d)**
- `src/access/authorized_read.py`: `_ks_predicate` = **correlated `EXISTS` trên junction** (không JOIN — event [A,B] UNION [A,B] xuất hiện đúng 1 lần); `_scope_allows` nhận **row's KS set** (`_junction_ks_map` một query/trang cho defensive re-check; `_row_ks_ids` fallback singular cho M4); helper mới `_junction_ks_map`/`_row_ks_ids`.
- **Chống duplicate:** correlated EXISTS (không JOIN) — test union no-dup; pagination 10 events multi-KS page-by-page không skip/lặp.
- Semantics: request KS = UNION; grant ∩ row KS set ≠ ∅ authorize; NULL/empty KS (không junction row) không bao giờ space-grant authorize (fail-closed).
- **Fingerprint:** đã bind KS canonicalized (sort + dedup — set union trong compose) — test [B,A] reuse cursor [A,B], [A] mismatch.
- **Gate matrix (behavioral):** (profile NULL/non-NULL) × (ks NULL/empty/list/legacy) qua global/default/local/grant reads; union-of-scopes (grant scopes mở rộng độc lập) được test đúng semantics.
- Test RED-first: **RED 6 failed (0.43s) → GREEN 11 passed** (`tests/unit/test_v160_c4_auth_junction.py`); adjacent m5+m3+DEF-010/011/012 475+156 passed (DEF-028 regression giữ); full suite **3581 passed / 6 failed** (đúng tập pre-classified) / 38 skipped / 11 errors.
- **Review follow-up (P1 — junction là NGUỒN DUY NHẤT, fail-closed):** bỏ OR singular fallback (`NOT EXISTS junction AND zm_meta.knowledge_space_id IN ...`) khỏi `_ks_predicate` → chỉ correlated EXISTS; defensive re-check query_events/get_event/get_trace chỉ dùng junction map (bỏ `or _row_ks_ids`); giữ API alias `row_knowledge_space_id` cho unit callers cũ (DEF-010/011/012 direct calls) nhưng production event-path KHÔNG dùng alias làm fallback. RED 1 failed (singular-no-junction bị leak) → GREEN; legacy đúng: fixture DEF-010 đổi sang **v12 → insert singular → migration runner → v13 (junction backfill)** — grant authorize qua junction; test `test_legacy_v12_upgrade_authorizes_via_junction` guard. Adjacent **511 passed**; full suite **3583 passed / 6 failed** (pre-classified) / 38 skipped / 11 errors. Raw logs: `audit/evidence-v160-c2/c4-*` + `c4fu-*`. DEF-034 stays OPEN.

### C5 — FTS parity: candidate SQL qua junction
- `src/retrieval/search.py` + `authorized_read.search_text`: candidate_where dùng junction.
- Cùng correlated EXISTS pattern như C4 (parity structured/FTS).
- Test: FTS multi-KS hit + grant lọc đúng (behavioral).

### C6 — Graph/temporal: PRIMARY-KS (quyết định đóng)
- m8 derived index/temporal/graph: dùng `zm_meta.knowledge_space_id` (PRIMARY-KS) — KHÔNG junction (đơn giản; junction chỉ cho auth/FTS).
- `graph_sources.py`: bỏ `knowledge_space_id=None` cho event-derived nodes (dùng primary từ zm_meta).
- **Limitation (round-3):** event [A,B] hiện dưới graph scope primary (A) — grant B đọc được event qua structured/FTS nhưng graph representation gated bởi primary (fail-closed tradeoff); gate test: grant B behavior qua structured + graph.
- Test: graph/temporal node mang primary ks (behavioral).

### C7 — list_knowledge_space parity
- `src/retrieval/relations.py`: trả rows từ junction (bỏ hardcode [] — docstring M2 schema đã cũ).
- Test: list_knowledge_space trả ks rows khi junction có dữ liệu (behavioral).

### C8 — Projection parity
- `src/projection/render.py`: render `knowledge_spaces` từ event ks (bỏ hardcode v9).
- Test: projection note mang ks list (behavioral).

### C9 — Corpus: giữ singular, document
- Không đổi `zm_corpus_units.knowledge_space_id` (singular); ghi limitation. Multi-KS unit → increment riêng sau.

### C10 — Backward compat + acceptance + release gates
- Canonical cũ đọc được; upgrade migration additive; rollback test.
- Acceptance: multi-KS end-to-end (capture → canonical → ingest → junction → structured/FTS/grant) + legacy compat.
- Trace-union: semantic definition only (không expose surface V1.6.0 — round-3 scope); gate test chỉ khi surface trace-scoped được thêm sau.
- Full suite + benchmark junction point-lookup (SPIKE-B: 2.5µs).
- Update docs (MASTER-SPEC projection, ARCHITECTURE, README) + ADR ACCEPTED.

## Risk matrix
| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Migration additive vỡ derived cũ | Thấp | Additive + rebuild test; rollback drop table |
| Authorization correlated-EXISTS trên junction chậm | Thấp | Index; SPIKE-B đo 2.5µs point-lookup |
| Capture contract mở rộng vỡ writer cũ | Thấp | OPTIONAL (forward-only); canonical cũ vẫn validate |
| UNION semantics sai kỳ vọng | Trung bình | ADR chốt trước; acceptance test rõ |
| FTS/structured parity lệch (lặp DEF-020) | Trung bình | Cùng junction predicate cho cả 2 path; test parity |
| NULL/legacy/global-read exposure | Trung bình | Gate matrix behavioral (không no-leak-observed claim vội) |
| Projection/list_knowledge_space thay đổi output | Thấp | Update fixtures chủ động; document breaking |

## Rollback plan
- Migration: additive → downgrade = DROP `zm_event_spaces` (derived, rebuildable); `zm_meta.knowledge_space_id` giữ nguyên.
- Capture contract: forward-only — canonical cũ không cần rollback; writer cũ vẫn chạy (không set list).
- Auth/FTS: revert code (junction → singular) — schema giữ; rebuild derived.
- Không bao giờ xóa canonical hay rewrite lịch sử.

## Gates V1.6.0
1. ADR-V160-01 ACCEPTED (maintainer) — sau khi sửa corruption/probes/sequencing.
2. C1-C10 mỗi commit: RED-first → focused → adjacent → full suite.
3. Acceptance multi-KS + legacy compat + NULL/legacy/global-read matrix PASS.
4. Benchmark junction (1k/10k/100k) latency/memory.
5. Release gates: version bump, release notes, CI matrix, doctor/docs sync.