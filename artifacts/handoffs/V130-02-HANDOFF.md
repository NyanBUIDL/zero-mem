# V130-02 HANDOFF — Knowledge-space filter (zm_meta.knowledge_space_id)

**WP:** V130-02 | **Commit:** `cdada94` | **Branch:** `release/v1.3.0` | **Date:** 2026-08-22
**Status:** IMPLEMENTED + FULL SUITE XANH — chờ Verifier audit

## Changed paths (core)
- `src/storage/migrations/migrate_11.py` (MỚI) — ALTER TABLE zm_meta ADD COLUMN knowledge_space_id TEXT + idx_zm_meta_ks; down drop cả hai; idempotent; fail-closed nếu SQLite < 3.35.
- `src/storage/migrations/__init__.py` — đăng ký migration 11 (CURRENT_SCHEMA_VERSION = 11).
- `src/storage/ingest.py` — `ZM_META_COLUMNS` + ks; `_project_row` điền `env.get("knowledge_space_id")`.
- `src/retrieval/models.py` — `QueryRequest.knowledge_space_id` (exact-equality).
- `src/retrieval/query.py` — `_EQUAL_FILTERS` + ks (enforce qua `_build_where` dùng chung cho query + search_text).
- `src/m8/*` + `src/integration/m7/m8_integration.py` — M8_SCHEMA_VERSION / describe() literals 10 → 11 (theo precedent a861ff0).
- 36 test files — schema-version assertions 10 → 11 (precedent: a861ff0 "bump schema-version assertions").
- `tests/unit/test_v130_02_ks_filter.py` (MỚI) — 8 contract tests.

## Data flow
Envelope `knowledge_space_id` → `_project_row` → `zm_meta.knowledge_space_id` (NULL = unscoped) → `_build_where` exact-equality khi `QueryRequest.knowledge_space_id` set → áp cho cả `query_events` lẫn `search_text`. Cursor fingerprint tự bao gồm ks filter vì `make_fingerprint` hash `req.to_dict()` (R3 thỏa từ đầu — bài học match_mode không lặp lại).

## R1 — Rebuildability (gate lớn nhất)
`test_rebuild_recreates_ks_column`: rebuild_from_jsonl từ canonical JSONL tái tạo đúng cột (ks-a/ks-b/NULL). JSONL canonical không đổi.

## R2 — NULL-ks policy (D-2026-08-22-03)
- `test_unfiltered_search_shows_null_ks_events`: NULL visible khi không filter ✓
- `test_search_with_ks_filter_excludes_other_and_null`: NULL bị loại khi filter ks ✓
- `test_no_leak_between_ks_scopes`: ks-a không leak ks-b ✓

## R3 — Cursor fingerprint
ks filter nằm trong `req.to_dict()` → có trong fingerprint từ đầu. Test pagination leak xuyên trang nằm trong test khung (C6 full suite xanh).

## Evidence
- RED trước implement: 7 failed / 1 passed.
- GREEN: 8/8 unit mới.
- Full suite run2: **3396 passed / 5 skipped / 0 failed** ≥ baseline — `zero-mem-dev-data/evidence/v130-wp02-full-suite-run2.log`.
- C7: stash migration+ingest+retrieval → 7 failed; restore → 8 passed.
- Schema-version bump: 157 test fail ban đầu (assertions ==10) → bump theo precedent a861ff0 (m10.4 đã làm y hệt khi migrate_10 vào) → xanh. KHÔNG có assertion bị xóa/weaken — chỉ literal 10→11.
- Graphify post: `zero-mem-dev-data/graphify/v130/wp02-post`.

## Risks
- Migration down yêu cầu SQLite ≥ 3.35 (DROP COLUMN) — fail closed với thông điệp rõ; up không có yêu cầu này.
- 52 files trong 1 commit — phần lớn là schema-version literal bump máy móc; core diff nhỏ (migrate_11 + ingest + retrieval).

## Next integration
- V130-04 (temporal→EvidenceSet) dùng ks cho authorization seed.
- V130-05 benchmark: case ks-leak (query ks-a phải 0 hit ks-b).
