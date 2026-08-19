# WP-33 Evidence

- WP: WP-33 Retrieval Evolution
- Baseline SHA: `7d871a95017c250f2d27a6e284ccfc6ad6f3c02e`
- Dependency WP-32: `VERIFIED`.
- Implementation: `benchmarks/wp33_lexical_benchmark.py`; tests: `tests/unit/test_wp33_retrieval.py`.
- The benchmark uses the real SQLite/FTS5 ingest and read-only retrieval path; it does not implement a parallel retrieval algorithm.
- Benchmark artifact: `artifacts/evidence/wp33-lexical-baseline.json`.
- Measured scales: 1k and 10k synthetic labeled units completed; 100k and 1M were attempted but exceeded the 420-second host execution limit.
- Measured precision@10: `0.1` and recall@10: `1.0` for all four supplied labels at completed scales; precision uses fixed-k denominator.
- Focused retrieval/authorization suite: `82 passed`.
- Full isolated regression excluding known baseline artifact test: `3219 passed, 5 skipped in 63.82s`.
- `compileall`, `git diff --check`, and static secret scan: passed.
- Final Graphify: `7248 nodes, 21397 edges, 188 communities`; disposable output `/home/lenovo/graphify-zero-mem-v1.2-wp33-final-5`.
- No hybrid/vector dependency was added; the synthetic benchmark alone does not justify one.
- Independent fail-closed review: `passed: true`; `security_concerns: []`; `logic_errors: []`.

## Acceptance status

`VERIFYING`.
