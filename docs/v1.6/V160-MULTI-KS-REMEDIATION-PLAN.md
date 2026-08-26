# V1.6.0 REMEDIATION PLAN — Multi-KS + capture wiring (DEF-034)

**Trạng thái:** PLAN (chưa thực thi — cần maintainer approve ADR-V160-01 + Gate riêng)
**Nguyên tắc:** không migration trong V1.5.1; canonical append-only; derived rebuildable; RED-first; commit nhỏ.

## Các commit đề xuất (nhỏ, tuần tự)

### C1 — Capture contract: canonical knowledge_space_ids (forward-only)
- `src/capture/validation.py`: thêm `knowledge_space_ids` vào OPTIONAL_FIELDS + validate (list[str] non-empty, dedup, max len).
NaN
NaN
NaN

### C2 — Ingest denormalize: zm_event_spaces junction (migration additive)
NaN
NaN
NaN

### C3 — Rebuild/replay: junction rebuild từ canonical
NaN
NaN

### C4 — Authorization: union read + per-row grant qua junction
NaN
NaN
NaN
NaN

### C5 — FTS parity: candidate SQL qua junction
NaN
NaN

### C6 — Graph/temporal: primary-KS hoặc junction
NaN
NaN

### C7 — Projection: render knowledge_spaces từ event
NaN
NaN

### C8 — Corpus: giữ singular, document
NaN

### C9 — Downstream surface parity (review-required): list_knowledge_space / M8 graph / projection
- relations.py list_knowledge_space: trả rows từ junction (bỏ hardcode [] — docstring M2 schema đã cũ).
- m8/graph_sources.py: event-derived nodes mang ks (bỏ knowledge_space_id=None).
- projection/render.py: render knowledge_spaces từ event ks (bỏ hardcode v9).
- Test: probes K/L/M chuyển từ 'pin hiện trạng' sang assert mới.

### C10 — Backward compat + acceptance + release gates
NaN
NaN
NaN
NaN

## Risk matrix
| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Migration additive vỡ derived cũ | Thấp | Additive + rebuild test; rollback drop table |
| Authorization junction join chậm | Thấp | Index; SPIKE-B đo 2.5µs point-lookup |
| Capture contract mở rộng vỡ writer cũ | Thấp | OPTIONAL (forward-only); canonical cũ vẫn validate |
| UNION semantics sai kỳ vọng | Trung bình | ADR chốt trước; acceptance test rõ |
| FTS/structured parity lệch (lặp DEF-020) | Trung bình | Cùng junction predicate cho cả 2 path; test parity |
| Projection thay đổi output (vỡ snapshot test) | Thấp | Update fixtures chủ động; document breaking |

## Rollback plan
- Migration: additive → downgrade = DROP `zm_event_spaces` (derived, rebuildable); `zm_meta.knowledge_space_id` giữ nguyên.
- Capture contract: forward-only — canonical cũ không cần rollback; writer cũ vẫn chạy (không set list).
- Auth/FTS: revert code (junction → singular) — schema giữ; rebuild derived.
- Không bao giờ xóa canonical hay rewrite lịch sử.

## Gates V1.6.0
1. ADR-V160-01 ACCEPTED (maintainer).
2. C1-C9 mỗi commit: RED-first → focused → adjacent → full suite.
3. Acceptance multi-KS + legacy compat PASS.
4. Benchmark junction (1k/10k/100k) latency/memory.
5. Release gates: version bump, release notes, CI matrix, doctor/docs sync.