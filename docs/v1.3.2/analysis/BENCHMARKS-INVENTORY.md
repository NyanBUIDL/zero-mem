# V132-07 — Benchmarks inventory (audit P3-8)

**Date:** 2026-08-23 · Method: per-file grep across tests/ benchmarks/ docs/
artifacts/ scripts/ (evidence-bound = referenced by acceptance evidence that
still governs, or imported by live tests).

| File | Thế hệ | Referenced-by | Verdict |
|---|---|---|---|
| m10_benchmark.py | M10 | corpus/retrieval line (v1.3.x active) | **keep** |
| run_m10_e2e.py | M10 | corpus/retrieval line (v1.3.x active) | **keep** |
| run_m10_rollout.py | M10 | corpus/retrieval line (v1.3.x active) | **keep** |
| run_memory_benchmark.py | M7-era runner | Graphify reverse-reach of eligibility; benchmark docs | **keep** |
| scale_memory_benchmark.py | M7-era scale | benchmark docs / reverse-reach | **keep** |
| v130_benchmark_runner.py | v1.3.0 | v130 evidence chain | **keep** |
| v130_real_corpus_pipeline.py | v1.3.0–v1.3.2 | test_v130_05_redaction_gate + WP-02 hardening | **keep** |
| v130_synthetic_generator.py | v1.3.0 | v130 pipeline companion | **keep** |
| wp02_core_boundaries.py | v1.2.0 wp02 | historical EVIDENCE only (wp-24 backport doc) | **archive** |
| wp03_performance.py | v1.2.0 wp03 | task note only | **archive** |
| wp04_storage.py | v1.2.0 wp04 | ARCH-MEASURE-PRE mention (analysis-only) | **archive** |
| wp05_retrieval.py | v1.2.0 wp05 | task/closure notes (historical) | **archive** |
| wp06_context.py | v1.2.0 wp06 | ARCH-MEASURE-PRE analysis-only | **archive** |
| wp07_hermes.py | v1.2.0 wp07 | NONE | **archive** |
| wp08_api.py | v1.2.0 wp08 | task note only | **archive** |
| wp11_async.py | v1.2.0 wp11 | task note only | **archive** |
| wp12_multi_agent.py | v1.2.0 wp12 | historical V124 evidence mention | **archive** |
| wp13_configuration.py | v1.2.0 wp13 | task note only | **archive** |
| wp14_recovery.py | v1.2.0 wp14 | historical wp-24 plan/evidence | **archive** |
| wp15_status.py | v1.2.0 wp15 | NONE | **archive** |
| wp21_sidecar.py | v1.2.2 wp21 | code-map doc (historical) | **archive** |
| wp22_workspace.py | v1.2.0+ wp22 | NONE | **archive** |
| wp33_lexical_benchmark.py | v1.2.0 wp33 | **tests/unit/test_wp33_retrieval.py imports it — LIVE TEST** | **keep** |

## Action taken

- 13 file `wp*.py` verdict=archive → `mv` sang `benchmarks/_legacy/`
  (git history giữ nguyên, không xoá) + README giải thích.
- `wp33_lexical_benchmark.py` KEEP: import còn sống từ test unit.
- Không sửa nội dung bất kỳ file được giữ lại.

## Post-move verification

Full suite chạy sau mv — xem
`zero-mem-dev-data/evidence/v132/wp7-full-suite.log`.
