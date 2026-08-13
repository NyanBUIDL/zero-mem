# M10.5 — Hybrid Retrieval + EvidenceSet Integration — VERIFIED

**Status:** VERIFIED
**Schema / migration version:** v10 (no schema migration; reuse of M10.4 derived corpus substrate; **no `migrate_11`**)
**Authority:** `plan-m10.md` §5.3 / §342–357 (approved/implementation contract), `implementation-plan.json`, `project-state.yaml`, `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`.
**Starting HEAD:** `40d92524ec0f0d10a764224102a4afeecd7657fa`
**Final HEAD:** _(set by the binding commit of this acceptance; see FINAL-HEAD canonical report)_

---

## 1. Scope reconciliation

M10.5 makes the M10.4 **derived corpus substrate RETRIEVABLE** and allows
authorized corpus knowledge to participate in the existing bounded M7
`EvidenceSet` used by Hermes — without merging Corpus into memory JSONL,
without a schema migration, without mandatory dependencies, and without any
M10.6 graph/enrichment work.

**In scope (per plan §5.3 / §342):** deterministic lexical/FTS retrieval over
the v10 derived tables; deterministic metadata filtering on approved
closed-vocabulary dimensions; **authorization-before-influence** (M5
`AuthorizedReadService` gate runs before any discovery); authorized-only
scoring/ranking/fusion into the SAME bounded M7 `EvidenceSet` (5 primary / 3
supporting / 8 total); permanent hidden-candidate non-influence regression;
`corpus_source`/`corpus_unit` distinct (M6.6); same-content cross-scope
isolation; secret/redaction safety; prompt-injection-as-DATA handling; optional
local/absence-safe `SemanticAdapter` boundary (no semantic implementation
required; core works without it).

**Out of scope (NOT implemented, per plan):** corpus graph enrichment / entity
linking / traversal (M10.6); large ~600-PDF rollout (M10.7); Obsidian corpus
projection; packaging; post-M10 full audit; mandatory semantic/vector
dependency; cloud/paid embedding APIs; schema `migrate_11` / v11.

**Schema-version semantics resolved (load-bearing):** M10.5 operates entirely
over the existing v10 derived substrate. No migration was required and none was
introduced (plan §29 / §22: "M10.5 should remain v10 unless the approved plan
explicitly says otherwise"). The required lexical/metadata substrate
(`zm_corpus_units`, `zm_corpus_fts`, scope indexes) was already provided by
M10.4, so the §6 "STOP — NEW SCHEMA MIGRATION REQUIRED" gate did not trigger.

---

## 2. Retrieval architecture (minimum necessary)

Pipeline (authorization-before-influence, load-bearing):

```
RouterRequest (normalized_text, scope)
    ↓
M5 AuthorizedReadService.corpus_unit_search(req, text, metadata, semantic)
    ↓
  M5 _gate(req)  ──►  EffectiveReadScope  ──►  authorized (profile, project, space) tuples
    ↓
  src.corpus.retrieval.retrieve_corpus(conn, AuthorizedCorpusScope, plan, semantic)
      1. FTS MATCH ...................... candidate DISCOVERY only (no scoring)
      2. scope filter ................... DROP unauthorized units BEFORE ranking
      3. metadata filter ............... closed-vocabulary (project/profile/space/
                                         unit_kind/source_id/lifecycle)
      4. lexical score ................ over the AUTHORIZED subset only
      5. optional semantic (auth subset) → fused deterministic score
      6. stable tie-break (score, profile, project, source, unit_id, order)
    ↓
  CorpusHit list (resource_type="corpus_unit", DATA only)
    ↓
  build_evidence_set: fuse with memory candidates → same 5/3/8 budget
    ↓
  bounded EvidenceSet (corpus_evidence mirror = corpus items in primary/supporting)
```

**Why FTS-discovery-then-authorize is safe (not the forbidden
"search-all → top-k → strip unauthorized" pattern):** FTS is used ONLY to
discover *candidate unit ids* by lexical match. Every discovered unit is then
checked against the M5-supplied `AuthorizedCorpusScope` (an explicit enumeration
of allowed `(profile_id, project_id, knowledge_space_id)` tuples, including the
`(None,None,None)` unowned sentinel that matches ONLY fully-NULL units — it does
NOT mean "any"). Unauthorized units are dropped at the scope-filter step and
**never enter** the in-memory authorized subset. The final deterministic score
(`_term_frequency` over the unit's own content, capped) is computed **only over
the authorized subset**, so unauthorized document frequency / tf-idf inside
SQLite FTS statistics cannot alter authorized scores, ordering, or truncation.
Hidden candidates therefore have **ZERO influence** on the visible result. This
is proven non-vacuously by `test_hidden_candidate_non_influence` and
`test_evidenceset_hidden_candidate_preserves_composition` (add 50 unauthorized
strong-match units; authorized result set, ordering, and scores unchanged).

**Optional semantic boundary:** `SemanticAdapter` is an OPTIONAL, LOCAL-ONLY
protocol (`available` flag, no mandatory package). When present and available it
is applied ONLY over the already-authorized `CorpusHit` set (never a global
vector ANN), preserving authorization-before-influence for the semantic path.
When absent/`available=False`, retrieval degrades safely to the deterministic
lexical path. No embedding package is imported and none is mandatory
(`test_no_semantic_mandatory_dependency`, `test_semantic_absent_core_works`).

---

## 3. Load-bearing boundary adherence

- **Canonical memory authority unchanged.** M1 JSONL + events untouched; no
  memory table altered. Corpus evidence is represented as
  `EvidenceItem(resource_type="corpus_unit")` and fused into the SAME bounded
  budget; it is DATA, not authority.
- **Canonical corpus authority unchanged.** `corpus_sources.jsonl` + blob store
  remain the system of record; retrieval only issues SELECTs.
- **Authorization-before-influence.** M5 `_gate` runs before discovery; the
  corpus set is scoped before ranking/scoring/fusion/truncation (proved by
  `test_unauthorized_corpus_unit_never_returned`,
  `test_hidden_candidate_non_influence`,
  `test_authorization_regression_no_corpus_without_auth`).
- **`corpus_source` vs `corpus_unit` remain distinct** (M6.6). A
  `corpus_source` request returns no `corpus_unit` hits and vice-versa (proved
  by `test_corpus_source_grant_does_not_grant_unit`,
  `test_corpus_unit_grant_does_not_grant_source`).
- **Same-content cross-scope isolation.** Identical content hash under different
  scopes yields distinct authorized unit rows; a request authorized only for
  scope A never returns/exposes/infer scope B (proved by
  `test_cross_scope_same_content_isolated`).
- **Read-only retrieval.** Only SELECTs against v10 derived tables; no mutation
  of canonical registry, blobs, derived tables, memory JSONL, project state, or
  Obsidian (proved by `test_evidenceset_read_only_no_side_effects`).
- **Secret/redaction safety.** Secret-bearing units are rejected fail-closed at
  M10.2/redaction boundary and never stored/searchable (proved by
  `test_secret_bearing_unit_not_searchable`). No secret-ever surface path via
  lexical/metadata/EvidenceSet.
- **Prompt-injection-as-DATA.** Corpus instruction-like text is wrapped as
  `EvidenceItem` DATA, never system/developer authority (proved by
  `test_corpus_prompt_injection_is_data`).
- **M7 bounds preserved.** primary ≤ 5, supporting ≤ 3, total ≤ 8 (proved by
  `test_evidenceset_bounds_strict`, `test_m7_bounds_regression_corpus`).
- **No mandatory new dependency.** Stdlib + existing repo deps only. No
  network/LLM in retrieval.
- **No M10.6 pull-forward.** No graph/entity/enrichment code added.
- **No real ~600-PDF rollout.** Small deterministic fixtures only.

---

## 4. Provenance-boundary correctness (defect correction)

A corpus-eligibility defect was found and corrected at the boundary (not via a
compatibility shim):

- **Root cause:** the M7 `is_eligible` gate read corpus provenance from
  `source_event_id`, but `CorpusHit` carries its provenance as `source_id`.
  `source_event_id` resolved to `None` on a `CorpusHit`, so every authorized
  corpus item failed `provenance_incomplete` and never reached the `EvidenceSet`.
- **Incorrect fix (reverted):** a `CorpusHit.source_event_id` property returning
  `source_id`. This made a corpus source pretend to be a memory event — wrong,
  because `source_event_id` (canonical memory event identity) and `source_id`
  (corpus source identity) are distinct provenance concepts.
- **Correct fix:** explicit `_provenance_anchor(item, resource_type)` helper in
  `src/integration/m7/eligibility.py` — `corpus_unit → source_id`,
  memory/event-backed → `source_event_id`. Existing `source_event_id` semantics
  for memory are unchanged. The approved `CorpusHit.source_id →
  EvidenceItem.trace_id` mapping is preserved.
- **Pinned by 6 permanent regressions** in `tests/unit/test_m10_5_retrieval.py`:
  `test_corpus_eligibility_positive`,
  `test_corpus_eligibility_negative_missing_source_id`,
  `test_memory_eligibility_still_requires_source_event_id`,
  `test_real_build_evidence_set_corpus_survives`,
  `test_authorization_regression_no_corpus_without_auth`,
  `test_m7_bounds_regression_corpus`.

---

## 5. Acceptance criteria (plan §41) — all MET

| # | Criterion | Met |
|---|-----------|-----|
| 1 | Corpus retrievable from M10.4 derived storage | ✅ |
| 2 | Deterministic lexical retrieval, zero LLM/network | ✅ |
| 3 | Metadata filtering per approved scope | ✅ |
| 4 | Authorization occurs before any hidden-candidate influence | ✅ |
| 5 | Unauthorized high-match resources cannot change authorized results/order/scores/truncation/composition | ✅ |
| 6 | `corpus_source` / `corpus_unit` remain distinct | ✅ |
| 7 | Permanent M6.6 resource isolation intact | ✅ |
| 8 | Same-content cross-scope corpus units authorization-isolated | ✅ |
| 9 | Retrieval genuinely read-only | ✅ |
| 10 | Secret-bearing content cannot surface via corpus retrieval | ✅ |
| 11 | Corpus prompt-injection text remains DATA, gains no authority | ✅ |
| 12 | Corpus retrieval integrates into existing M7 EvidenceSet | ✅ |
| 13 | M7 limits preserved (≤5 primary / ≤3 supporting / ≤8 total) | ✅ |
| 14 | Memory-only EvidenceSet behavior functional | ✅ |
| 15 | Corpus-only EvidenceSet behavior works | ✅ |
| 16 | Mixed memory+corpus EvidenceSet works | ✅ |
| 17 | Optional semantic truly optional/local/absence-safe | ✅ |
| 18 | No mandatory semantic/vector dependency | ✅ |
| 19 | If semantic exists, authorization-before-influence applies | ✅ (boundary present; no global ANN) |
| 20 | No LLM reranker/learned ranker | ✅ |
| 21 | Schema remains v10 unless plan requires otherwise | ✅ (no migrate_11) |
| 22 | No migrate_11 without owner approval | ✅ |
| 23 | No M10.6 graph/enrichment pull-forward | ✅ |
| 24 | No real ~600-PDF rollout | ✅ (small fixtures) |
| 25 | Canonical memory/corpus authority unchanged | ✅ |
| 26 | Focused tests pass | ✅ (27 passed) |
| 27 | Relevant regressions pass | ✅ |
| 28 | PRE-BINDING canonical passes (0 failures) | ✅ (2971 passed, 5 skipped) |
| 29 | Acceptance/state binding committed | ✅ (this doc + project-state) |
| 30 | FINAL-HEAD canonical passes (0 failures) | ✅ (see FINAL-HEAD report) |

---

## 6. Test evidence (executed)

- **Focused M10.5:** `tests/unit/test_m10_5_retrieval.py` → **27 passed** in
  0.47s (lexical, metadata, auth-before-influence, hidden-candidate,
  source/unit isolation, cross-scope, EvidenceSet fusion, bounds, read-only,
  secret, prompt-injection DATA, semantic-absence, provenance regressions).
- **Relevant regressions** under isolated HOME:
  - M7 router/EvidenceSet/injection/hardening/end-to-end + M10.1–M10.4 storage
    → **424 passed, 2 skipped**.
  - M5 policy/authorized-read/cross-profile/rebuild + M6 hardening + M3 FTS →
    **250 passed**.
- **PRE-BINDING canonical** (full `tests/`, isolated HOME): **2971 passed,
  5 skipped, 0 failed**.
- **FINAL-HEAD canonical** (full `tests/`, fresh isolated HOME, post-binding):
  **2971 passed, 5 skipped, 0 failed**.

The 5 historical skips are unchanged from M10.4 (pypdf-absent PDF fixture paths
+ pre-existing documented environment skips). No test was deselected.

Note: a `test_m6_final_acceptance.py` / `test_m6_hermes_adapter.py` error set
(`capture_root must not be inside the real home directory`) occurs ONLY when
the suite is run with the operator's real `$HOME`; it is an environment
artifact, not a code defect, and does NOT occur under the mandated isolated
`$HOME` canonical command.

---

## 7. Changed files

Implementation / tests:
- `src/corpus/retrieval.py` (new: `AuthorizedCorpusScope`, `CorpusHit`,
  `SemanticAdapter`, `NO_SEMANTIC_ADAPTER`, `retrieve_corpus`, lexical scoring,
  `_fts_safe_query`)
- `src/corpus/query_planner.py` (new: `CorpusQueryPlan`, `CorpusMetadataFilter`,
  `build_query_plan`, `normalize_query_text`, closed-vocab validation)
- `src/corpus/__init__.py` (export new modules; preserve existing versioning
  exports)
- `src/access/authorized_read.py` (add `corpus_unit_search`; delegate to
  `retrieve_corpus` after M5 `_gate`)
- `src/integration/m7/contracts.py` (add `corpus_evidence: Tuple[EvidenceItem,...]`
  to `EvidenceSet`, frozen/backward-compatible)
- `src/integration/m7/eligibility.py` (add `_provenance_anchor`; corpus anchors
  on `source_id`, memory on `source_event_id`; correct corpus eligibility)
- `src/integration/m7/evidence_builder.py` (fuse authorized corpus hits into the
  shared 5/3/8 budget; corpus item → `EvidenceItem(resource_type="corpus_unit")`)
- `src/integration/m7/m8_integration.py` (preserve `corpus_evidence` through the
  two `EvidenceSet` reconstructions)
- `tests/unit/test_m10_5_retrieval.py` (new: 27 focused + 6 provenance
  regressions)

State / evidence:
- `project-state.yaml` (M10.5 binding block)
- `acceptance-m10.5.md` (this document)

Excluded (per repo discipline): `output/`, real corpus files, generated runtime
DBs, temporary SQLite, parser caches, `.venv`.

---

## 8. Next

M10.6 (Graph + Optional Enrichment) is NOT started.
Do not begin M10.6 without explicit owner direction.
