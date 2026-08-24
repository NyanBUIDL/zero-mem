# v1.4.0 — EVIDENCE

> Điền dần khi thực thi. Mỗi mục phải có: lệnh chạy nguyên bản, exit code, output trích dẫn, commit hash. Self-report không phải evidence.

## Pre-flight (đã hoàn thành trước khi mở version)

| Hạng mục | Kết quả | Evidence |
|---|---|---|
| Graphify pre-flight v1.3.4 | PASS — 8699 nodes / 24509 edges / 259 communities, 0 dangling/duplicate/self-loop; god-nodes ổn định; migrate_12 degree=4 (coupling mỏng đúng thiết kế); `_to_evidence_item` impact-set đóng gọn | `zero-mem-dev-data/graphify/graphify-zero-mem-v1.3.4/` |
| Baseline suite | 3479 passed / 7 skipped / 0 failed (Py 3.13.15, isolated HOME) | `project-state.yaml` v134_final_suite |
| Baseline HEAD | `d142fd2` (AGENTS.md workspace-layout + workflow fix) | git log |

## V140-00 — Re-baseline & recon

Status: `PLANNED` — chưa thực thi.

## V140-01 — Ingest quant_lab

Status: `PLANNED` — chưa thực thi.

## V140-02 — ADR DEF-004

Status: `PLANNED` — chưa thực thi. (Chờ SCOUT soạn đối chiếu A/B → GATE-2 user chọn.)

## V140-03 — MCP adapter + POC

Status: `PLANNED` — chưa thực thi.

## V140-04 — Benchmark baseline

Status: `DONE` — đã thực thi (commit pending GATE-4).

- Held-out QA set: `benchmarks/qa_quant_lab_heldout.jsonl` — **42 queries** (≥30),
  drawn from 41 distinct corpus sources (quant_lab derived units). Self-retrieval
  probe: query = first 14 words of a real unit; ground-truth = that unit_id.
- Harness: `benchmarks/v140_04_retrieval_bench.py` — stdlib-only, deterministic,
  zero-LLM, reuses product path `src.corpus.retrieval.retrieve_corpus` +
  `AuthorizedCorpusScope` + `build_query_plan` (no re-implementation).
- Precision@k (authorized ks=quant-theory, limit=10, 2 runs identical):

| k | precision@k |
|---|---|
| 1 | 0.0952 |
| 3 | 0.3095 |
| 5 | 0.3095 |
| 8 | 0.3095 |
| 10 | 0.3095 |

- Latency: mean 75.2 ms, p95 164.8 ms (N=42 queries, isolated HOME, Py 3.13.15).
- Reproducibility: **2 runs byte-identical on precision-bearing keys** (fingerprint
  `aee554fee8059494`). Latency excluded from equivalence (timing noise).
- Legacy baseline ref (context only, NOT comparable — different corpus + metric):
  recall@8 0.519 (N=500 synthetic). precision@k ≠ recall@k; reported side-by-side
  per GATE-3 condition, không claim subsumption.
- **INPUT cho quyết định v1.5 semantic** — WP này KHÔNG đề xuất v1.5.
- Test: `tests/unit/test_v140_04_benchmark.py` (3 passed: held-out≥30, reproducible 3 runs, rejects<30).
- Commit: V140-04 implement (harness + query set + test + EVIDENCE) pending GATE-4.

## V140-05 — Closure

Status: `PLANNED` — chưa thực thi.

---

## Gate log

Xem `CHECKLIST.md` mục Gate log — SCRIBE đồng bộ cả hai nơi khi duyệt.
