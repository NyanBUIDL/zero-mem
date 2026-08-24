# V140-04 HANDOFF — Retrieval-quality benchmark (precision@k)

- **WP:** V140-04 (v1.4.0) · **Ngày:** 2026-08-24 · **Repo:** zero-mem-v123-engineering @ `f58aa28` (master, local)
- **Authorization:** GATE-0/1/2/2b/3 approvals. GATE-3 APPROVED V140-04 proceed.
- **Phases:** held-out QA set → precision@k harness → reproducibility proof → GATE-4.

## Observed

- `docs/v1.4/EVIDENCE.md` baseline ref: legacy synthetic corpus recall@8 0.519 (N=500, different corpus + metric).
- `benchmarks/` has `m10_benchmark.py` (rollout harness) — reused product retrieval path pattern.
- `zm_corpus_units` schema uses `source_ref` (not `source_id`).

## Changed (commits local, KHÔNG push)

1. `f58aa28` — V140-04 implement:
   - `benchmarks/qa_quant_lab_heldout.jsonl` (MỚI): 42 held-out queries / 41 distinct sources. Self-retrieval probe (query = first 14 words of a real unit; ground-truth = that unit_id).
   - `benchmarks/v140_04_retrieval_bench.py` (MỚI): stdlib-only, deterministic, zero-LLM. Reuses `src.corpus.retrieval.retrieve_corpus` + `AuthorizedCorpusScope` + `build_query_plan` (product path, no re-implementation). Prints precision@k, latency, run fingerprint, reproducibility flag.
   - `tests/unit/test_v140_04_benchmark.py` (MỚI, 3 tests): held-out≥30, 3-run reproducibility, rejects<30.
## Verified (Builder self-test)

- Harness run (2 runs): `precision@1=0.0952`, `@3=@5=@8=@10=0.3095`. Latency mean 75.2ms / p95 164.8ms (N=42, isolated HOME, Py 3.13.15).
- Reproducibility: 3 runs byte-identical on precision-bearing keys (fingerprint `aee554fee8059494`). Latency excluded from equivalence (timing noise).
- `test_v140_04_benchmark.py`: 3 passed.
- Full suite (isolated HOME, Py 3.13.15): **3425 passed, 7 skipped, 0 failed**.
- Verifier độc lập (deleg_afbc5f73) đang chạy → OVERALL chờ.

## Risk / Notes

- Precision@k là SELF-RETRIEVAL probe (no external relevance judgement available). Lower @1 because short 14-word snippets are ambiguous; @3+ stabilizes at 0.31. This is expected for lexical-only retrieval on a 217k-unit corpus.
- Metric discipline: precision@k (this WP) ≠ recall@8 (legacy baseline). Different corpus + different lens. Reported side-by-side per GATE-3, NO claim of subsumption.
- **INPUT cho quyết định v1.5 semantic** — WP này KHÔNG đề xuất v1.5 (tuân thủ SOUL/WP rule).

## Next (GATE-4)

- Chờ Verifier OVERALL PASS → maintainer duyệt GATE-4 (baseline metric).
- Sau GATE-4: V140-05 (Closure: EVIDENCE.md tổng hợp, RELEASE-NOTES, preflight, GATE-FINAL, tag v1.4.0).
- **DỪNG tại GATE-4** — không tự chuyển V140-05.

## Authorization

Local-only, chưa push. Commits: `635769d`(V140-03) `62afcf1`(docs V140-03) `f58aa28`(V140-04). Chờ GATE-4 + release duyệt.
