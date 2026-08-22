# P1-02 — Knowledge-space filter chưa enforced trên memory events

**Status:** PENDING USER REVIEW (Gate A)
**Date:** 2026-08-22
**Scope:** V130-02 (schema + enforce `search_text`).

## 1. Hiện trạng code chính xác

- `src/storage/migrations/migrate_1.py:12-37` — `zm_meta` **KHÔNG có cột** `knowledge_space_id`. 23 cột hiện tại liệt kê trong `ZM_META_COLUMNS` (`src/storage/ingest.py:43-49`) — cũng không có ks.
- `src/storage/ingest.py:270-282` — khi ingest, `knowledge_space_id` từ envelope chỉ ghi vào bảng quan sát `zm_scopes` (scope_type='knowledge_space'); **không lưu liên kết event-level**.
- `src/retrieval/search.py:94-176` — `search_text` không nhận/thực thi ks filter. `_EQUAL_FILTERS` (`src/retrieval/query.py:33-47`) không chứa ks → query structured cũng không lọc theo ks được.
- `src/retrieval/relations.py:15-16, 251-267` — `list_knowledge_space()` trả `[]` cố ý: schema-truthful, không có cột event-level.
- Ngược lại, phía corpus (migrate_10) và graph/temporal (migrate_9) ĐÃ có `knowledge_space_id` trên từng row (`zm_corpus_units`, `zm_graph_nodes`, `zm_temporal_index`) và authorization scope đã hỗ trợ ks (`src/corpus/retrieval.py:59-85`, `migrate_8.py:41`). Nghĩa là: **memory events là lỗ hổng enforce duy nhất còn lại.**

## 2. Root cause

Schema M2 (zm_meta) ra đời trước khi ks trở thành chiều authorization; envelope có `knowledge_space_id` nhưng projector chỉ ghi quan sát zm_scopes, không denormalize xuống event row. Hệ quả: FTS search và structured query trên memory events không thể giới hạn theo knowledge space → vi phạm tinh thần "reads are profile-first and evidence-bounded" (AGENTS.md) ở một trục scope.

## 3. Phương án thiết kế (open question 1)

### Option A — Cột đơn `knowledge_space_id TEXT` trên `zm_meta` (khuyến nghị)
Migration 11 additive: `ALTER TABLE zm_meta ADD COLUMN knowledge_space_id TEXT` + index `(knowledge_space_id)`. Ingest điền từ envelope. Query/search thêm exact-equality filter (NULL = unscoped; filter ks chỉ match NULL khi caller yêu cầu tường minh hoặc policy quyết định).
- Ưu: query WHERE đơn giản, indexable, khớp mô hình corpus/graph đang dùng (cũng là cột đơn), rebuild từ JSONL được (envelope giữ ks).
- Nhược: chỉ 1 ks/event (đủ với mô hình scope hiện tại — mọi chỗ khác đều single-value).

### Option B — Multi-value set trong `zm_meta` (bảng nối `zm_event_ks(event_id, ks_id)` hoặc JSON column)
- Ưu: 1 event thuộc nhiều ks.
- Nhược: schema mới + join mỗi query; FTS search phải subquery/EXISTS (chậm hơn); không có chỗ nào trong hệ thống hiện tại dùng multi-ks; tăng phức tạp migration + rebuild.

| Tiêu chí | A (cột đơn) | B (multi-value) |
|---|---|---|
| Storage | +1 col/index | +1 bảng + rows |
| Runtime search | WHERE trực tiếp, indexed | EXISTS/join |
| Rebuildable từ canonical | có (envelope có ks) | có nhưng phức tạp hơn |
| Khớp phần còn lại của hệ thống | đúng bằng | lệch |
| Reversibility | cao (drop column) | trung bình |

## 4. Khuyến nghị

**Option A — cột đơn trong `zm_meta`.** Toàn hệ thống (corpus, graph, temporal, access CHECK constraint migrate_8) đều single-value ks; multi-value là phát minh yêu cầu không có nguồn (vi phạm §B.4 checklist).

## 5. Schema / migration impact

- Migration 11 (additive): ALTER TABLE + CREATE INDEX + backfill.
- Backfill: từ canonical JSONL replay (envelope.knowledge_space_id) qua đường rebuild hiện có `src/storage/canonical_replay.py` / recovery — derived state nên bắt buộc rebuildable; test migration phải chứng minh rebuild tái tạo đúng cột.
- `ZM_META_COLUMNS` mở rộng → mọi SELECT build từ list này tự thấy; kiểm tra cursor fingerprint có bind ks filter mới hay không (phải bind để pagination an toàn).
- Migration test: v1 DB cũ → up 11 → query ks; down 11 → về trạng thái trước (drop column).

## 6. Rủi ro

- Event cũ ingest trước khi envelope có ks → NULL. Cần chính sách tường minh trong spec: NULL nghĩa "unscoped"; authorization layer quyết định NULL hiển thị cho route nào (giữ hành vi global-default-read của AGENTS.md, KHÔNG tự siết thành deny-by-default — đó sẽ là thay đổi behavior ngoài finding này; nếu cần thì NEEDS DECISION riêng).
- Fingerprint cursor phải bao gồm ks filter tránh leak across pages.
- Enforce trong `search_text` phải đi qua parameterized WHERE như các filter khác — không concat string.

## 7. Test plan dự thảo

1. Migration: fresh DB có cột; DB version 10 → up 11 OK; down OK; ledger ghi version.
2. Ingest event có envelope.knowledge_space_id → zm_meta.knowledge_space_id đúng; thiếu ks → NULL.
3. Rebuild từ JSONL → cột tái tạo giống hệt (byte-compare query result).
4. `search_text(..., req=QueryRequest(knowledge_space_id="ks-a"))`: chỉ hit event thuộc ks-a; event ks-b/không-hit bị loại cả khi MATCH khớp.
5. Structured query `_EQUAL_FILTERS` nhận ks; unknown value vẫn fail closed như cũ.
6. Cursor pagination với ks filter: không leak event ngoài ks giữa trang.
7. Regression full suite ≥ baseline.

## 8. Gate criteria

- G0 contract: tên cột, semantics NULL, vị trí trong ZM_META_COLUMNS chốt trước code.
- G1/G2 như checklist C5/C6; security/redaction test vì chạm ingest path (ks không phải content — vẫn chạy suite redaction chuẩn).

## 9. Rollback plan

Down-migration 11 (drop index + drop column). Derived-only → rollback không đụng JSONL canonical.

## 10. Migration plan

Additive migration 11, đăng ký trong migrations runner, note ledger, test upgrade path từ DB v10 thật (fixture dựng DB cũ rồi migrate).
