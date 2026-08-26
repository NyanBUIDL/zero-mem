# ADR-V160-01 (ĐỀ XUẤT) — Multi-Knowledge-Space per event + capture wiring

**Trạng thái:** PROPOSED (chưa ACCEPTED — cần maintainer duyệt trước V1.6.0 code)
**Liên quan:** DEF-034 (OPEN → V1.6.0), master spec §4.3, SPIKE-B, DEF-028 (per-row auth base).
**Nguồn bằng chứng:** `docs/defects/DEF-034-ROOT-CAUSE.md` + probes `docs/v1.6/probes/` (A-J chạy exit 0).
**Ghi chú phạm vi:** commit evidence DEF-034 (37c33d6, f21758f) KHÔNG đổi production code; branch chứa các fix DEF-028/029/030/031/033 từ trước.

## Context
Hệ thống hiện tại: (1) standard capture adapters không sinh knowledge_space_id (probe A/B/H); (2) schema SINGULAR `zm_meta.knowledge_space_id` (migrate_11); (3) master spec yêu cầu trace thuộc NHIỀU KS; (4) projection hardcoded empty; (5) authorization per-row chỉ xử lý 1 ks/event; (6) `list_knowledge_space` trả rỗng; (7) M8 graph gán ks=None.

## Decision (đề xuất)

### 1. Event thuộc MỘT hay NHIỀU KS? — NHIỀU (per-event)
**Quyết định:** canonical mang `knowledge_space_ids: List[str]` **per event** (mỗi event có tập KS riêng, có thể rỗng).

### 1a. Trace vs event semantics (đóng quyết định)
- Canonical lưu KS **per event** (event là đơn vị capture).
- **Trace-level KS = UNION các KS của events trong trace** (derived, tính tại query/rebuild — không lưu thêm).
- Events trong cùng trace **KHÔNG bắt buộc cùng tập KS** (không thêm invariant; mỗi event độc lập).
- Master spec 'một trace thuộc nhiều KS' được thỏa bởi union derived.
- **Scope V1.6.0 (round-3):** trace-union là **semantic definition** (tính khi có surface đọc trace-scoped trong tương lai); **KHÔNG expose làm surface trong V1.6.0** — không có implementation commit, chỉ ghi định nghĩa + gate test nếu surface sau này thêm.

### 2. Semantics NULL / empty list / legacy knowledge_space_id
| Giá trị | Semantics |
|---|---|
| `knowledge_space_ids: []` (mới, rỗng) | UNKNOWN/unscoped — không authorize bởi space grant nào. **Chính xác:** KS không THÊM hạn chế, nhưng visibility vẫn do profile/project/global policy quyết định (row NULL-profile vẫn visible dưới global read theo D-2026-08-22-03; row có profile thì theo profile match). |
| `knowledge_space_ids: [A]` | thuộc A |
| `knowledge_space_ids: [A, B]` | thuộc CẢ A VÀ B; READ scope filter = UNION (xem §7) |
| legacy `knowledge_space_id: A` | tương đương `knowledge_space_ids: [A]`; list thắng khi cả hai; list rỗng + legacy set → dùng legacy |
| NULL (canonical không có field) | unscoped (như cũ) |

### 3. Canonical envelope
- Capture contract: thêm `knowledge_space_ids` (OPTIONAL_FIELDS + adapter params `knowledge_space_ids`).
- Standard adapters (`normalize_event` + `capture_adapter._envelope`) PHẢI truyền ks (fix gốc DEF-034).

### 4. Derived: `zm_event_spaces` junction + `zm_meta.knowledge_space_id` = PRIMARY-KS
**Quyết định (đóng):**
- **Junction `zm_event_spaces(event_id, knowledge_space_id)` = nguồn dẫn xuất CHÍNH cho multi-KS** (auth + FTS + structured query dùng junction).
- **PRIMARY-KS reconstruction (round-3):** junction KHÔNG lưu thứ tự (chỉ (event_id, ks)) nên KHÔNG thể rebuild primary từ junction. **Cả junction LẪN `zm_meta.knowledge_space_id` (PRIMARY-KS) đều là projection TRỰC TIẾP từ canonical tại ingest** (primary = phần tử đầu tiên theo thứ tự canonical); rebuild re-ingest canonical → cả hai tái tạo faithful. KHÔNG cần thêm `ordinal` vào junction (không có query cần thứ tự); nếu sau này cần thứ tự → migration additive riêng.
- `zm_meta.knowledge_space_id` GIỮ NGUYÊN = denormalized PRIMARY-KS — convenience projection cho backward compat + graph/temporal; **KHÔNG phải source of truth**; mọi query/read hiện tại không vỡ.

### 5. Migration additive + rollback
- Migration vN (additive): `CREATE TABLE zm_event_spaces(...)` + index; backfill từ `zm_meta.knowledge_space_id` (legacy singular → 1 row; NULL → 0 row).
- Rollback: DROP table (derived, rebuildable); canonical không đụng; capture contract forward-only (canonical cũ vẫn đọc được).

### 6. Capture wiring
- `normalize_event(..., knowledge_space_ids=...)` + validation (list[str] dedup, max len).
- `capture_adapter._envelope` truyền ks từ mapped payload.
- Hermes bridge / PublicClient / runtime: ks từ config/bridge tường minh (không infer — ADR-M1-006).
- Test E2E: Hermes payload → canonical → ingest → junction (gate bắt buộc).

### 7. Authorization union/intersection
- READ scope filter `knowledge_space_ids=[A,B]` = **UNION**. Space grant per-row: `granted ∩ row.knowledge_space_ids ≠ ∅`.
- **Chống duplicate (round-3):** junction được dùng qua **correlated EXISTS subquery**, KHÔNG dùng JOIN trực tiếp (event [A,B] + UNION [A,B] match 2 junction rows → JOIN nhân đôi):
  ```sql
  EXISTS (SELECT 1 FROM zm_event_spaces s WHERE s.event_id = zm_meta.event_id AND s.knowledge_space_id IN (...))
  ```
- Acceptance bắt buộc: event [A,B] xuất hiện ĐÚNG 1 lần; pagination không skip/lặp giữa các trang; cursor fingerprint bind toàn bộ KS filter đã canonicalize (sort + dedup).
- `_ks_predicate` chuyển sang junction join; NULL/empty không bao giờ space-grant authorize (giữ).
- Matrix NULL/legacy/global-read là gate bắt buộc (không chỉ no-leak-observed).

### 8. Parity: FTS/structured/graph/temporal/corpus
- **FTS + structured:** cùng junction predicate (học DEF-020/028).
- **Graph/temporal (m8): dùng `zm_meta.knowledge_space_id` (PRIMARY-KS)** — đơn giản, không junction (quyết định C6: primary-KS).
- **Limitation (round-3, fail-closed tradeoff):** event [A,B] chỉ hiện dưới graph/temporal scope của PRIMARY-KS (A); space grant B đọc được event qua structured/FTS nhưng **có thể không đọc được graph-derived representation** — tradeoff chủ đích (fail-closed, không leak); gate test bắt buộc: grant B → event readable qua structured, graph representation gated bởi primary (behavioral).
- Corpus: units giữ singular (1 KS/unit) — KHÔNG chuyển multi-KS (chưa đủ evidence).
- Projection: render `knowledge_spaces` từ event ks (bỏ hardcode v9).
- `list_knowledge_space`: trả rows từ junction (bỏ hardcode []).

### 9. Backward compatibility
- Canonical cũ đọc được; rebuild không đổi; `zm_meta.knowledge_space_id` giữ (primary-KS).
- `knowledge_space_ids` OPTIONAL — capture cũ không set → empty → unscoped như cũ.

### 10. Tests / acceptance / release gates
- RED-first: multi-KS ingest; junction rebuild; union/intersection auth; FTS parity; legacy compat; NULL/empty semantics.
- **Gate bổ sung (review 2026-08-25):** NULL/legacy/global-read matrix (behavioral, không inspect source); standard-adapter E2E (`_envelope` + `normalize_event`); `list_knowledge_space` behavioral; M8 graph behavioral; projection behavioral.
- Acceptance: 1 event 2 KS — structured + FTS + grant(A) + grant(B) trả row; grant(C) không; legacy singular vẫn hoạt động.
- Release: full suite + benchmark junction point-lookup + migration upgrade/rollback.

## Rejected alternatives
- Giữ SINGULAR + chỉ wiring capture: không đáp ứng master spec §4.3.
- JSON array trong zm_meta: khó query/index; phá per-row auth.
- Bảng thay thế zm_meta.ks hoàn toàn: vỡ backward compat.

## Consequences
- +1 migration additive, +1 junction (derived), capture contract forward-only.
- Auth/FTS phức tạp hơn (junction join) nhưng fail-closed.
- Projection + list_knowledge_space cải thiện.