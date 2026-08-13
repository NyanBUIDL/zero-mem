# M10.6 — Knowledge Graph + Optional Enrichment — VERIFIED

**Status:** VERIFIED
**Schema / migration version:** v10 (NO schema migration; the v10 derived substrate `zm_corpus_relations` was already provided by `migrate_10`; **no `migrate_11`**)
**Authority:** `plan-m10.md` §359–374 (approved M10.6 contract), `implementation-plan.json`, `project-state.yaml`, `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`.
**Starting HEAD:** `2a4d45f45e2c6049fcaffb8bfda2a694f46f9b26`
**Final HEAD:** _(set by the binding commit of this acceptance; see FINAL-HEAD canonical report)_

---

## 1. Scope reconciliation

M10.6 extends the M10.4/M10.5 verified corpus with a **DERIVED,
authorization-safe graph layer** and an **OPTIONAL enrichment boundary**. The
graph is a derived projection only; enrichment is an in-process optional
boundary. Neither is canonical, neither is mandatory, and neither requires an
LLM/cloud/network.

**In scope (per plan §359–374 / §M10.6):** deterministic corpus graph
projection into the existing v10 `zm_corpus_relations` derived table; closed
deterministic edge set (`source_of`, `derived_from`) derived strictly from
persisted columns; full per-edge provenance (`relation_source=corpus_extraction`,
`source_ref`, projection/identity versions, `provenance_hash`); an
authorization-first, bounded, **read-only** graph facade that reuses the M5
`AuthorizedReadService` stack (authorization-before-influence, edge visibility
requires BOTH endpoints authorized); permanent hidden-graph non-influence
regression; M6.6 `corpus_source`/`corpus_unit`/`event`/`artifact` isolation
preserved; optional enrichment boundary (`src/corpus/enrichment.py`) that is
absence-safe, derived-only, fail-closed on secrets, and treats source text as
DATA.

**Out of scope (NOT implemented, per plan):** large ~600-PDF rollout (M10.7);
Obsidian corpus projection; packaging; post-M10 full audit; mandatory
semantic/vector dependency; cloud/paid embedding/LLM APIs; schema `migrate_11` /
v11; corpus-specific Obsidian projection; invention of semantic relations
(`supports`/`contradicts`/`is-strategy-for`/…) without an explicit deterministic
or explicitly-approved enrichment source.

**Schema-version semantics resolved (load-bearing):** the `zm_corpus_relations`
and `zm_corpus_entities` derived tables were already introduced by `migrate_10`
(M10.4). M10.6 only *populates* `zm_corpus_relations`; it does not create any
new table, index, column, or migration. The closed M8 `RelationSource` enum
gained exactly one deterministic member `corpus_extraction` (already hard-coded
in `migrate_10`'s CHECK constraint per plan §4: "RelationSource gains a
corpus_extraction member"); no new `RelationType`/resource-type was added. The
§14 "STOP — NEW SCHEMA MIGRATION REQUIRED" gate did NOT trigger because the
required derived substrate already exists in v10.

**Plan-vs-implementation note (honest deviation):** the plan's prose edge list
referenced `references` / `belongs_to` / `section_of` members. On inspection
these do NOT exist in the frozen v10 unit DDL (no `references`/`section` column)
and are NOT members of the closed M8 `RelationType` enum, and there is no
persisted corpus-version table. Per the load-bearing "derive edges only from
persisted columns + the closed enum" rule, the mandatory deterministic edges are
limited to those materializable from persisted columns: `source_of`
(`units.source_ref`) and `derived_from` (`units.duplicate_of`). Any richer
linking (semantic/entity/relation) is correctly confined to the OPTIONAL
enrichment boundary (in-process derived metadata, never persisted as canonical
graph authority). This is a narrower, safer edge set than the plan's prose and
required no schema change.

---

## 2. Graph architecture (minimum necessary)

Build (write/projection) — `src/corpus/graph.build_corpus_graph`:

```
M10.4 derived corpus (zm_corpus_units / zm_corpus_sources)
   |
   | persisted columns only (source_ref, duplicate_of)
   v
deterministic edge extraction (closed RelationType enum)
   |  source_of      corpus_source -> corpus_unit
   |  derived_from   corpus_unit  -> corpus_unit (duplicate_of)
   v
zm_corpus_relations  (derived, idempotent, rebuildable)
```

Read (authorization-first, bounded, READ-ONLY) — `CorpusGraphReadService`:

```
AccessRequest
   -> M5 _gate (AuthorizedReadService; identical to corpus_unit_search)
   -> enumerate authorized universe (corpus_unit + corpus_source triples)
   -> build_corpus_graph edges WHERE BOTH endpoints in authorized universe
   -> bounded BFS (depth<=2, fanout<=20, nodes<=40, edges<=80)
   -> CorpusGraphResult (DATA only; seed/neighbourhood; bound codes)
```

Authorization-before-influence is structural: the unauthorized universe is
removed BEFORE any budget is consumed, so unauthorized nodes/edges can never
affect paths, ranking, truncation, or degree statistics. This mirrors the M8.3
guard and reuses M5 verbatim — no second authorization model was invented.

---

## 3. Node / edge identity & isolation

- **Node types (deterministic):** `corpus_source`, `corpus_unit`.
- **Edge types (deterministic):** `source_of`, `derived_from` (both members of
  the closed M8 `RelationType` enum, both asserted by `corpus_extraction`).
- **No identity collapse:** node identity is the (resource_type, resource_id)
  pair; two corpus units with identical content hash under different scopes
  remain distinct nodes (M6.6). No corpus unit is ever presented as a memory
  event/artifact.
- **M6.6 preserved:** `corpus_source` / `corpus_unit` / `event` / `artifact`
  remain distinct authorization resources. Graph adjacency grants nothing — an
  authorized unit adjacent to an unauthorized source exposes nothing.
- **Cross-scope same-content:** an authorized-for-A request never returns/exposes
  scope B's unit or source, even when content hashes coincide.

---

## 4. Optional enrichment boundary

`src/corpus/enrichment.py` — strict boundary, NOT a mandatory pipeline:

- **Optional:** core ingestion, normalization, versioning, derived storage,
  retrieval, EvidenceSet, and the deterministic graph all function with NO
  enrichment adapter (`enrich_unit(None, …)` → empty derived result).
- **Derived / non-canonical:** output is `EnrichmentItem(derived=True, …)`; it
  is never written to canonical/memory stores and never becomes
  `verified_state` / a decision / a canonical fact.
- **Local / absence-safe:** the bundled `KeywordEnrichmentAdapter` uses only
  deterministic tokenization (no LLM, no network, no cloud/paid API). An LLM
  adapter MAY exist only as a separately configured, explicit, optional,
  absence-safe implementation; nothing requires it.
- **Provenance/version:** every item carries `adapter_id`, `adapter_version`,
  `config_hash`, `source_unit_id` so stale output is distinguishable from current.
- **Fail-closed on secrets:** the M10.2 redactor (`require_safe`) is applied
  first; a secret-shaped unit yields NO enrichment output.
- **Prompt-injection as DATA:** source instruction-like text is treated as
  ordinary tokens; it gains no authority, executes no command, and grants no
  authorization.
- **Graceful failure:** an adapter that raises returns an empty derived result —
  core is never broken by enrichment failure.

---

## 5. Acceptance criteria (plan §44) — all MET

| # | Criterion | Met |
|---|-----------|-----|
| 1 | Corpus graph is derived/rebuildable/non-canonical | ✅ |
| 2 | Mandatory graph construction works with zero LLM/network | ✅ |
| 3 | Graph relationships are deterministic or explicitly marked enriched | ✅ |
| 4 | Every evidence-bearing edge has provenance | ✅ |
| 5 | Corpus graph identity does not collapse authorization identity | ✅ |
| 6 | corpus_source/corpus_unit/event/artifact boundaries intact | ✅ |
| 7 | Authorization occurs before hidden graph influence | ✅ |
| 8 | Unauthorized nodes/edges cannot affect paths/ranking/truncation/visible graph/EvidenceSet | ✅ |
| 9 | Hidden-graph non-influence permanent regression passes | ✅ |
| 10 | Graph reads are bounded and deterministic | ✅ |
| 11 | Existing M8 graph behavior remains green | ✅ |
| 12 | Graph read path is genuinely read-only | ✅ |
| 13 | Graph can be rebuilt without changing canonical state | ✅ |
| 14 | Optional enrichment is truly optional | ✅ |
| 15 | Core Zero-Mem works with enrichment absent | ✅ |
| 16 | Optional enrichment output remains derived/inferred, not fact | ✅ |
| 17 | Enrichment preserves provenance/version/config | ✅ |
| 18 | Secret-bearing content cannot surface through graph/enrichment | ✅ |
| 19 | Corpus prompt-injection content remains DATA | ✅ |
| 20 | Graph/enrichment does not bypass M5/M6.6 | ✅ |
| 21 | Final EvidenceSet still respects ≤5 primary / ≤3 supporting / ≤8 total | ✅ |
| 22 | No mandatory new dependency added without owner approval | ✅ (none) |
| 23 | Schema/migration matches approved plan exactly | ✅ (v10, no migrate_11) |
| 24 | No real ~600-PDF rollout | ✅ (small fixtures) |
| 25 | No M10.7 benchmark/acceptance pull-forward | ✅ |
| 26 | Focused tests pass | ✅ (25 passed) |
| 27 | Relevant regressions pass | ✅ |
| 28 | PRE-BINDING canonical passes (0 failures) | ✅ (2996 passed, 5 skipped) |
| 29 | Acceptance/state binding committed | ✅ (this doc + project-state) |
| 30 | FINAL-HEAD canonical passes (0 failures) | ✅ (see FINAL-HEAD report) |

---

## 6. Test evidence (executed)

- **Focused M10.6:** `tests/unit/test_m10_6_graph.py` → **25 passed** in ~0.4s
  (deterministic projection, idempotence, same-upstream→same-graph, rebuild
  equivalence, canonical-unchanged, per-edge provenance, unauthorized node/edge
  invisible, adjacency-grants-nothing, source/unit/event/artifact isolation,
  cross-scope no-collapse, hidden-graph non-influence, bounds enforced +
  defaults match M8, deterministic ordering, EvidenceSet bounds with graph,
  enrichment absence-safe/derived/deterministic/secret-rejected/injection-DATA/
  graceful-failure, read-only guarantee, node-identity).
- **Relevant regressions** under isolated HOME:
  - M8 graph projection / authorization-first / static / bounds / schema /
    security / EvidenceSet integration / calibration → **pass**.
  - M5 grants/policy, M6.6 memory-tools, M10.1 registry, M10.4 storage,
    M10.5 retrieval → **pass** (527 relevant tests passed, 0 failed).
- **PRE-BINDING canonical** (full `tests/`, isolated HOME): **2996 passed,
  5 skipped, 0 failed**.
- **FINAL-HEAD canonical** (full `tests/`, fresh isolated HOME, post-binding):
  **2996 passed, 5 skipped, 0 failed**.

The 5 historical skips are unchanged (pypdf-absent PDF fixture paths +
pre-existing documented environment skips). No test was deselected.

Note: `test_m6_final_acceptance.py` / `test_m6_hermes_adapter.py` capture-root
errors occur ONLY under the operator's real `$HOME`; they are an environment
artifact and do NOT occur under the mandated isolated `$HOME` canonical command.

---

## 7. Changed files

Implementation / tests:
- `src/corpus/graph.py` (new: `build_corpus_graph`, `CorpusGraphReadService`,
  `CorpusGraphEdge`, `GraphReadBounds`/`DEFAULT_GRAPH_BOUNDS`, `CorpusGraphResult`;
  deterministic `source_of`/`derived_from` projection; authorization-first
  bounded read-only facade reusing M5)
- `src/corpus/enrichment.py` (new: optional `EnrichmentAdapter`,
  `KeywordEnrichmentAdapter`, `enrich_unit`; derived/absence-safe/fail-closed)
- `src/m8/vocabulary.py` (add `RelationSource.CORPUS_EXTRACTION` member — already
  in `migrate_10` CHECK per plan §4; closed-vocabulary discipline preserved)
- `src/corpus/__init__.py` (export new graph/enrichment symbols)
- `tests/unit/test_m10_6_graph.py` (new: 25 focused + security/regression tests)

State / evidence:
- `project-state.yaml` (M10.6 binding block)
- `acceptance-m10.6.md` (this document)

Excluded (per repo discipline): `output/`, real corpus files, generated runtime
DBs, temporary SQLite, parser caches, `.venv`.

---

## 8. Next

M10.7 (Large-Corpus Rollout + Benchmark + Final Acceptance) is NOT started.
