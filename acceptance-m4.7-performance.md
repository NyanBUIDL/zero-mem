# M4.7 Performance Baseline (recorded evidence)

Deterministic synthetic corpus, no caching added, no production SLA invented.
Captured via `tests/unit/test_m4_rebuild.py::test_performance_baseline_recorded`.

Environment:
- SQLite version: 3.53.1
- Python version: 3.11.15

Corpus:
- project_count: 3
- corpus_events: 120
- m4_requirement_rows: 60
- m4_deision_rows: 60

Measured (median over 20 iterations unless noted):
- full multi-project rebuild (drop + replay): 9.75 ms
- active Charter lookup (by project_id): 0.005 ms
- Requirement listing (by project): 0.126 ms
- active Decision lookup (project/scope/key): 0.013 ms
- Current State lookup (project/scope/key): 0.005 ms
- Verification lookup (by id): 0.005 ms
- project-artifact listing (by project): 0.045 ms

Acceptance:
- deterministic (same input -> same structure every run; verified by repeated-rebuild tests);
- no pathological behavior (rebuild < 5000 ms bound, lookups sub-ms);
- approved indexes used (PRAGMA query_only intact; active-uniqueness partial unique
  indexes guard the key lookups exercised above);
- baseline recorded for future regression comparison.

Indexes used (verified by EXPLAIN in M4.6/M3 tests): zm_decisions partial unique
index on (project_id, scope, decision_key) WHERE active; zm_project_state partial
unique index on (project_id, scope, state_key) WHERE active; primary-key seeks for
charter/requirement/verification/artifact by explicit id.
