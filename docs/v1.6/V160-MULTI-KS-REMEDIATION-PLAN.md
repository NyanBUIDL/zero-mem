# V1.6.0 REMEDIATION PLAN — Multi-KS + capture wiring (DEF-034)

**Trạng thái:** PLAN (chưa thực thi — cần maintainer approve ADR-V160-01 + Gate riêng)
**Nguyên tắc:** không migration trong V1.5.1; canonical append-only; derived rebuildable; RED-first; commit nhỏ.
**Phạm vi:** commit evidence DEF-034 KHÔNG đổi production code; plan này là kế hoạch cho V1.6.0.

## Các commit đề xuất (nhỏ, tuần tự)

### C1 — Capture contract: canonical knowledge_space_ids (forward-only)
- `src/capture/validation.py`: thêm `knowledge_space_ids` vào OPTIONAL_FIELDS + validate (list[str] non-empty, dedup, max len).
- `src/capture/adapter.py`: param `knowledge_space_ids` + đưa vào envelope.
- `src/integration/capture_adapter.py`: `_envelope` truyền ks từ mapped payload.
- Test: envelope có list; validate reject non-list/dup/quá dài; **E2E _envelope → canonical → ingest** (behavioral).

### C2 — Ingest denormalize: zm_event_spaces junction + PRIMARY-KS (migration additive)
- Migration vN: `CREATE TABLE zm_event_spaces(event_id, knowledge_space_id, PRIMARY KEY(...))` + index; backfill từ `zm_meta.knowledge_space_id`.
- `src/storage/ingest.py`: parse canonical `knowledge_space_ids` (ưu tiên) / legacy singular; INSERT junction; `zm_meta.knowledge_space_id` = PRIMARY-KS (first của list, NULL nếu rỗng).
- Test RED-first: canonical multi-KS → junction 2 rows + zm_meta primary; legacy singular → 1 row; NULL/empty → 0 rows.

### C3 — Rebuild/replay: junction rebuild từ canonical
- Recovery/rebuild re-ingest canonical → junction tái tạo (không backfill từ derived).
- Test: rebuild sau khi xóa derived → junction == ban đầu (behavioral, không inspect).

### C4 — Authorization: union read + per-row grant qua junction
- `src/access/authorized_read.py`: `_ks_predicate` → junction join; `_scope_allows` nhận row's set ks.
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
| Authorization junction join chậm | Thấp | Index; SPIKE-B đo 2.5µs point-lookup |
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