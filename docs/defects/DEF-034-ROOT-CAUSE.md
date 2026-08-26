# DEF-034 — ROOT CAUSE REPORT (revised theo review 2026-08-25)

**Ngày:** 2026-08-25 · **Branch:** remediation/v151-audit (v1.5.1 candidate; reviewer checkout v1.5.0 — line refs khác).
**Verdict (thu hẹp):** **CONFIRMED — standard capture adapters không truyền KS vào top-level canonical envelope.**
**Chưa đủ bằng chứng cho:** toàn bộ capture boundary không thể lưu KS; chỉ mất tại capture; không có security impact.

## 1. Điểm lỗi chính xác: ENVELOPE CONSTRUCTION trong standard adapters

| Adapter | Bằng chứng |
|---|---|
| `src/capture/adapter.py:41-74` `normalize_event` | Signature chỉ nhận `profile_id`/`project_id` (không ks); envelope dict cố định không ks. **KS truyền qua payload bị chuyển vào `sanitized_content.extra`** (probe H: top-level False, extra True). |
| `src/integration/capture_adapter.py:58-98` `_envelope` (Hermes production adapter) | Whitelist dict cố định (line 82 `profile_id` v.v.) — **không có `knowledge_space_id`**; KS trong sanitized payload bị bỏ. |
| `src/capture/validation.py:18-46` | `knowledge_space_id` không trong REQUIRED/OPTIONAL_FIELDS; **không reject unknown fields** (line 69+) → manual top-level ks vẫn validate được. |
| `src/storage/jsonl_capture.py:164-179` | `validate_envelope` + `dict(event)` nguyên vẹn — **KHÔNG drop** field lạ. Probe I: manual top-level `ks-manual` trước append → canonical GIỮ nguyên → ingest denormalize thành `zm_meta.knowledge_space_id = 'ks-manual'`. |

**Kết luận:** capture STORE/boundary không phải điểm mất; mất tại **envelope construction** của standard adapters. Caller có thể tự thêm top-level ks vào envelope — hệ thống (validate/append/ingest) xử lý ĐÚNG.

## 2. Chuỗi thực tế (probes executable A-I)
| Probe | Kết quả |
|---|---|
| A. adapter envelope | `has knowledge_space_id: False` |
| B. canonical (capture thật) | `has knowledge_space_id: False` |
| C. ingest captured | `zm_meta.knowledge_space_id: None` (dù profile/project set) |
| D. hand-crafted ks envelope | ingest denormalize `{ev-ks: quant-theory, ev-null: None}` |
| E. FTS SearchHit | mang ks từ zm_meta (khi có dữ liệu) |
| F. space-grant auth | trả `[ev-ks]`; NULL row deny fail-closed |
| G. rebuild | faithful (v1 == v2) |
| H. KS via payload | → `sanitized_content.extra`, KHÔNG top-level |
| I. manual top-level ks | canonical giữ + ingest denormalize ĐÚNG |

## 3. Security: thay 'không phải security defect' bằng 'no leak observed in tested paths'

Probe J (global read + NULL profile):
- Row `profile_id=None, ks=NULL` (intended 'secret-ks' bị drop): **visible** dưới global read (stranger + include_global).
- Row `profile_id=None, ks='secret-ks'` (ks giữ): **visible** dưới global read — vì global read cho NULL-profile rows **bỏ qua ks** (D-2026-08-22-03: NULL-profile = unowned/default scope, visible dưới global; global branch trả True cho NULL-profile).
⇒ **KS loss KHÔNG mở rộng exposure global read** (cả hai visible theo design). KS loss chỉ GỠ kênh space-grant authorization (fail-closed deny) — feature gap, không phải leak mới.

**Tuyên bố an toàn:** *no leak observed in tested paths (global/local/grant). KS loss removes the space-grant authorization channel for the row; it does not add new exposure in tested paths.* Chưa probe hết mọi tổ hợp profile/ks — cần gate NULL/legacy/global-read trong V1.6.0.

## 4. 'Chỉ mất tại capture' KHÔNG đúng toàn hệ thống — downstream feature gaps riêng
| Surface | Trạng thái | Bằng chứng |
|---|---|---|
| `list_knowledge_space` (relations.py:251-270) | **Luôn trả rỗng** dù event có ks — docstring: 'NO event-level linkage column in the verified M2 schema' | Probe K: `items: 0, total: 0` với event ks='quant-theory' |
| M8 graph sources | **Gán `knowledge_space_id=None`** cho event-derived nodes | Probe L: 4 occurrences; `graph_sources.py:125` comment 'zm_meta carries no knowledge_space_id column' (SAI — migrate v11 đã thêm) |
| Projection (Obsidian) | **Hardcoded `knowledge_spaces: []`** | `render.py:516-519` (comment v9 chủ đích) |

## 5. Doc-code conflicts (đã ghi nhận)
1. `migrate_11.py:4`: 'canonical JSONL events already carry knowledge_space_id' — SAI cho capture path.
2. `graph_sources.py:125`: 'zm_meta carries no knowledge_space_id column' — LỖI THỜI (v11 đã thêm).
3. SPIKE-B: 'zm_meta chưa có cột ks' — LỖI THỜI.
4. Roadmap `ZERO-MEM-v1.5.1-REMEDIATION-ROADMAP.vi.md` — TỒN TẠI tại OneDrive workspace (bản trước nói thiếu là SAI).
5. `search.py:120` — trong clone v1.5.1 map `knowledge_space_id=row[...]` (DEF-020); checkout v1.5.0 khác.

## 6. Probes (lưu trong repo để review được)
- `tests/unit/test_v151_audit_def034_lifecycle.py` (A-I + security J) — committed.
- `tests/unit/test_v151_audit_def034_downstream.py` (K/L/M) — committed.