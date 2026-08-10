# Acceptance — M8.4: Temporal Projection and Bounded As-Of / History Reads

**Milestone:** M8.4 (only M8.4; M8.5 / M8.6 / M9 / M10 NOT started)
**Schema:** v9 (unchanged)
**Plan:** `plan-m8.md` §340, §342–§364, §7
**Starting HEAD:** `7cafcc3cb4e44d82cb8e6d25ea47a0c34ef5ca9f` (M8.3 closure)
**Implementation/Tested commit:** `22ef685af8b29792e78b92f565a1257faf27bea4`

---

## Objective evidence

### Focused M8.4 tests (ran under isolated HOME with `.venv/bin/python3`)

- `tests/unit/test_m8_4_temporal.py` → **20 passed, 0 failed**
- `tests/unit/test_m8_4_security.py` → **12 passed, 0 failed**
- Combined focused M8.4 → **32 passed, 0 failed**

### Relevant combined regression (M8.1 / M8.2 / M8.3 + M8.4)

- `tests/unit/test_m8_1_security.py`, `tests/unit/test_m8_1_rebuild.py`,
  `tests/unit/test_m8_2_projection.py`, `tests/unit/test_m8_2_security.py`,
  `tests/unit/test_m8_3_static.py`, `tests/unit/test_m8_3_authorization_first.py`,
  `tests/unit/test_m8_4_temporal.py`, `tests/unit/test_m8_4_security.py`,
  `tests/unit/test_m8_3_helpers.py` → **176 passed, 0 failed**

### Pre-binding canonical (full `tests/`, isolated HOME)

```
2188 passed, 3 skipped in 14.32s
```

Exit code 0. The 3 skips are the unchanged historical M2 FTS5 skips
(`tests/unit/test_m2_fts5.py`). No deselection, no new skip/xfail, no failure.

---

## What M8.4 adds

Two new modules under `src/m8/`, plus the `temporal_query_implemented` flag
flipped to `True` in `describe_derived_foundation()` and `describe_projection()`.

### `src/m8/temporal_projection.py` — temporal projection

- **The only writer** of `zm_temporal_index` (the v9 table added by M8.1).
- Deterministic: each authorized source subsource (`zm_requirements`,
  `zm_decisions`, `zm_project_state`, `zm_verifications`, `zm_artifacts`,
  `zm_project_artifacts`, `zm_relations`, `zm_charter`, `zm_events`) is read and
  its resource rows projected once, in a fixed table order, with a stable
  column SELECT built by introspecting **only the columns that actually exist**
  on each source (`PRAGMA table_info`, cached per connection). It never emits
  a column that is absent on the source.
- **Derived / rebuildable**: `project_temporal(conn)` truncates and re-inserts;
  `rebuild_temporal(conn)` is identical. Fingerprint is order- and row-count
  independent (SHA-256 over sorted `(resource_type, resource_id)` → normalized
  projection) so rebuild is insertion-order-independent and idempotent.
- **Transaction dimension** = `created_at` (the recorded-at instant) wherever
  the source carries it.
- **Valid/effective dimension** = `effective_at` / `valid_from`–`valid_until`
  **only where actually present**:
  - `zm_requirements`, `zm_project_artifacts`, `zm_events` carry `created_at`.
  - `zm_decisions`, `zm_project_state` carry `effective_at` (no `created_at`).
  - `zm_verifications` carries `timestamp`.
  - **None** of the M4 tables carry `valid_from` / `valid_until`; those columns
    surface as `NULL` on the derived row and are **never invented**.
- **No invented timestamps:** unknown time stays unknown (`NULL` → `None`,
  never epoch, never infinity). `zm_decisions`/`zm_project_state` rows that
  lack an `effective_at` have a `NULL` valid time, not a fabricated one.
- **Malformed source timestamps fail closed:** `_norm()` routes through the
  M8.1 `normalize_timestamp` contract; a malformed source timestamp aborts the
  whole projection (deterministic, no partial publish) — same fail-closed
  contract as the M8.1 temporal module.
- **Lifecycle status preserved verbatim:** copied from source
  `lifecycle_status` where present, defaulting to `'candidate'` only for tables
  that have no lifecycle column (artifacts) — never redefined or reinterpreted.
- **Scope / provenance preserved:** `profile_id`, `project_id`,
  `knowledge_space_id`, `source_event_id`, `trace_id` are copied verbatim where
  present. `knowledge_space_id` is `NULL` for all current M4 sources (KS is an
  M5 concept not present in M4 scope); this is preserved, not assumed.
- No authorization, no policy, no grant surface: the projector imports only
  stdlib + sibling `m8` modules.

### `src/m8/temporal_read.py` — authorization-first bounded reads

- **Authorization FIRST.** Every read seeds an M5 `AccessRequest` and routes it
  through `AuthorizedReadService` (the sanctioned M5 facade, same exemption as
  M8.3's `graph_access.py`) **before** any temporal row is read.
  `read_temporal(...)` returns an empty `TemporalReadResult` (no rows, no count,
  no earliest/latest, no revision count, no bound, no `authorized=True`) when
  the seed is denied. No search-then-authorize; an unauthorized resource
  contributes nothing.
- **Sole authorization authority:** the module imports `src.access`
  (`AuthorizedReadService`, `AccessRequest`), `src.access.contracts` (`READ`),
  and `src.access.authorized_read` only. It does **not** import
  `src.access.policy` and makes **no** authorization decision of its own.
- **Transaction vs valid kept distinct:** `as_of_match(fact, dimension, when)`
  and `within_window(fact, dimension, start, end)` are pure predicates that
  switch on `TemporalDimension.TRANSACTION` (`created_at`) vs
  `TemporalDimension.VALID` (`effective_at` / `valid_from`–`valid_until`). The
  two axes are never silently conflated.
- **Unknown time remains unknown:** `_known_or_fail(ts)` returns `None` for
  `NULL`; comparisons treat `None` as "unknown → does not satisfy an as-of /
  window predicate" and **never** as epoch or infinity.
- **Limit ceiling = 20** (approved plan §7: "maximum historical versions per
  resource for an as-of response: 20"). `MAX_HISTORY_VERSIONS = 20`; any
  caller-supplied limit above the ceiling fails closed.
- **As-of / history behavior:** `read_temporal` returns at most
  `MAX_HISTORY_VERSIONS` facts from the authorized resource's own derived row,
  optionally bounded by an as-of instant and/or a `(start, end)` window. As-of
  returns the fact(s) valid/recorded relative to the instant; history returns
  the bounded ordered set of the resource's own temporal facts. The resource is
  a single derived row, so normally a single fact; the bound is enforced as
  policy regardless.
- **Read-only proof:** the read layer issues only `SELECT` against
  `zm_temporal_index` (and the `SELECT` authorization probes via the facade),
  and `describe_temporal_read()` exposes `read_only: True`.
- **Zero LLM, zero network:** no `openai`/`anthropic`/HTTP/socket imports;
  behavioral tests assert no network expression and no LLM token.
- **Recency != truth:** tests assert a newer `created_at`/`effective_at` does
  not promote lifecycle/verification and that supersession is **not** inferred
  from a newer timestamp (explicit M4 supersession references are surfaced
  verbatim as provenance under authorization, never as an authority decision).
- **M6.6 resource_type isolation:** `m4_artifacts`-scoped grants with
  `resource_types=['artifact']` authorize only `resource_type='artifact'` seeds;
  a decision/requirement seed in the same project is denied (test:
  `test_artifact_only_grant_denies_decision_seed`). Revoked / current M5
  authorization is honored at seed time via the live `AuthorizedReadService`.

---

## Static / authority-boundary audit (M8.4)

`tests/unit/test_m8_4_security.py` (12 tests) confirms:

- No banned LLM / network modules imported; no LLM tokens; no network
  expressions; no `subprocess`/`eval`/`exec`/`__import__`; no vectors/embeddings.
- Access imports are exactly the sanctioned surface
  (`src.access`, `src.access.authorized_read`, `src.access.contracts`); no
  `src.access.policy` import; no `GrantAdminService`/`AuthorizedWriteService`;
  no `def authorize`/`def check_access`/etc.
- No hardcoded HOME / `.hermes` paths; no `migrate_10.py`; modules live only
  under `src/m8`.

The M8.1 static freeze (`tests/unit/test_m8_1_security.py`) was updated to
exempt `temporal_read.py` from the `src.access.policy` import ban and to scope
the `def as_of` / `def query_history` / `def history_at` / `as_of_query` ban to
pre-M8.4 modules — mirroring the existing `graph_access.py` exemption.

---

## Unchanged surfaces (evidence of non-regression)

- **Schema remains v9.** No `migrate_10.py`; the only migration touched is a
  descriptive flag field value.
- **No M8.5 / M8.6 / M9 / M10** code added; `test_no_m8_5_calibration_scoring`
  and `test_no_m9_obsidian` / `test_no_m10_corpus_expansion` still pass.
- **No Hermes-core modification:** M8.4 lives entirely under `src/m8` (plus the
  additive flag edit in `src/m8/derived_index.py`, `src/m8/graph_projection.py`).
- **M6 tools unchanged:** `test_m8_does_not_import_m6_tools` passes.
- **M7 EvidenceSet unchanged:** `test_m7_evidence_budget_unchanged` passes.
- **M8.1 / M8.2 / M8.3 regressions green** (see combined regression above).

---

## Stale test corrections (objectively required by the temporal_query_implemented transition)

1. `tests/unit/test_m8_1_rebuild.py::test_declares_deferred_behavior_absent`
   — expected `temporal_query_implemented is False`; updated to `True` (M8.4
   legitimately implements temporal reads).
2. `tests/unit/test_m8_1_security.py::test_no_policy_engine_import` — exempted
   `temporal_read.py` from the `src.access.policy` import ban (sanctioned M5
   consumer, same precedent as `graph_access.py`).
3. `tests/unit/test_m8_1_security.py::test_no_m8_4_temporal_query` — renamed to
   `test_no_m8_4_temporal_query_outside_m8_4`; the as-of / history query
   vocabulary is now expected in M8.4's own modules and only banned from
   leaking backwards into M8.1/M8.2/M8.3.
4. `tests/unit/test_m8_2_projection.py::test_declares_temporal_query_deferred`
   — updated `temporal_query_implemented` expectation to `True`.

These are smallest-exact updates; no test was weakened generically.

---

## Verification status

- Pre-binding canonical: **2188 passed, 3 skipped, 0 failed** (isolated HOME,
  `.venv/bin/python3`, exit 0).
- M8.4 focused: **32 passed, 0 failed**.
- Relevant M8.1–M8.4 regression: **176 passed, 0 failed**.
- Final-head canonical: **PENDING** (run on the evidence/state-binding commit
  per the closure protocol).
