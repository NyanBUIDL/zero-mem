# Acceptance — M8.5: Deterministic Calibration and Retrieval-Metadata Integration

**Milestone:** M8.5 (only M8.5; M8.6 / M9 / M10 NOT started)
**Schema:** v9 (unchanged)
**Plan:** `plan-m8.md` §22.1 (owner-approved resolution of M8-OQ-6 and M8-OQ-7, authoritative for M8.5)
**Starting HEAD:** `32756bfae119b069a7345d2e86d5b4a758f1b8c5` (M8.4 closure)
**Implementation/Tested commit:** `5e4d6fe86271c194a16627e71bfccacb7a988f2e`

---

## Objective evidence

### Focused M8.5 tests (ran under isolated HOME with `.venv/bin/python3`)

- `tests/unit/test_m8_5_calibration.py` → **96 passed, 0 failed**
- `tests/unit/test_m8_5_retrieval_metadata.py` → **authz-first, scope, provenance/temporal, revocation-honoured, tie-break (included in the 96 above)**
- Combined focused M8.5 → **96 passed, 0 failed**

### Relevant combined regression (M8.1 / M8.2 / M8.3 / M8.4 + M8.5)

- `tests/unit/test_m8_1_security.py`, `tests/unit/test_m8_1_rebuild.py`,
  `tests/unit/test_m8_1_temporal_provenance.py`, `tests/unit/test_m8_2_projection.py`,
  `tests/unit/test_m8_2_security.py`, `tests/unit/test_m8_3_static.py`,
  `tests/unit/test_m8_3_authorization_first.py`, `tests/unit/test_m8_3_helpers.py`,
  `tests/unit/test_m8_4_temporal.py`, `tests/unit/test_m8_4_security.py`,
  `tests/unit/test_m8_5_calibration.py`, `tests/unit/test_m8_5_retrieval_metadata.py`
  → **all passed, 0 failed** (232 in the M8.x subset; full M8 unit = 464 passed).

### Pre-binding canonical (full `tests/`, isolated HOME)

```
2285 passed, 3 skipped in 16.85s
```

Exit code 0. The 3 skips are the unchanged historical M2 FTS5 skips
(`tests/unit/test_m2_fts5.py`). No deselection, no new skip/xfail, no failure.
The +97 delta vs the M8.4 pre-binding baseline (2188) is exactly the M8.5
focused suite.

---

## What M8.5 adds

Two new modules under `src/m8/`, plus the `scoring_implemented` flag flipped to
`True` in `calibration_contract.describe_calibration_contract()` and the
`calibration_scoring_implemented` field flipped to `True` in
`describe_derived_foundation()` / `describe_projection()`. No schema migration.

### `src/m8/calibration.py` — deterministic calibration engine

Frozen, pure, read-only. Implements the owner-approved formula from
`plan-m8.md` §22.1.

- **Eight factors, closed vocabularies** (§22.1.3):
  1. `retrieval_match` — authorized relation distance (in-request only; no
     cross-request normalization). None → 1.0, 0 → 1.0, 1 → 0.9, 2 → 0.8,
     else fails closed.
  2. `scope_priority` — `exact` 1.0, `composed` 0.9, `global_fallback` 0.8;
     `unauthorized` is an EXCLUSION marker, never a zero value.
  3. `verification_strength` — keyed by the EXISTING memory/evidence type names
     (the `EventType.value` set): `verified_state`/`verification` 1.0,
     `decision`/`tool_observation` 0.9, `user_statement` 0.8,
     `assistant_claim` 0.6, `inference` 0.5; unknown type FAILS CLOSED.
  4. `provenance_completeness` — per M7.3 eligibility (identity + record time or
     source event id required): `complete` 1.0, `required_only` 0.75,
     `incomplete` EXCLUDED.
  5. `temporal_validity` — `valid` 1.0, `unknown` 0.75, `invalid` EXCLUDED.
     Recency is never a reward: validity is a discrete valid/unknown/invalid
     judgement; a newer timestamp does not raise the score.
  6. `lifecycle_eligibility` — `active`/`candidate`/`confirmed`/`observed` 1.0,
     `superseded`/`conflicted`/`archived` 0.5, `deleted` EXCLUDED.
  7. `conflict_penalty` — no conflict 1.0, unresolved conflict 0.5 (lowers only;
     never resolves or declares a winner).
  8. `relation_relevance` — in-request `retrieval_relevance` when present and
     within [0,1], else 1.0.
- **Combination = multiplicative product** over the eight bounded unit factors
  (§22.1.2). No independent weights; no additive bias; no recency term.
- **Score range [0.0, 1.0]** (§22.1.4). Out-of-range / `NaN` / non-numeric /
  boolean-mistaken-for-number inputs **fail closed** (raised `CalibrationError`)
  — they are NOT clamped. This is by design: a malformed signal must never
  silently become a usable score.
- **Exclusion before calibration** (security-relevant, fixed order):
  `unauthorized` scope, `invalid` temporal, `incomplete` provenance, `deleted`
  lifecycle, and unknown `memory_type` are each excluded with a distinct code
  before any factor is derived. The result for a candidate is therefore
  identical whether calibrated alone or alongside any other candidates —
  authorized or not.
- **Deterministic tie-break** (§22.1.5): `score desc`, then `resource_type asc`
  (enum order), then `resource_id asc`. It is a pure function of
  `(score, resource_type, resource_id)` — no insertion order, no Python
  `id()`, no hidden state. Verified by `test_hidden_candidate_cannot_affect_…`
  and `test_stable_under_reverse_insertion_order`.
- **Calibration score is NOT authority.** `verification_status` (the M8.1
  closed verification echo) and `lifecycle_status` are carried through into the
  `CalibrationResult` UNCHANGED. They never feed a factor, are never set by
  calibration, and a high score never promotes `assistant_claim` or upgrades
  verification (`ASSISTANT_CLAIM_NOT_PROMOTED` reason code; authority-safety
  tests assert this explicitly).
- **Pure / read-only / zero I/O / zero LLM / zero network.** No `openai`/
  `anthropic`/HTTP/socket imports; behavioral tests assert no LLM token and no
  network expression. `describe_calibration()` exposes `performs_io: False`,
  `fails_closed: True`, `independent_weights: False`, `clamps_out_of_range: False`.

### `src/m8/retrieval_metadata.py` — authorization-first retrieval-metadata integration

An INTERNAL adapter (request-time only). It attaches deterministic calibration
metadata to retrieval candidates that M5 has ALREADY authorized.

- **Authorization FIRST, consumes the M5 decision.** `calibrate_authorized_result`
  takes an M5 `AuthorizedResult` and honours its `AuthorizationDecision`: a
  denial (or any downstream error) produces an empty, unauthorized
  `RetrievalMetadataResult` that leaks NO existence, NO count, NO ordering.
  The upstream decision is never re-made or second-guessed.
- **No cache between calls → revocation honoured immediately.** Because nothing
  is memoized, a subsequent call with a revoked/denied result returns empty; no
  stale prior output can leak. Verified by `test_revocation_honoured_no_cache`.
- **No authorization surface of its own.** It imports no `src.access.policy`,
  makes no grant/deny decision, issues no read of its own. It only describes and
  orders what M5 handed it.
- **No new tool surface, no traversal, no result-limit change, no mutation.**
  `describe_retrieval_metadata()` exposes `makes_authorization_decisions: False`,
  `consumes_m5_decision: True`, `performs_io: False`, `performs_traversal: False`,
  `mutates_input: False`, `persists_scores: False`, `changes_m3_ordering: False`,
  `changes_result_limits: False`, `adds_tool_surface: False`.
- **Scope/provenance/temporal classification** reuses the SAME closed vocabularies
  as the calibration engine (`classify_scope`, `classify_candidate_provenance`
  per M7.3, `classify_temporal_validity` per M8.4 semantics). An explicitly
  authorized cross-space/composed scope is `composed` (0.9); the exact-requested
  scope is `exact` (1.0).

---

## Static / authority-boundary audit (M8.5)

`tests/unit/test_m8_5_retrieval_metadata.py` and `test_m8_1_security.py` confirm:

- No banned LLM / network modules imported; no LLM tokens; no network
  expressions; no `subprocess`/`eval`/`exec`/`__import__`; no vectors/embeddings.
- The M8.1 static freeze was narrowed (M8.4 precedent) so the calibration/
  scoring vocabulary (`def calibrate`, `def compute_score`, `FACTOR_WEIGHTS`,
  `def rank_/rerank`, etc.) is permitted ONLY inside `src/m8/calibration.py` and
  `src/m8/retrieval_metadata.py`, and banned from leaking backwards into
  M8.1/M8.2/M8.3. `test_no_m8_5_calibration_scoring_outside_m8_5` passes.
- `test_no_m8_6_evidence_integration` and `test_no_m9_obsidian` /
  `test_no_m10_corpus_expansion` still pass (M8.6/M9/M10 NOT started).
- No `migrate_10.py`; modules live only under `src/m8`.

---

## Unchanged surfaces (evidence of non-regression)

- **Schema remains v9.** No `migrate_10.py`; only descriptive flag values moved.
- **No M8.6 / M9 / M10** code added.
- **No Hermes-core modification:** M8.5 lives entirely under `src/m8` (plus the
  additive flag edits in `src/m8/calibration_contract.py`, `src/m8/derived_index.py`,
  `src/m8/graph_projection.py`).
- **M6 tools unchanged:** unchanged.
- **M7 EvidenceSet unchanged:** unchanged.
- **M8.1 / M8.2 / M8.3 / M8.4 regressions green** (see combined regression above).

---

## Stale introspection corrections (objectively required by the scoring_implemented transition)

1. `src/m8/calibration_contract.py::describe_calibration_contract` — `scoring_implemented`
   flipped `False` → `True`; docstring updated (M8.5 legitimately implements scoring).
2. `src/m8/derived_index.py::describe_derived_foundation` / `src/m8/graph_projection.py::describe_projection`
   — `calibration_scoring_implemented` flipped `False` → `True` (additive).
3. `tests/unit/test_m8_1_rebuild.py`, `tests/unit/test_m8_1_temporal_provenance.py`,
   `tests/unit/test_m8_2_projection.py` — assert the now-true
   `*_scoring_implemented` flags.
4. `tests/unit/test_m8_1_security.py::test_no_m8_5_calibration_scoring` renamed to
   `test_no_m8_5_calibration_scoring_outside_m8_5` and scoped to M8.5's own
   modules. `tests/unit/test_m8_2_security.py::test_no_m3_plus_read_service_modules_added`
   updated to remove `calibration.py` (now a permitted M8.5 module).

These are smallest-exact updates (M8.4 precedent); no test was weakened generically.

---

## Verification status

- Pre-binding canonical: **2285 passed, 3 skipped, 0 failed** (isolated HOME,
  `.venv/bin/python3`, exit 0).
- M8.5 focused: **96 passed, 0 failed**.
- Relevant M8.1–M8.5 regression: **all passed, 0 failed**.
- Final-head canonical: **2285 passed, 3 skipped, 0 failed** (isolated HOME,
  `.venv/bin/python3`, exit 0; evidence/state-binding commit `770555c`).
