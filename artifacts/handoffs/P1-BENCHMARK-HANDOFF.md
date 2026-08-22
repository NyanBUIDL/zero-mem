# P1 — First Executable Memory Benchmark (Recall@K + Token Savings) — Handoff

## Metadata
- Package: `zero-mem` (tree: `zero-mem-v123-engineering`)
- Branch: `v124-post-release-closure` (HEAD `975b268`; P0 autofix merged local `master` = `975b268`)
- Date: 2026-08-22
- Status: **BENCHMARK_HARNESS_IMPLEMENTED + BASELINE_MEASURED** (first executable baseline; NOT a release gate)
- Authorization: user selected "Bước A + P1 Benchmark Recall@K/token-savings" in-session.

## Deliverable
`benchmarks/run_memory_benchmark.py` — deterministic synthetic-labeled memory benchmark
over the REAL product pipeline:
- Canonical JSONL (`ingest_file`) → derived SQLite (`rebuild_project_memory`) → `AuthorizedReadService`
  → `route()` + `build_evidence_set()` (M7 EvidenceSet, the exact bounded retrieval path).
- 29 gold queries (benchmark-plan B01–B30 families + dedicated probes C-QUANT / C-FUND / C-CLAIM).
- Metrics: plan-route accuracy, contract-route accuracy, Recall@5/@8, MRR, stale safety,
  active-recall-on-stale, conflict visibility, claim non-promotion, isolation, latency p50/p95,
  token savings vs full-history estimate, determinism (double-run byte-equality of evidence ids).

## Evidence (real runs, isolated TMPDIR/HOME per repo convention)
- `zero-mem-dev-data/evidence/p1-benchmark/benchmark-memory-recall-v2.json` (22,224 B, valid JSON)
- `zero-mem-dev-data/evidence/p1-benchmark/benchmark-summary.txt`
- `zero-mem-dev-data/evidence/p1-benchmark/benchmark-stderr.log` (empty)
- Graphify re-extraction (post-change, read-only): `zero-mem-dev-data/graphify/v124-eval-p1/` (background)

## Baseline numbers (v2, 29 queries, synthetic store)
| Metric | Value | Note |
|---|---:|---|
| plan_route_accuracy | 0.931 | B08/B28 "latest" → EXTERNAL_CURRENT (freshness precedence) |
| contract_route_accuracy | 1.000 | router matches its documented precedence on all 29 |
| mean recall@5 | 0.217 | bounded primary evidence |
| mean recall@8 | 0.406 | bounded primary+supporting |
| mean mrr | 0.350 | deterministic ordering quality |
| stale_safe_rate | 1.000 | superseded ids never surfaced |
| active_recall_on_stale | 0.333 | docker-state queries starved (see findings) |
| conflict_visible_rate | 0.333 | only when retrieval succeeds (C-FUND) |
| not_primary_rate | 1.000 | assistant_claim never primary |
| isolation_ok | True | foreign profile leaks no OWNED record (ART1/V1 are NULL-profile, globally readable by design) |
| latency p50/p95 | 0.80 ms / 1.17 ms | spec target < 2 s |
| token_savings_ratio | 0.259 | avg 47 evidence tokens vs 182 full-history (~74% saved; small corpus) |
| deterministic_repeat | True | identical evidence ids across two runs |

## Root-caused findings (verified by direct probes)
1. **FTS hyphen bug (product-level retrieval gap).** Query `walk-forward validation`
   → `malformed_fts_expression` → research retrieval returns ZERO (typed error swallowed into
   empty candidate set). Probe: `walk forward validation` (no hyphen) → hit. Real-world impact:
   hyphenated compound terms are common in research/code text. Plan query B11 fails for this
   reason. No normalization/fallback exists for hyphenated query terms.
2. **FTS AND brittleness.** Multi-term query with any out-of-vocabulary word returns zero
   (`two sources report different funding values` — `two/report/different` absent → 0).
   No OR/partial-match/fallback. Plan queries B16/B18 fail.
3. **State starvation in the PROJECT EvidenceSet (ordering/budget gap).** M4 state records
   (S1 = current step, S3 = docker fixed) lose to decisions in `select_evidence` order key
   (role → verified → lifecycle → created_at → evidence_id; all M4 rows share created_at, so
   D* ties beat S*). B01 (current project step) and B06/B09 (docker status) return ZERO state
   evidence; primary fills with D2–D5 + C1/R1. M8.5 calibration metadata is observation-only
   and does not re-rank the EvidenceSet.
4. **Knowledge-space filter not enforced on memory events.** `search_text` builds
   `QueryRequest` without knowledge_space; M5 scope restricts profile/project only (zm_meta has
   no ks column). Research isolation currently relies on FTS term-matching, not scope
   enforcement (known M5.2 design: knowledge_space has no event linkage).
5. **History/as-of reads not wired into the standard EvidenceSet.** B29 (pre-supersession
   fact) correctly returns nothing (stale_safe), but answering "what was true before" needs
   M8.4 `temporal_read` integration (out of scope for this baseline).
6. **Isolation verified.** Foreign profile sees only NULL-profile records (ART1/V1) — owned
   pr1 records (decisions/states) are denied; consistent with M5.2 global-read semantics.

## Honest caveats
- Synthetic corpus is small (16 M3 events + 11 M4 events; full-history baseline 182 tokens).
  Token-savings ratio and Recall numbers are a FUNCTIONAL baseline, not a production-scale claim;
  rerun on a larger labeled corpus before v1.3 gates.
- B02/B04/B05 gold=() are route-only (recall trivially 1.0); dedicated claim non-promotion is
  measured by C-CLAIM.
- B29's zero recall is an expected limitation (history read), reported honestly.

## Changed files
- `benchmarks/run_memory_benchmark.py` (new; benchmark infrastructure only; no product change)
- Evidence dir under `zero-mem-dev-data/evidence/p1-benchmark/` (outside repo)
- Graphify output under `zero-mem-dev-data/graphify/v124-eval-p1/` (outside repo, disposable)

No product code (`src/`, `zero_mem/`), no tests, no state, no schema, no packaging changed.

## Risks / next steps
- The 4 findings above are the P1 payoff: they are the concrete gaps between spec §17
  acceptance ("gold evidence top-k", "stale-state correct", "conflict visible") and current
  behavior. Recommended follow-ups (each a separate scoped WP):
  1. FTS query normalization for hyphenated terms (small, high value).
  2. EvidenceSet ordering: weight active state freshness / m8 calibration re-rank so
     project-state queries return the current state (design decision needed).
  3. Knowledge-space scope enforcement for memory events (schema/design decision).
  4. Decide whether B08/B28 "latest" should remain EXTERNAL_CURRENT or be allowed a
     memory fallback (product-behavior decision for the plan labels).
  5. Scale the harness to a larger labeled corpus for a production token-savings estimate.
- Not authorized / not performed: product code changes, test changes, commit, push, tag,
  release, merge, remote mutation.

## Verification commands
```bash
cd "/home/lenovo/Hermes Workspace/zero-mem-v123-engineering"
export TMPDIR=/dev/shm/zm-v124-test && export HOME=/tmp/zm-tmp && mkdir -p "$TMPDIR" "$HOME"
.venv-v124/bin/python benchmarks/run_memory_benchmark.py            # summary
.venv-v124/bin/python benchmarks/run_memory_benchmark.py --json     # machine-readable
```
