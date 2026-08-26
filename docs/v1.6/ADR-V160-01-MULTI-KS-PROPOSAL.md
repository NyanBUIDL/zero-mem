# ADR-V160-01 (ĐỀ XUẤT) — Multi-Knowledge-Space per event + capture wiring

**Trạng thái:** PROPOSED (chưa ACCEPTED — cần maintainer duyệt trước V1.6.0 code)
**Liên quan:** DEF-034 (OPEN → V1.6.0), master spec §4.3 (trace thuộc nhiều KS), SPIKE-B (B-schema khả thi), DEF-028 (per-row auth base).
**Nguồn bằng chứng:** `audit/DEF-034-ROOT-CAUSE.md` (probes executable A-G).

## Context
Hệ thống hiện tại: (1) capture không sinh knowledge_space_id (probe A/B); (2) schema SINGULAR `zm_meta.knowledge_space_id` (migrate_11); (3) master spec yêu cầu một trace thuộc NHIỀU KS; (4) projection hardcoded empty; (5) authorization per-row chỉ xử lý 1 ks/event.

## Decision (đề xuất)

### 1. Một event thuộc MỘT hay NHIỀU KS?
**NHIỀU KS** (theo master spec §4.3). Canonical mang `knowledge_space_ids: []` (list, có thể rỗng).

### 2. Semantics NULL / empty list / legacy knowledge_space_id
| Giá trị | Semantics đề xuất |
|---|---|
| `knowledge_space_ids: []` (mới, rỗng) | UNKNOWN/unscoped — không authorize bởi bất kỳ space grant nào; thấy được trong global/default read (D-2026-08-22-03 giữ nguyên) |
| `knowledge_space_ids: [A]` | thuộc A |
| `knowledge_space_ids: [A, B]` | thuộc CẢ A VÀ B (union cho READ scope filter; xem §7) |
| legacy `knowledge_space_id: "A"` (canonical cũ) | Đọc tương đương `knowledge_space_ids: [A]`; ưu tiên list khi cả hai tồn tại; list rỗng + legacy set → dùng legacy (tương thích ngược) |
| NULL (canonical không có field) | unscoped (như cũ) |

### 3. Canonical envelope
- Bổ sung `knowledge_space_ids: List[str]` vào capture contract (OPTIONAL_FIELDS + adapter param `knowledge_space_ids`).
NaN

### 4. Derived: `zm_event_spaces` junction table
- `zm_event_spaces(event_id TEXT, knowledge_space_id TEXT, PRIMARY KEY(event_id, knowledge_space_id))` + index theo ks.
NaN
NaN

### 5. Migration additive + rollback
- Migration vN (additive): tạo `zm_event_spaces`; backfill từ `zm_meta.knowledge_space_id` (legacy) — events cũ có singular ks → junction 1 row; NULL → không row.
NaN

### 6. Capture wiring
- `normalize_event(..., knowledge_space_ids=...)` + validation (list-of-str, dedup, max len).
NaN
NaN

### 7. Authorization union/intersection
- **READ scope filter** với `knowledge_space_ids=[A,B]`: **UNION** (row thuộc A HOẶC B) — khớp profile_first/global composition hiện tại.
- **Space grant per-row:** row được phép nếu `granted ∩ row.knowledge_space_ids ≠ ∅`.
NaN
NaN

### 8. FTS/structured/graph/temporal/corpus parity
- Structured + FTS: candidate SQL dùng junction (parity bắt buộc — học từ DEF-020/028).
NaN
NaN
NaN

### 9. Backward compatibility
- Canonical cũ (không ks / singular ks) đọc được, rebuild không đổi.
NaN
NaN

### 10. Tests / acceptance / release gates
- RED-first: multi-KS ingest; junction rebuild; union/intersection auth; FTS parity; legacy compat; NULL/empty semantics.
- **Gate bổ sung theo review (2026-08-25) — bắt buộc trước khi đóng V1.6.0:**
  - **NULL/legacy/global-read matrix:** probe security cho mọi tổ hợp (profile NULL/non-NULL) × (ks NULL/empty/list/legacy) qua global/default/local/space-grant reads — khẳng định no-new-exposure (không chỉ no-leak-observed).
  - **Standard adapter E2E:** normalize_event + capture_adapter._envelope phải truyền ks qua canonical (test E2E từ Hermes payload → canonical → zm_meta/junction).
  - **list_knowledge_space parity:** API này không được trả rỗng khi junction/zm_meta có ks (fix relations layer).
  - **M8 graph parity:** event-derived nodes không được gán knowledge_space_id=None (fix graph_sources).
  - **Projection parity:** render knowledge_spaces từ event (bỏ hardcode []).
NaN
NaN

## Rejected alternatives
- Giữ SINGULAR + chỉ wiring capture (DEF-034 hẹp): không đáp ứng master spec §4.3; đẩy nợ multi-KS vô hạn.
NaN
NaN

## Consequences
- +1 migration (additive), +1 junction table (derived), capture contract mở rộng (forward-only).
NaN
NaN