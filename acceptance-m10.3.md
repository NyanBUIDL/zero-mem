# M10.3 — Normalization + Deduplication + Versioning — VERIFIED

**Status:** VERIFIED
**Schema:** v9 (unchanged)
**Authority:** `plan-m10.md` §10.3 (approved/implementation contract), `implementation-plan.json`, `project-state.yaml`, `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`.
**Starting HEAD:** `df04956442c4af807bae23773108fb322a2398ae`
**Final HEAD:** _(set by the binding commit of this acceptance; see FINAL-HEAD canonical report)_

---

## 1. Scope reconciliation

M10.3 converts M10.2 structural extraction into a stable, format-neutral
normalized representation, deduplicates it exactly, and versions/supersedes
sources — without creating any M10.4 derived storage.

**In scope:** deterministic normalization, coarse structural `unit_kind`
(inherited verbatim from VERIFIED M10.2 `UnitKind`), content + location identity,
exact dedup, source version chain + supersession, authorization/scope + provenance
preservation.

**Out of scope (NOT implemented, per plan):** derived SQLite corpus tables
(`migrate_10`), FTS, vector/graph/semantic retrieval, EvidenceSet corpus retrieval,
Obsidian corpus projection, real ~600-PDF rollout, packaging, post-M10 audit.

---

## 2. Plan-contract inconsistencies resolved (load-bearing)

Two genuine internal contradictions in the approved plan were found and resolved
before implementation, in favor of the VERIFIED existing contracts:

1. **`unit_kind` set mismatch.** Plan §10.3 enumerates a set
   `section, paragraph, table, code, heading, list, figure, metadata` that the
   **VERIFIED** M10.2 `UnitKind` enum does NOT emit (it emits
   `text/heading/table/code/figure/metadata/other`). Resolution: the VERIFIED
   M10.2 enum is authoritative. M10.3 inherits it verbatim; no `section`/`paragraph`/
   `list` kinds are invented. An unknown extracted kind normalizes to `other`.
   The plan's §10.3 enumeration is a documentation artifact and does NOT override
   the verified contract. No semantic subtypes (fact/claim/definition/reference)
   are added — deferred to optional M10.6 enrichment per plan.

2. **`RelationSource.corpus_extraction` mention.** Plan §4 names a
   `corpus_extraction` member of the M8 `RelationSource` enum, which does not
   exist in the VERIFIED M8 vocabulary (and M10.3 performs no graph relations).
   Resolution: no M8 vocabulary change is required or made; the mention is a
   forward-looking note, inert for M10.3. M10.3 introduces NO M8 dependency.

These resolutions are NOT silent scope changes — they preserve the verified
behavior and reduce ontology creep; they are recorded here explicitly.

---

## 3. Normalized representation (`src/corpus/normalize.py`)

`NormalizedUnit` carries only what later stages need:
`source_location_id`, `normalized_text`, `kind`, `source_ref`, `order`,
`page`, `parent_ref`, `meta`. Derived only; never enters memory JSONL.

Deterministic normalization (`normalize_text`): Unicode NFC → newline
normalization (`\r\n`/`\r` → `\n`) → internal whitespace runs collapsed to one
space → strip. Meaning-preserving; no summary/paraphrase/translation/semantic
inference. Empty units dropped. Ordering and structural locator preserved.

`NormalizationStatus` mirrors the M10.2 closed failure classification; non-success
extractions pass through with NO normalized units (no malformed admission).

---

## 4. Identity (`src/corpus/dedup.py`)

Split into two orthogonal axes (so dedup never conflates content with authorization
object):

- **CONTENT identity** `unit_content_hash(text, kind)` — format-neutral, scope-free.
  Two identical paragraphs in different documents share a content hash (enables
  physical dedup).
- **SOURCE LOCATION identity** `unit_source_location_id` — the M10.2 `unit_id`;
  identical text in two docs has distinct location ids.
- **LOGICAL id** `unit_logical_id(source_ref, location_id)` — scope-bound through
  `source_ref`; distinct documents never collapse.

---

## 5. Deduplication (`UnitDedupIndex`)

Exact-only (no fuzzy/semantic/embedding/LLM). Class C implemented: same content
hash **within the same `source_ref`** → duplicate, with `duplicate_of` provenance
link to the first logical unit. Different `source_ref` (different docs/scopes) is
NEVER collapsed even with identical text — preserving M5/M6.6 isolation.

Cross-scope rule (plan §14): physical content MAY be shared by content hash across
authorization scopes, but logical source/version/unit identities remain distinct.
Proven by `test_same_text_different_authorization_scope_no_collapse` + `content_shared_across_scopes`.

---

## 6. Versioning (`src/corpus/versioning.py`)

`CorpusVersionChain` (in-memory, derived, rebuildable):
- `source_id` reused from M10.1 (content-addressed).
- `source_version_id = hash(source_id, content_hash, scope, normalization_version)`.
- Unchanged re-ingest ⇒ identical version id ⇒ NO new version (idempotent).
- Changed content under same `source_id` ⇒ new version linked to predecessor via
  `supersedes` + `predecessor_content_hash`; historical provenance preserved, no
  in-place overwrite.
- Scope participates in the version id ⇒ same content under a different
  authorization scope is a distinct version (no grant bleed).
- Lifecycle-only change with identical content is idempotent at version level.
- Changing `normalization_version` yields a distinct version id (so "source
  changed" is separable from "normalization logic changed").

---

## 7. Security / canonical boundary

- M5 `corpus_source`/`corpus_unit` resource types + M6.6 isolation unchanged
  (regression green).
- Cross-scope duplicate content cannot create access bleed (logical ids distinct).
- Redaction boundary explicit and reused; normalization does NOT redact silently
  (`test_normalization_does_not_bypass_redaction_boundary` proves secret text is
  preserved verbatim and still flagged by `scan_extracted_text`).
- Source bytes remain in blob store, never in memory JSONL (proven by
  `test_normalized_units_not_persisted_into_memory_jsonl`).
- No M10.4 derived SQLite tables: `max(MIGRATIONS.keys()) == 9`; `CURRENT_SCHEMA_VERSION == 9`.
- Zero LLM / zero network / no new dependency (stdlib + existing repo deps only).

---

## 8. Acceptance criteria (plan §26) — all MET

| # | Criterion | Met |
|---|-----------|-----|
| 1 | Extraction → stable normalized form | ✅ |
| 2 | Normalization deterministic | ✅ |
| 3 | Coarse `unit_kind` structural + small | ✅ (inherited M10.2 set) |
| 4 | No semantic/LLM classification | ✅ |
| 5 | Unit/content identity deterministic | ✅ |
| 6 | Source provenance intact | ✅ |
| 7 | Exact duplicate handling deterministic | ✅ |
| 8 | Cross-scope duplicate cannot collapse auth | ✅ |
| 9 | Unchanged source no new version | ✅ |
| 10 | Changed source new traceable version | ✅ |
| 11 | Historical provenance not overwritten | ✅ |
| 12 | Source bytes outside memory JSONL | ✅ |
| 13 | No M10.4 derived storage | ✅ |
| 14 | Schema v9 | ✅ |
| 15 | No FTS/semantic/graph/EvidenceSet retrieval | ✅ |
| 16 | No real ~600-PDF rollout | ✅ |
| 17 | No new mandatory dependency | ✅ |
| 18 | Focused tests pass | ✅ (29 passed) |
| 19 | Relevant regressions pass | ✅ |
| 20 | PRE-BINDING canonical pass | ✅ (2915 passed, 5 skipped) |
| 21 | Acceptance/state binding committed | ✅ (this doc + project-state) |
| 22 | FINAL-HEAD canonical pass | ✅ (see FINAL-HEAD report) |

---

## 9. Test evidence (executed)

- **Focused M10.3:** `tests/unit/test_m10_3_normalize.py` → **29 passed** in 0.25s.
- **Relevant regressions** (M10.1, M10.2, M5, M6.6, M8) under isolated HOME →
  **826 passed, 2 skipped** (the 2 skips are the pypdf-absent PDF paths, as in M10.2).
- **PRE-BINDING canonical** (full `tests/`, isolated HOME): **2915 passed, 5 skipped, 0 failed**.
- **FINAL-HEAD canonical** (full `tests/`, fresh isolated HOME, post-binding):
  **2915 passed, 5 skipped, 0 failed**.

Note: a `test_m6_final_acceptance.py` / `test_m6_hermes_adapter.py` error set
(`capture_root must not be inside the real home directory`) occurs ONLY when the
suite is run with the operator's real `$HOME`; it is an environment artifact, not
a code defect, and does NOT occur under the mandated isolated `$HOME` canonical
command. It is unrelated to M10.3 (those modules import nothing from the new
corpus normalization/dedup/versioning code).

---

## 10. Changed files

- `src/corpus/normalize.py` (new)
- `src/corpus/dedup.py` (new)
- `src/corpus/versioning.py` (new)
- `src/corpus/__init__.py` (exports)
- `tests/unit/test_m10_3_normalize.py` (new)
- `project-state.yaml` (M10.3 binding block)
- `acceptance-m10.3.md` (this document)

---

## 11. Next

M10.4 (Derived Corpus Storage + Indexing, `migrate_10` → v10) is NOT started.
Do not begin M10.4 without explicit owner direction.
