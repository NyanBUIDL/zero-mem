# Zero-Mem v1.5.0 — Release Notes

**Ngày phát hành:** 2026-08-25 · **Dòng:** minor release (v1.4.1 → v1.5.0)

## Chủ đề: Canonical-first authorization + hardening

Cụm deferred defect về ủy quyền knowledge-space (DEF-009/010/011) được đóng
toàn bộ theo ADR-V150-01 (GATE-V150-1: "A + spike B-schema"). Sau bản này,
space grant trên event path authorize **đúng từng row** dựa trên
`zm_meta.knowledge_space_id` — derived trực tiếp từ canonical JSONL.

## Đóng defect

### DEF-009 — Registry O(n)/update + fingerprint field name (FIXED)
- `CorpusSourceRegistry._update_record` ghi lại file từ in-memory index:
  hết re-read toàn bộ JSONL mỗi update (O(1) amortized).
- Cursor fingerprint gán đúng `profile_id=profile_filter` (naming-only).

### DEF-010 — Space-grant coarsening (FIXED)
- Phát hiện then chốt: `zm_meta.knowledge_space_id` đã có từ migration v11
  (V130-02) và ingest denormalize sẵn → không cần schema mới.
- `_ks_predicate`: SQL `knowledge_space_id IN (...)` enforce per-row boundary.
- Grant space giờ cấp quyền đọc ĐÚNG các row mang ks đó; hết
  "grant space ≡ grant project".

### DEF-011 — Derived-state trong authorization (CLOSED)
- Bỏ hẳn resolution fallback: event path KHÔNG đọc corpus projection nữa.
- `_expand_scope_with_spaces` thành no-op (chính là kênh coarsening cũ).
- Row NULL-ks = unscoped (D-2026-08-22-03): không bao giờ được space grant
  authorize, bất kể projection nói gì.
- `projection_integrity.py` (digest gate fail-closed) giữ lại làm hạ tầng cho
  corpus path và feature tương lai.

## Cải tiến khác

- Test portability (DEF-017/018): benchmark test resolve corpus DB qua env
  `ZM_TEST_CORPUS_DB` + repo-relative fallback; hardening test bền với HOME absent.
- E2E acceptance mới: JSONL thật → ingest → `_open_facade` → grant → assert
  đúng tập row (pin cả 2 trap coarsening + NULL-ks).

## Lưu ý nâng cấp

- **Row legacy (NULL ks)** không còn được space grant authorize qua đường gián
  tiếp. Nếu cần space grant áp dụng: re-ingest envelope mới mang
  `knowledge_space_id`.
- Không schema migration; derived store rebuild bình thường.
- Owner vẫn đọc được row unscoped của chính mình (implicit-local không đổi).

## Chất lượng

- Full suite: **3535 passed / 12 skipped / 0 failed** (Py 3.13.15, isolated HOME).
- Regression riêng access/retrieval/integration: 1151 passed.
- Spike hiệu năng B-schema đo trên corpus thật (217k units): không blocker.

## Backlog đã biết

- Admin CLI đa-agent (ADR-V141-01 Option B) — tier enterprise.
- Digest-gate cache cho corpus scale lớn.
