# V140-02 HANDOFF — DEF-004 Knowledge-Space Resolution (Option B)

- **WP:** V140-02 (v1.4.0) — DEF-004 fix, phương án B (resolution layer)
- **Ngày:** 2026-08-24 · **Repo:** zero-mem-v123-engineering @ `aba47b0` (master, local)
- **Authorization:** GATE-0/1/2 approvals (user paste). GATE-2 CHỌN B (no zm_meta schema change).
- **Phases:** SCOUT (Graphify) → ADR draft → Implement (RED-first) → Full suite → Verifier (bg) → SCRIBE/GATE-2b

## Observed (SCOUT)

Graphify code-only (8719 nodes, moved to `zero-mem-dev-data/graphify/graphify-zero-mem-v140-02`):
- `_scope_allows` (`authorized_read.py:176-179`) là nút thắt — space-grant → `return False` vì `zm_meta` thiếu cột `knowledge_space_id`.
- `zm_meta` DDL (`migrate_1.py:12`) KHÔNG có ks col; `migrate_13` KHÔNG tồn tại.
- **Phát hiện then chốt:** corpus path (`corpus_unit_search` → `AuthorizedCorpusScope`) ĐÃ hoạt động với ks (zm_corpus_units có col ks). DEF-004 chỉ ảnh hưởng **event-store path**.
- `grants.py` đã resolve space-grant vào `allowed_knowledge_space_ids` (sẵn sàng, chỉ thiếu resolve tại row-check).

## Changed (commits local, KHÔNG push)

1. `5a99ce4` — SCOUT impact-set + ADR draft (A vs B).
2. `a5e0fde` — **Implement Option B**:
   - `src/access/knowledge_space_resolver.py` (mới): `resolve_space_members(conn, space_ids)` → DISTINCT (profile_id, project_id) từ `zm_corpus_sources` UNION `zm_corpus_units` WHERE ks IN (...). Pure, derived/rebuildable.
   - `src/access/authorized_read.py`:
     - `_scope_allows(..., space_members=None)`: space-branch trả True CHỈ KHI (profile,project) in space_members; None → fail-closed.
     - `AuthorizedReadService.__init__(..., corpus_conn=None)`: optional corpus DB conn.
     - `_expand_scope_with_spaces(scope)`: merge resolved members vào scope's profile/project dims (mọi read path dùng predicate cũ → authorize space-owned rows, no schema change).
     - 6 caller `_scope_allows` + facade `search_text` project-resolution sửa để ưu tiên scope (fix bug lấy project từ request thay vì scope).
   - `tests/unit/test_v140_02_ks_resolution.py` (mới, 9 tests): resolver + `_scope_allows` + facade expand, RED→GREEN.
3. `aba47b0` — DEF-004 → FIXED (Option B), CHECKLIST V140-02 ticked.

**KHÔNG có migrate_13** — zm_meta schema UNCHANGED (tuân thủ GATE-2 B).

## Verified

- `test_v140_02_ks_resolution.py`: **9 passed** (resolver maps space→members; space-member event authorized; non-member denied; no-resolver fail-closed; legacy call fail-closed; facade expand merges + fail-closed khi không có corpus_conn).
- Full suite (isolated HOME, Py 3.13.15): **3412 passed, 7 skipped, 0 failed** — không regression.
- Verifier độc lập (deleg_faf272b3) đang chạy → OVERALL chờ.

## Risk / Notes

- Resolution layer phụ thuộc derived corpus state: nếu corpus DB chưa build, space-grant → fail-closed (by design, an toàn).
- Facade fix `search_text` project-resolution là bug nhỏ đi cùng (lấy từ scope thay vì request) — đã cover bởi test B.
- Token cost thấp (1 module + 1 param + facade expand), rủi ro thấp (no migration).

## Next (GATE-2b)

- Chờ Verifier OVERALL PASS → maintainer duyệt GATE-2b → V140-03 (MCP adapter + POC client ngoài Hermes).
- **DỪNG tại GATE-2b** — không tự chuyển V140-03.

## Authorization

Local-only, chưa push. 3 commits (5a99ce4, a5e0fde, aba47b0) chờ GATE-2b + release duyệt.
