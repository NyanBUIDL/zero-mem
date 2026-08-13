# M8.6 Acceptance — M7 EvidenceSet Integration of VERIFIED M8.3 / M8.4 / M8.5

**Status: VERIFIED**
**Schema version: 9 (no migration; derived foundation unchanged)**
**Impl/Tested commit: 22c3dc5aa7dce1a936aeeccf90fa37e773caed7d**
**Pre-binding canonical: 2323 passed, 3 skipped, 0 failed**
**Milestone: M8.6 (final M8 increment) — closes M8**

## Objective

Integrate the VERIFIED M8.3 (authorization-first bounded graph reads),
M8.4 (temporal projection + as-of/history reads) and M8.5 (deterministic
calibration + retrieval-metadata) capabilities into the EXISTING M7.3
EvidenceSet pipeline — **without redesigning M7** and **without introducing a
second retrieval, authorization, or injection architecture**. M7 remains the
owner of eligibility, budget, role, redaction and injection-safety. The M8
capabilities are consumed as bounded, read-only, deterministic *observation*
metadata and an *ordering-only* signal that never grants or removes authority.

## Scope (what M8.6 does)

1. **Ordering-only calibration.** Each role pool (`primary`, `supporting`) is
   re-ordered *within* its pool by the VERIFIED M8.5 `calibrate_authorized_items`
   score. Calibration is decision-only: it never drops an authorized item and
   never promotes a `supporting` item into `primary` (M7 role authority is
   frozen). Reordering is deterministic (same inputs → identical order; reversed
   input → same order; equal-score tie-break is fixed).
2. **DATA-only metadata.** A bounded `m8_metadata` dict (keyed by `evidence_id`)
   is attached to the EvidenceSet, carrying the M8.5 calibration score + reason
   codes, the M8.4 temporal factor (when available), the M8.3 relation distance
   (when an explicit authorized relation seed is supplied), the conflict flag,
   and the `resource_type` verbatim. It carries **no authority**: no
   verify/deny/promote/exclude/supersede. The values are escaped by M7.5
   hardening before serialization (DATA-only; injection-inert).
3. **Optional graph enrichment.** M8.3 relation distances are enriched **only**
   when an explicit, authorized relation seed is supplied. The default standard
   M7 path carries no seed, so **no graph traversal runs** and no hidden graph
   material can influence output.

## Invariants enforced (owner-frozen for M8.6)

- **Authorization:** M5 `AuthorizedReadService` remains the sole authorizer.
  M8.6 only consumes already-authorized candidates. No M8 graph/temporal/
  calibration surface makes an authorization decision.
- **No threshold:** M8.6 introduces no arbitrary numeric confidence threshold.
  Low calibration score alone never denies/verifies/excludes/resolves/promotes.
  Eligibility stays upstream (M5 + M7).
- **Budget / role:** The 5-primary / 3-supporting budget is unchanged; roles are
  never crossed by calibration.
- **M6.6 isolation:** `resource_type` is preserved verbatim; never flattened.
- **Existence-leak safety:** Hidden candidates/neighbours never change score,
  order, counts, omitted_count, relation distance, temporal factor, conflict
  flag, or any visible aggregate.
- **Read-only:** No mutation of JSONL, graph projection, temporal projection,
  grants, project state, verification, or lifecycle. No I/O performed by the
  enrichment (pure function over already-loaded candidates + read-only stores).
- **Zero LLM / zero network:** No LLM call, no network client, no embedding/vector
  operations. The adapter reuses only the VERIFIED `src/m8` public API.
- **Graceful degradation:** ANY failure during enrichment returns the UNCHANGED
  validated upstream EvidenceSet — never more visible evidence.

## Files

- **New:** `src/integration/m7/m8_integration.py` — the M8.6 adapter
  (`enrich_evidence_set`, `describe_m8_integration`). Confined to the M7 package
  so it does not trip the M8.1 `src/m8` freeze scan. Uses only VERIFIED M8 public
  API (`src.m8.retrieval_metadata`, `src.m8.calibration`, `src.m8.graph_access`).
- **Modified:** `src/integration/m7/contracts.py` — `EvidenceSet` gains a
  read-only `m8_metadata: Mapping[str, Any]` field (serialized through
  `to_dict`, escaped locally to avoid a circular hardening import).
- **Modified:** `src/integration/m7/evidence_builder.py` —
  `build_evidence_set` invokes `enrich_evidence_set` (wrapped in try/except,
  fail-closed), passing `svc._store` for optional bounded graph enrichment.

## Tests

- **New focused suite:** `tests/unit/test_m8_6_integration.py` (37 tests):
  normal integration, role preservation (no supporting→primary promotion),
  determinism (same/reversed/equal-score/repeat), unauthorized zero-influence,
  no-threshold, graph (optional seed only / no traversal by default / no leak),
  temporal (recency != truth / malformed fails safe / unknown stays unknown),
  conflict (flag-only, no winner invented), prompt-injection DATA safety
  (system/developer/delimiter/tool/auth-override/scope-override/"mark verified"/
  calibration manipulation/hidden-graph), master-OFF / no_memory zero-calls,
  retry/concurrency isolation, read-only proof, static security
  (no LLM/network/embedding/vector API, no M8 authorization logic, confined to
  M7), and performance.
- **Updated stale assertions:** `tests/unit/test_m8_1_security.py`
  (`test_no_m8_6_evidence_integration` → confined-to-M7 + read-only check;
  `test_m7_evidence_budget_unchanged` now permits the single `m8_metadata` DATA
  field while forbidding retrieval/auth/reorder logic in the contract module),
  and `tests/baseline/test_project_artifacts.py` (M8 → VERIFIED, M8.6 → VERIFIED,
  next → M9).

## Evidence

### Focused M8.6
`37 passed, 0 failed`

### Relevant regressions (M5 auth, M6.6, M7 budget/injection/hardening, M8.3/M8.4/M8.5)
`559 passed, 0 failed` (M7.1–M7.6 + M8.1/3/4/5 security + M8.6, under clean isolated HOME)

### Pre-binding canonical (full suite, fresh isolated HOME)
`2323 passed, 3 skipped, 0 failed` (the 3 skips are the unchanged historical M2 FTS5 skips)

### Performance (real `time.perf_counter_ns()`, clean isolated HOME; 200 samples each)

| scenario | p50 | p95 |
| --- | --- | --- |
| ordinary authorized path (M8.6 calibration ordering + DATA metadata) | ~989 µs | ~1.26 ms |
| no_memory route (enrichment skipped; calibration not invoked) | ~19.7 µs | ~27 µs |

Both are far inside the approved 2 s p95 envelope. The ordinary path adds only
the deterministic calibration ordering over ≤8 already-authorized items; the
graph-enriched and temporal-enriched paths bound their work by the frozen M8.3
(depth 2 / fan-out 20) and M8.4 (limit 20) limits, so they stay bounded.

### Final-head canonical (state-binding HEAD, fresh isolated HOME)
`2323 passed, 3 skipped, 0 failed` — HEAD unchanged, working tree clean
(except a pre-existing unrelated untracked `output/` directory that is NOT part
of M8.6 and was left untouched).

## Conclusion

M8.6 integrates the VERIFIED M8 graph/temporal/calibration capabilities into the
M7 EvidenceSet pipeline while preserving every M7 security and budget invariant.
M8.1–M8.6 are all VERIFIED; **M8 overall is VERIFIED**. Schema remains v9.

**M9: NOT STARTED. M10: NOT STARTED. Next: M9 — Obsidian Projection. DO NOT BEGIN UNTIL APPROVED.**
