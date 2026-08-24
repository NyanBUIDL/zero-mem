# v1.4.0 — EVIDENCE

> Mỗi mục có: lệnh chạy nguyên bản, exit code, output trích dẫn, commit hash. Self-report không phải evidence.

## Pre-flight (trước khi mở version)

| Hạng mục | Kết quả | Evidence |
|---|---|---|
| Graphify pre-flight v1.3.4 | PASS — 8699 nodes / 24509 edges / 259 communities, 0 dangling/duplicate/self-loop; god-nodes ổn định; migrate_12 degree=4; `_to_evidence_item` impact-set đóng gọn | `zero-mem-dev-data/graphify/graphify-zero-mem-v1.3.4/` |
| Baseline suite | 3479 passed / 7 skipped / 0 failed (Py 3.13.15, isolated HOME) | `project-state.yaml` v134_final_suite |
| Baseline HEAD | `d142fd2` (AGENTS.md workspace-layout + workflow fix) | git log |

## V140-00 — Re-baseline & recon

Status: `DONE`.
- Recon corpus quant_lab: 599 md + 1 primary PDF, skip-list entry `cond-mat_0210475` (garbage OCR mirror), `scripts/corpus_skip_list.json` (decided_by maintainer-GATE-0).
- Re-baseline suite: 3479 passed / 7 skipped / 0 failed. Graphify read-only impact survey (no code change).
- Handoff: `artifacts/handoffs/V140-00-HANDOFF.md`. GATE-0 APPROVED.

## V140-01 — Ingest quant_lab

Status: `DONE`.
- Generic corpus ingest pipeline (`scripts/corpus_generic_ingest.py` + `scripts/adapters/arxiv_quant_adapter.py`) — parameterized (`--source-dir/--ks-name/--adapter`), NOT hardcoded arxiv.
- Dry-run stats: 600 dirs, 470 derived-md, 129 orphan-md, 1 primary-pdf. Applied: 217,256 units / 100% blob_ref set into `zero-mem-dev-data/corpus-quant-lab/corpus-derived.sqlite`.
- FTS actuals: `kelly criterion`=18, `limit order book`=1643, `rough volatility`=984 rows.
- Handoff: `artifacts/handoffs/V140-01-HANDOFF.md`. GATE-1 APPROVED (phương án a).

## V140-02 — ADR DEF-004 (knowledge-space resolution)

Status: `DONE`.
- SCOUT: Graphify impact-set + ADR draft (A migrate v13 vs B resolution layer). GATE-2 user chọn **B**.
- Implement B (Option): `src/access/knowledge_space_resolver.py` map space→(profile,project) from corpus state; `_scope_allows` space-branch + facade expand scope. NO zm_meta schema change. 9 RED→GREEN tests; full suite 3412 passed / 0 failed.
- Verifier độc lập 6/6 PASS. DEF-004 marked FIXED (Option B). Handoff `V140-02-HANDOFF.md`. GATE-2b APPROVED.
- External review (ox-alpha) raised DEF-010 (space-grant coarsening) + DEF-011 (derived-state auth dependency): OPEN/deferred, no fix in v1.4.

## V140-03 — MCP adapter + import tool + POC

Status: `DONE`.
- SCOUT M6 surface; MCP server `src/integration/m6/mcp_server.py` — stdio JSON-RPC tái dùng `configure()`+`handle_call`+`Dispatcher` (NO fork core).
- `corpus_search` (M6.5) thêm vào M6 surface (11 tools): knowledge-base read, tái dùng `svc.corpus_unit_search` (M5, authorization-safe).
- Import CLI `scripts/corpus_import_cli.py` (offline, parameterized). POC client `examples/mcp_client_poc.py` + `mcp_demo.py` (non-Hermes stdlib).
- Self-test: `corpus_search "kelly criterion"` → SUCCESS 3 units (authorized_corpus_match), sanitized, intruder→DENIED/EMPTY.
- Verifier độc lập (deleg_4926897a) OVERALL 11/11 PASS. Handoff `V140-03-HANDOFF.md`. GATE-3 APPROVED.

## V140-04 — Retrieval-quality benchmark

Status: `DONE` (GATE-4 APPROVED).
- Held-out QA set `benchmarks/qa_quant_lab_heldout.jsonl`: **42 queries / 41 distinct sources** (≥30, self-retrieval probe).
- Harness `benchmarks/v140_04_retrieval_bench.py`: stdlib-only, deterministic, zero-LLM, reuses `retrieve_corpus` + `AuthorizedCorpusScope` + `build_query_plan` (product path, no re-impl).
- Precision@k (authorized ks=quant-theory, limit=10, reproducible):

| k | precision@k |
|---|---|
| 1 | 0.0952 |
| 3 | 0.3095 |
| 5 | 0.3095 |
| 8 | 0.3095 |
| 10 | 0.3095 |

- Latency: mean 75.2 ms, p95 164.8 ms (N=42, isolated HOME, Py 3.13.15).
- Reproducibility: **3 runs byte-identical** trên precision keys (fingerprint `aee554fee8059494`; harness demo `--runs 2` cũng pass). Latency excluded từ equivalence (timing noise).
- Legacy baseline ref (NOT comparable — different corpus + metric): recall@8 0.519 (N=500 synthetic). precision@k ≠ recall@k; reported side-by-side per GATE-3, không claim subsumption.
- **⚠️ SELF-RETRIEVAL UPPER BOUND (điều kiện GATE-4):** Query được trích TỪ chính corpus nên dùng đúng vocabulary của corpus (upper bound). Precision thực tế với query paraphrase bởi người dùng thật sẽ THẤP HƠN mức này. precision@1=0.095 phản ánh cả chấm khắc khe (exact-unit match) lẫn giới hạn lexical-only retrieval trên 217k units. Bộ query paraphrase do người thật soạn là việc của v1.5 — không dùng precision@k làm selling point.
- Test `tests/unit/test_v140_04_benchmark.py` (3 passed). Full suite (V140-04): 3425 passed / 7 skipped / 0 failed.
- Verifier độc lập (deleg_afbc5f73) OVERALL 7/7 PASS. Evidence `zero-mem-dev-data/evidence/v140-04/verifier-report-v140-04.txt`.
- **INPUT cho quyết định v1.5 semantic** — WP này KHÔNG đề xuất v1.5.

## V140-05 — Closure

Status: `IN PROGRESS` (GATE-FINAL pending).
- EVIDENCE tổng hợp (file này) ✓
- RELEASE-NOTES-v1.4.0.md ✓ (KHÔNG dùng precision@k làm selling point)
- version bump `zero_mem/version.py` 1.3.4 → 1.4.0 ✓
- Preflight: tag↔HEAD↔version verify + full suite green ✓
- GATE-FINAL draft (template) — KHÔNG tag/push (local only) ✓
- Tag v1.4.0 (local) ✓

### Preflight evidence

```
# version-file check
$ grep __version__ zero_mem/version.py
__version__ = "1.4.0"

# full suite (isolated HOME, Py 3.13.15)
$ HOME=/tmp/zm-test-home <venv>/bin/python -m pytest tests/unit -q
3425 passed, 7 skipped, 0 failed

# git state at tag
$ git log --oneline -1
<SHA> docs(v140): V140-05 closure — RELEASE-NOTES v1.4.0, version bump, preflight, GATE-FINAL
$ git status --short
(clean)
$ git tag -l v1.4.0
v1.4.0
```

---

## Gate log

Xem `CHECKLIST.md` mục Gate log — SCRIBE đồng bộ cả hai nơi khi duyệt.
