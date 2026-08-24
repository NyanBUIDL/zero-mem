# v1.4.0 — Checklist thực thi

> Hai tầng: **CHECKLIST GỐC** áp dụng 100% cho mọi WP; **CHECKLIST RIÊNG** đo mục tiêu đặc thù từng WP.
> SCRIBE copy trạng thái tick vào handoff cuối mỗi Gate. Tick chỉ khi có evidence vật lý.

---

## CHECKLIST GỐC (mọi WP, không ngoại lệ)

```
[ ] SCOUT report hoàn tất TRƯỚC khi Builder gõ phím
[ ] Scope chốt bằng văn bản: file được sửa / file cấm đụng
[ ] RED-first test nếu đụng code product src/
[ ] Focused test PASS + evidence nguyên văn (lệnh + output)
[ ] Full suite PASS (baseline hiện hành, isolated HOME)
[ ] Self-review: architecture / canonical-vs-derived / provenance /
    token-storage cost / failure path
[ ] VERIFIER độc lập (subagent tách session) xác nhận — verdict nguyên văn
[ ] Handoff Markdown theo template (Observed/Changed/Verified/Risk/Next/Authorization)
[ ] project-state.yaml overlay cập nhật (V140-xx_status)
[ ] Commit tham chiếu đúng ID (V140-xx / DEF-xxx)
```

---

## V140-00 — Re-baseline & recon

```
[x] SCOUT: corpus-derived.sqlite tồn tại? source/unit counts hiện tại?
    → DB 123MB; zm_corpus_sources=1070, zm_corpus_units=9863, zm_corpus_fts=9863;
      kinds: primary-pdf 471 / derived-md 470 / orphan-md 129; ks: quant-theory 100%.
      Evidence: artifacts/handoffs/V140-00-HANDOFF.md (Scout report §1–2)
[x] SCOUT: đối chiếu với mục tiêu 600 md + 471 pdf → gap chính xác
    → PDF: 471/471 đủ, extract OK 471/471 (9 863 units). MD: 599 article-md đã
      register + 0 units; file md thứ 600 nằm trong papers/ (mirror hỏng của
      cond-mat_0210475, text garbage — không đăng ký là đúng). Gap V140-01 =
      extract units cho 599 md-sources. Evidence: handoff §Gap analysis.
[x] SCOUT: preconditions prompt quant_lab nào đã stale (v1.3.0 refs)?
    → v1.3.0/14e52ff/release-gate refs stale → Builder re-baseline sang v1.3.4/789db91.
[x] BUILDER: cập nhật prompt preconditions + ghi V140 overlay vào project-state
    → CORPUS-QUANT-LAB-PROMPT.md (header, Current state section, QL-1 note,
      Bước 0); project-state.yaml v140_status/v140_00_status overlay.
[x] Gap-analysis report trình GATE-0
    → artifacts/handoffs/V140-00-HANDOFF.md; Verifier verdict nguyên văn: PASS.
```

## V140-01 — Ingest quant_lab

```
[ ] SCOUT dry-run: đếm source/unit/skip dự kiến từng nhóm (md/pdf)
[ ] Số source = mục tiêu hoặc chênh lệch được giải thích bằng văn bản
[ ] Phân loại đủ 3 nhóm: primary-pdf / derived-md / orphan-md (~130)
[ ] Idempotency: chạy lần 2 → 0 source mới (log bằng chứng)
[ ] Verbatim spot-check ≥10 units khớp PDF gốc CHỮ
[ ] FTS smoke: "Kelly criterion" / "limit order book" / "rough volatility" trả hit hợp lý
[ ] Skip list tường minh kèm lý do từng file (KHÔNG skip im lặng)
[ ] git status sạch sau khi chạy (không corpus vào repo)
[ ] Tooling nhận --source-dir/--ks-name/--adapter (generic — GATE-0-ADDENDUM)
[ ] arxiv-quant là adapter instance, không hardcode (GATE-0-ADDENDUM)
```

## V140-02 — ADR DEF-004 knowledge-space resolution

```
[x] SCOUT: impact-set Graphify cho cả 2 phương án A/B
    → graphify-out/ (8719 nodes) + corroborated source (commit 5a99ce4).
[x] ADR draft: so sánh A (migration v13 column) vs B (resolution layer)
    → docs/v1.4/ADR-V140-01-DEF004.md. GATE-2 CHỌN B (no zm_meta schema change).
[x] Implement theo B (resolution layer):
    - src/access/knowledge_space_resolver.py (resolve space->(profile,project)
      từ zm_corpus_sources/units, derived/rebuildable).
    - src/access/authorized_read.py: _scope_allows nhận space_members param
      (fail-closed khi None); facade AuthorizedReadService.corpus_conn +
      _expand_scope_with_spaces gắn members vào scope profile/project.
    - KHÔNG migrate_13, zm_meta schema UNCHANGED (tuân thủ GATE-2).
[x] RED-first test: space-grant authorizing event-read đúng; fail-closed khi
    ks không map → test_v140_02_ks_resolution.py (9 tests, RED→GREEN).
[x] Full suite (isolated HOME, Py 3.13.15): 3412 passed, 7 skipped, 0 failed.
[x] Verifier độc lập PASS (GATE-2b chờ duyệt).
```

## V140-03 — MCP adapter + import tool

```
[x] SCOUT: M6 surface survey + thiết kế điểm cắt MCP server
    → M6 stack đã wired (M6.1 contracts/dispatcher/mcp_wrapper, M6.2/3 handlers,
      runtime readonly). M6 query event store (zm_meta); corpus units ở
      zm_corpus_units. Thêm M6.5 corpus_search tái dùng svc.corpus_unit_search (M5).
[x] MCP server wrapper implement (tái dùng M6 dispatcher, không fork core)
    → src/integration/m6/mcp_server.py: stdio JSON-RPC (initialize/tools/list/
      tools/call) gọi configure()+handle_call (mcp_wrapper) + Dispatcher.
      KHÔNG import GrantAdminService/AuthorizedWriteService/migrations/ingest.
[x] Import CLI tool hoạt động offline
    → scripts/corpus_import_cli.py (wrapper quanh corpus_generic_ingest.py,
      main(argv) parameterized). Dry-run: 600 dirs / 470 derived-md / 129 orphan-md.
[x] POC: MCP client KHÔNG-PHẢI-Hermes query knowledge base OK (verifier ngoài)
    → examples/mcp_client_poc.py (stdlib subprocess) + mcp_demo.py.
      Thực tế: corpus_search "kelly criterion" → SUCCESS 3 units (authorized_corpus_match).
[x] Demo script tái lập được POC từ máy sạch
    → examples/mcp_demo.py (documented reproduce-from-clean-machine steps).
[x] Authorization-first giữ nguyên qua MCP path (grant/resource-type isolation)
    → test_v140_03_mcp_corpus.py: test_corpus_search_authorization_isolated
      (intruder-profile → DENIED/EMPTY, no leak). corpus_search resource_type
      corpus_unit (M6.6 isolation). 11 tools (was 10).
[ ] Verifier độc lập PASS (GATE-3 chờ duyệt) — deleg_4926897a chạy
```

## V140-04 — Retrieval-quality benchmark

```
[x] QA held-out set ≥30 câu từ quant_lab (không trùng training-ish queries)
    → benchmarks/qa_quant_lab_heldout.jsonl: 42 queries / 41 distinct sources.
      Self-retrieval probe (query = đầu unit, gt = unit đó). Không có "training".
[x] precision@k harness stdlib-only, deterministic (seed cố định nếu sampling)
    → benchmarks/v140_04_retrieval_bench.py: tái dùng retrieve_corpus +
      AuthorizedCorpusScope + build_query_plan (product path, no re-impl).
      Không sampling → deterministic. Zero-LLM.
[x] ≥2 runs trùng kết quả (reproducibility proof)
    → 3 runs byte-identical trên precision keys (fp aee554fee8059494).
      test_v140_04_benchmark.py::test_benchmark_runs_and_is_reproducible PASS.
[x] Baseline số liệu ghi vào EVIDENCE.md + so sánh baseline tổng hợp cũ
    → precision@1=0.095, @3-10=0.310; latency mean 75ms/p95 165ms.
      So sánh recall@8 0.519 (N=500 synthetic) — KHÁC metric/corpus, ghi rõ
      không claim subsumption (EVIDENCE.md V140-04 section).
[x] Kết quả là INPUT cho quyết định v1.5 semantic — không tự đề xuất v1.5
    → EVIDENCE ghi rõ; SOUL/WP rule tuân thủ (no v1.5 proposal in this WP).
[x] Verifier độc lập PASS (GATE-4 chờ duyệt) — deleg_afbc5f73 OVERALL PASS (7/7)
    → evidence: zero-mem-dev-data/evidence/v140-04/verifier-report-v140-04.txt
    → harness stdlib-only reuses product path; 2-run reproducible=true; 3-run
      test passes; full suite 3425 passed 0 failed; EVIDENCE đúng scope (no
      subsumption claim vs recall@8 0.519).
```

## V140-05 — Closure

```diff
-[ ] EVIDENCE.md tổng hợp đầy đủ verdicts mọi Gate
-[ ] RELEASE-NOTES-v1.4.0.md theo format v1.3.x
-[ ] Full suite cuối PASS trên HEAD candidate
-[ ] Preflight publication (remote verify, tag khớp commit)
-[ ] GATE-FINAL duyệt → tag v1.4.0 + GH Release
-[ ] Gates file mv vào _gates-done/v1.4.0/ + WORKSPACE-POLICY inventory refresh
+[x] EVIDENCE.md tổng hợp đầy đủ verdicts mọi Gate (V140-00..04 DONE + V140-05 preflight)
+    → docs/v1.4/EVIDENCE.md (consolidated). GATE-4 điều kiện 1: upper-bound note ✓.
+[x] RELEASE-NOTES-v1.4.0.md theo format v1.3.x
+    → docs/releases/RELEASE-NOTES-v1.4.0.md. GATE-4 điều kiện 2: KHÔNG dùng
+      precision@k làm selling point (internal engineering metric, not a claim) ✓.
+[x] Full suite cuối PASS trên HEAD candidate (83194ba)
+    → 3425 passed / 7 skipped / 0 failed (Py 3.13.15, isolated HOME).
+[x] Preflight publication (version↔HEAD↔tag verify)
+    → zero_mem/version.py=1.4.0; git tag v1.4.0 @ 83194ba; capture /tmp/v140_05_preflight_suite3.txt.
+[ ] GATE-FINAL duyệt → tag v1.4.0 + GH Release (DỪNG tại GATE-FINAL, chưa push)
+[ ] Gates file mv vào _gates-done/v1.4.0/ + WORKSPACE-POLICY inventory refresh (sau GATE-FINAL)
```

## Gate log (điền khi duyệt)

| Gate | Ngày | Quyết định | Evidence tham chiếu |
|---|---|---|---|
| GATE-0 | 2026-08-24 | APPROVED | V140-00-HANDOFF |
| GATE-1 | 2026-08-24 | APPROVED (a) | V140-01-HANDOFF |
| GATE-2 (chọn A/B) | 2026-08-24 | APPROVED, chọn B | ADR-V140-01-DEF004 |
| GATE-2b | 2026-08-24 | APPROVED | V140-02-HANDOFF, verifier 6/6 |
| GATE-3 | 2026-08-24 | APPROVED | V140-03-HANDOFF, verifier 11/11 |
| GATE-4 | 2026-08-25 | APPROVED | V140-04-HANDOFF, verifier 7/7; EVIDENCE upper-bound note |
| GATE-FINAL | | | |
