# v1.3.0 — Kiến trúc

> Kiến trúc nền tảng theo `docs/architecture/ARCHITECTURE.md` (M0+) và `docs/v1.2.4/ARCHITECTURE.md`;
> ở đây chỉ ghi quyết định RIÊNG của v1.3.

## Component topology
Giữ nguyên topology v1.2.4 (capture → JSONL canonical → derived SQLite (zm_meta/zm_fts/scopes/temporal) → retrieval/M7 EvidenceSet → Hermes). Thay đổi v1.3:

- `zm_meta` +1 cột `knowledge_space_id` (migration 11, additive, index) — chiều scope thứ 4 trên event row, đồng bộ với corpus/graph/access.
- `search_text`/query thêm ks exact-filter qua `_build_where` dùng chung; FTS OR-fallback tầng retrieval (không index mới).
- M7 eligibility nhận `route` để promotion active-state trong PROJECT route (role-split layer, không budget change).
- EvidenceSet + field annotation `temporal` (M8.4 read_temporal, authorization-first, bounded ≤20).

## Ownership boundaries
| Component | Owner | State authority |
|---|---|---|
| zm_meta schema | storage/migrations | Derived từ JSONL canonical |
| FTS query strategy | src/retrieval/search.py | Read-only over zm_fts |
| Eligibility/promotion | src/integration/m7 | Deterministic metadata, zero-LLM |
| Temporal annotation | src/m8/temporal_read (M5 authorize) | Derived zm_temporal_index |

## Interaction protocols
| Boundary | Protocol | Quyết định |
|---|---|---|
| search ↔ cursor | fingerprint bao gồm match_mode + filters | Cursor chéo chế độ bị từ chối (versioned, không shim) |
| eligibility ↔ builder | route truyền tường minh, default None | Non-PROJECT byte-giống cũ |
| EvidenceSet ↔ temporal | fail-open annotation sau validated set | Không đổi selection/budget |

## State and failure semantics
CURRENT/STALE/UNAVAILABLE/DENIED/EMPTY giữ nguyên chuẩn v1.2.4. Bổ sung: STALE giờ visible qua temporal annotation (không bị lọc mất); OR-fallback là EMPTY→broaden trong cùng contract, vẫn trả typed result.

## Quyết định kiến trúc version này
- Không ADR mới cần thiết: mọi quyết định nằm trong `plans/DECISIONS.md` D-01..03 và đúng khung invariant AGENTS.md/ADR-009 (xem MASTER-SPEC-RECONCILIATION.md).
- P1 findings xử lý: FTS-AND fallback (V130-01), state-as-primary (V130-03), knowledge-space filter (V130-02), temporal read integration (V130-04); benchmark scale (V130-05).
