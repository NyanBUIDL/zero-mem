# V140-03 HANDOFF — MCP adapter + import tool + non-Hermes POC

- **WP:** V140-03 (v1.4.0) · **Ngày:** 2026-08-24 · **Repo:** zero-mem-v123-engineering @ `635769d` (master, local)
- **Authorization:** GATE-0/1/2/2b approvals. GATE-2b APPROVED V140-03 proceed.
- **Phases:** SCOUT M6 survey → MCP server (reuse dispatcher) → Import CLI → POC client (verifier ngoài) → GATE-3.

## Observed (SCOUT)

M6 stack (src/integration/m6/):
- `contracts.py` (M6.1), `dispatcher.py` (transport-independent, READ-only by construction), `mcp_wrapper.py` (thin transport adapter), `handlers.py` (M6.2/M6.3 wired qua AuthorizedReadService), `runtime.py` (TRUE READ-ONLY store + grant conn).
- M6 surface query **event store** (zm_meta). quant_lab corpus ingest tạo **corpus units** (zm_corpus_units) — separate knowledge base. POC "query knowledge base" cần tool đọc corpus units.
- `svc.corpus_unit_search` (M5) đã tồn tại, authorization-before-influence (enumerate allowed (profile,project,space) tuples trước FTS).

## Changed (commits local, KHÔNG push)

1. `635769d` — V140-03 implement:
   - `src/integration/m6/mcp_server.py` (MỚI): stdio JSON-RPC (initialize/tools/list/tools/call) tái dùng `configure()`+`handle_call`(mcp_wrapper)+`Dispatcher`. KHÔNG fork core (no GrantAdminService/WriteService/migrations/ingest import).
   - `src/integration/m6/tools.py`: +`corpus_search` (M6.5, resource_type CORPUS_UNIT).
   - `src/integration/m6/contracts.py`: +`CORPUS_UNIT` enum.
   - `src/integration/m6/handlers.py`: +`handle_corpus_search` tái dùng `svc.corpus_unit_search` (authorization-safe, reuse M5).
   - `src/integration/hermes_read_adapter.py`: +`corpus_search` vào ALL_READ_TOOLS (11 tools).
   - `scripts/corpus_import_cli.py` (MỚI): stable offline import entry (wrapper corpus_generic_ingest, main(argv)).
   - `scripts/corpus_generic_ingest.py`: main(argv=None) để testable/wrapper.
   - `examples/mcp_client_poc.py` + `examples/mcp_demo.py` (MỚI): non-Hermes stdlib MCP client + reproducible demo.
   - `tests/unit/test_v140_03_mcp_corpus.py` (MỚI, 5 tests): server wiring, sanitized units, authorization isolation, unknown-method.
   - Updated M6/M7 acceptance tests: 10→11 tools (corpus_search), deny-parity fields, resource_type map.

2. CHECKLIST V140-03 ticked (docs/v1.4/CHECKLIST.md) — chưa commit riêng (cùng handoff).

## Verified (Builder self-test)

- POC thực tế: `examples/mcp_demo.py --store-path <corpus-derived.sqlite>` → corpus_search "kelly criterion" → **SUCCESS** 3 units (authorized_corpus_match), sanitized (unit_id/normalized_text/knowledge_space_id, no stored_path/grant).
- Authorization isolation: intruder-profile → DENIED/EMPTY (no leak).
- Import CLI dry-run: 600 dirs / 470 derived-md / 129 orphan-md / 1 primary-pdf (khớp V140-01).
- `test_v140_03_mcp_corpus.py`: 5 passed.
- Full suite (isolated HOME, Py 3.13.15): **3422 passed, 7 skipped, 0 failed** (tăng 10 tests vs baseline 3412).

## Verifier (deleg_4926897a, đang chạy)

Độc lập, READ-ONLY, chạy POC client thực tế + authorization isolation + import CLI + full suite. OVERALL chờ.

## Risk / Notes

- M6.5 corpus_search mở rộng M6 surface từ 10→11 tools (M6.6 isolation giữ: corpus_unit resource_type distinct từ corpus_source). Đã update mọi acceptance test "unchanged 10" → 11.
- MCP server script-mode fallback (absolute import) để chạy trực tiếp `python mcp_server.py` từ examples client (subprocess spawn).
- Token cost thấp (transport-only wrapper + 1 handler reuse). Rủi ro thấp (no schema change, no core fork).

## Next (GATE-3)

- Chờ Verifier OVERALL PASS → maintainer duyệt GATE-3 (POC client ngoài Hermes OK).
- Sau GATE-3: V140-04 (retrieval-quality benchmark) — baseline precision@k.
- **DỪNG tại GATE-3** — không tự chuyển V140-04.

## Authorization

Local-only, chưa push. Commits: `5a99ce4`(SCOUT/ADR) `a5e0fde`(DEF-004 B) `aba47b0`(docs) `691fe9c`(handoff V140-02) `635769d`(V140-03). Chờ GATE-3 + release duyệt.
