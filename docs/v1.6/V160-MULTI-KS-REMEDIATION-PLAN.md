# V1.6.0 REMEDIATION PLAN — Multi-KS + capture wiring (DEF-034)

**Trạng thái:** ĐANG THỰC THI — ADR-V160-01 ACCEPTED; C1 (71bb865+cfea75d) và C2 (617ed92) DONE; C3–C10 pending (mỗi commit có gate riêng).
**Nguyên tắc:** không migration trong V1.5.1; canonical append-only; derived rebuildable; RED-first; commit nhỏ.
**Phạm vi:** commit evidence DEF-034 KHÔNG đổi production code; plan này là kế hoạch cho V1.6.0.

## Các commit đề xuất (nhỏ, tuần tự)

### C1 — Capture contract: canonical knowledge_space_ids (forward-only) — **DONE (commit 71bb865 + follow-up) — đủ điều kiện mở C2**
- `src/capture/validation.py`: `knowledge_space_ids` vào OPTIONAL_FIELDS + validate strict (list[str] non-empty, unique, MAX_KNOWLEDGE_SPACE_IDS=16, MAX_KNOWLEDGE_SPACE_ID_LENGTH=64).
- `src/capture/event_types.py`: hằng số contract bounds.
- `src/capture/adapter.py`: param `knowledge_space_ids` (payload key thắng), strict type (raise non-list/non-str), dedup lenient giữ thứ tự; None omit, [] explicit.
- `src/integration/capture_adapter.py`: `_envelope` truyền `knowledge_space_ids` (legacy singular → list).
- Evidence: RED 14 failed (0.16s) → GREEN 14 passed; follow-up edge cases (review) RED 6 failed → GREEN (23 passed); adjacent + evidence regression 146 passed; full suite 3550 passed / 5 failed (env/Windows-specific pre-classified) / 38 skipped / 11 errors (installer quirk) — không regression. Test: `tests/unit/test_v160_c1_capture_ks.py` (23 tests).

### C2 — Ingest denormalize: zm_event_spaces junction + PRIMARY-KS (migration additive) — **DONE (commit 617ed92)**
- Migration v13 (additive): `zm_event_spaces(event_id, knowledge_space_id, PK)` + index ks; backfill từ `zm_meta.knowledge_space_id` (legacy singular); down = DROP (derived, rebuildable).
- `src/storage/ingest.py`: helper `_knowledge_spaces(env)` (precedence ADR §2: list thắng; absent/empty → legacy non-empty string; else []); INSERT junction 1 row/KS; `zm_meta.knowledge_space_id` = PRIMARY-KS (first của list, NULL nếu rỗng); zm_scopes 1 knowledge_space row/KS.
- Test RED-first: RED 7 failed (0.32s) → GREEN 7 passed; schema-version assertions 12→13 cập nhật (hợp lệ — migration mới; gồm M8 describe constants + pkg5/pkg6 pins); adjacent 1456 passed (33 file schema-affected + C1/C2); full suite 3565 passed / 6 failed (env/Windows-specific pre-classified: 4 multiprocessing pipes, v134 sigkill flaky, DEF-026 timing) / 38 skipped / 11 errors (installer standalone-python quirk) — không regression. Test: `tests/unit/test_v160_c2_junction.py`.

### C3 — Rebuild/replay: junction rebuild từ canonical
- Recovery/rebuild re-ingest canonical → junction tái tạo (không backfill từ derived).
- Test: rebuild sau khi xóa derived → junction == ban đầu (behavioral, không inspect).

### C4 — Authorization: union read + per-row grant qua junction
- `src/access/authorized_read.py`: `_ks_predicate` dùng **correlated `EXISTS` trên junction** (không JOIN — chống duplicate); `_scope_allows` nhận row's set ks.
- **Chống duplicate (round-3):** dùng correlated EXISTS subquery (không JOIN trực tiếp) — event [A,B] xuất hiện đúng 1 lần; pagination không skip/lặp; cursor fingerprint bind KS filter canonicalized (sort + dedup).
- Semantics: request KS list = UNION; grant ∩ row's ks ≠ ∅; NULL/empty không grant authorize.
- **Gate NULL/legacy/global-read matrix (behavioral):** mọi tổ hợp (profile NULL/non-NULL) × (ks NULL/empty/list/legacy) qua global/default/local/grant reads.
- Test RED-first + DEF-028 regression giữ.

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