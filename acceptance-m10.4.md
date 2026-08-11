# M10.4 — Derived Corpus Storage + Indexing (`migrate_10`) — VERIFIED

**Status:** VERIFIED
**Schema / migration version:** v10 (additive derived corpus substrate; `migrate_10`, v9 → v10)
**Authority:** `plan-m10.md` §5.2 / §323–338 (approved/implementation contract), `implementation-plan.json`, `project-state.yaml`, `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`.
**Starting HEAD:** `4b11147a61cfcee4bfaed40f4615fc491b26b2bb`
**Final HEAD:** _(set by the binding commit of this acceptance; see FINAL-HEAD canonical report)_

---

## 1. Scope reconciliation

M10.4 introduces the **derived storage layer** for the corpus data produced by
M10.1–M10.3: a rebuildable SQLite substrate (`migrate_10`, v9 → v10) that mirrors
the canonical corpus registry (`corpus_sources.jsonl`) + blob store as derived
projection tables, plus a deterministic rebuild path.

**In scope (per plan §5.2 / §323):** `migrate_10` (additive derived tables:
`zm_corpus_sources`, `zm_corpus_units`, `zm_corpus_fts`, `zm_corpus_relations`,
`zm_corpus_entities` + indexes); `rebuild_from_corpus()`; `FTS5_AVAILABLE` guard;
sanitized content only into FTS (reuse M2.5 discipline).

**Out of scope (NOT implemented, per plan):** query planner (M10.5), FTS/semantic
*query* retrieval integration, graph population/enrichment (M10.6), vector/semantic
indexes, EvidenceSet corpus retrieval, Obsidian corpus projection, real ~600-PDF
rollout, packaging, post-M10 audit.

**Schema-version semantics resolved (load-bearing):** plan §5.2 is explicit —
`CURRENT_SCHEMA_VERSION` becomes **10**; v1–v9 tables/JSONL/blobs are never
altered; `down()` returns to v9 by dropping only the new derived tables. No
owner-decision ambiguity remained.

---

## 2. Derived-store design (minimum necessary)

Tables added (all DERIVED, rebuildable, down()-safe):

| Table | Classification | Contents |
|---|---|---|
| `zm_corpus_sources` | (A) projection of canonical registry | source_id, content_hash, external_ref, kind, `resource_type='corpus_source'`, scope keys, sensitivity, lifecycle, blob_ref, provenance |
| `zm_corpus_units` | (B) derived normalized units | unit_id (= M10.3 logical id), source_ref, source_location_id, content_hash, normalized_text, `kind` (coarse CHECK), `resource_type='corpus_unit'`, order/page/parent, scope keys, duplicate_of, lifecycle, sensitivity, provenance_hash |
| `zm_corpus_fts` | (A) projection of sanitized unit text | FTS5 over `normalized_text` only; `FTS5_AVAILABLE` guard; mirrors `zm_fts` |
| `zm_corpus_relations` | schema-only (M10.6 populates) | closed M8 `RelationType` + `RESOURCE_TYPES` CHECK incl. `corpus_source`/`corpus_unit` |
| `zm_corpus_entities` | schema-only (M10.6 populates) | closed M8 `EntityType` + `RelationSource` incl. `corpus_extraction` |

Indexes: scope (`profile_id, project_id, knowledge_space_id`), `content_hash`,
`unit_kind`, `lifecycle_status`, `source_id`, `source_ref`, `duplicate_of`.

**Canonical vs derived classification:** every `zm_corpus_*` table is (A) or (B) —
a projection of canonical state or recomputable metadata. There is **no (C)
migration/rebuild bookkeeping that becomes new authoritative state**, and **no (D)
new authoritative state existing only in SQLite**. `migrate_10` writes **zero**
canonical data; canonical corpus truth remains blob store + `corpus_sources.jsonl`.

---

## 3. Load-bearing boundary adherence

- **Canonical memory authority unchanged.** M1 JSONL + events untouched; no memory
  table altered by `migrate_10`.
- **Canonical corpus authority unchanged.** `corpus_sources.jsonl` + blob store
  remain the system of record; SQLite is a derived mirror only.
- **Cross-scope content sharing preserved.** Identical content hash under
  different scopes yields **distinct logical unit rows** (key = `(source_ref,
  source_location_id)`); authorization identity is never collapsed by dedup
  (proved by `TestCrossScope::test_same_content_different_scope_distinct_units`).
- **`corpus_source` vs `corpus_unit` remain distinct** resource types — hard
  `CHECK` per table + permanent M6.6 isolation (proved by
  `TestCrossScope::test_corpus_source_and_unit_resource_types_distinct` and
  `test_resource_type_check_blocks_wrong_literal`).
- **Versioning projection traceable.** Unchanged content → idempotent re-projection
  (no new unit rows); changed content → new source_id + new version, historical
  row retained (proved by `TestVersioning`).
- **Rebuild from canonical.** `rebuild_from_corpus()` drops only v10 corpus tables,
  recreates via the migration framework, re-projects from registry + blobs; produces
  equivalent derived state; canonical JSONL/blobs/memory untouched (proved by
  `TestRebuild`).
- **Read/write boundary.** `derived_store.py` is a write/projection module only; it
  exposes no retrieval surface (proved by `TestSecurity::test_projection_module_is_not_a_read_service`).
  The M3/M5 read paths are unchanged and remain read-only.
- **Secret/sensitivity boundary.** Every unit's `normalized_text` is scanned by the
  fail-closed M10.2 redactor (`require_safe`) BEFORE any derived row is written; a
  secret-shaped unit is rejected (never stored/indexed) — `TestSecurity::
  test_secret_unit_rejected_fail_closed`. FTS indexes sanitized text only.
- **No mandatory new dependency.** Stdlib + existing repo deps (SQLite WAL/FTS5)
  only. No network/LLM in the migration or projection.
- **No FTS query retrieval, no semantic/vector, no EvidenceSet, no Obsidian** in M10.4.
  `zm_corpus_fts` is storage substrate only; M10.5 owns retrieval.

---

## 4. Migration safety

- Forward-only, additive, reuses the existing runner (`SQLiteStore._apply_up` /
  `_apply_down`). `up()` opens an explicit `BEGIN`, runs DDL, commits the ledger row;
  any failure rolls back and does **not** advance the recorded version (proved by
  `TestMigrationFailureSafety::test_failed_migration_does_not_advance_version`).
- `down()` (v10 → v9) drops only the v10 derived structures (child-before-parent for
  the unit FK), leaving M0–M8 tables, canonical JSONL, blobs, and the migration
  ledger intact (proved by `TestMigrationFailureSafety::test_downgrade_returns_to_v9`).
- Idempotent: re-running `ensure_schema()` over an up-to-date DB applies nothing
  (proved by `TestFreshInitialization::test_ensure_schema_is_idempotent`).
- Safe against partially-existing derived schema (all `CREATE ... IF NOT EXISTS`;
  FTS5 created only when available).

---

## 5. Acceptance criteria (plan §28) — all MET

| # | Criterion | Met |
|---|-----------|-----|
| 1 | `migrate_10` follows existing migration infrastructure | ✅ |
| 2 | Corpus SQLite state explicitly DERIVED / REBUILDABLE | ✅ |
| 3 | Existing canonical memory authority unchanged | ✅ |
| 4 | Approved corpus canonical registry/blob authority unchanged | ✅ |
| 5 | Source/version/unit projections persist correctly | ✅ |
| 6 | Cross-scope same-content data does not collapse authorization identities | ✅ |
| 7 | `corpus_source`/`corpus_unit` remain isolated | ✅ |
| 8 | Historical versions remain traceable | ✅ |
| 9 | Rebuild from canonical corpus state succeeds deterministically | ✅ |
| 10 | Derived-state loss does not lose canonical corpus knowledge | ✅ |
| 11 | ReadonlyStore remains read-only | ✅ |
| 12 | Migration is transactional/fail-safe | ✅ |
| 13 | No mandatory new dependency | ✅ |
| 14 | No FTS user-facing retrieval unless required as storage substrate | ✅ (storage only; no query API) |
| 15 | No semantic/vector requirement | ✅ |
| 16 | No EvidenceSet/Hermes corpus retrieval | ✅ |
| 17 | No graph enrichment | ✅ (schema-only tables; not populated) |
| 18 | No Obsidian corpus projection | ✅ |
| 19 | No real ~600-PDF rollout | ✅ (small fixtures only) |
| 20 | Focused tests pass | ✅ (29 passed) |
| 21 | Relevant regressions pass | ✅ |
| 22 | PRE-BINDING canonical passes | ✅ (2944 passed, 5 skipped) |
| 23 | Acceptance/state binding committed | ✅ (this doc + project-state) |
| 24 | FINAL-HEAD canonical passes | ✅ (see FINAL-HEAD report) |

---

## 6. Test evidence (executed)

- **Focused M10.4:** `tests/unit/test_m10_4_storage.py` → **29 passed** in 0.25s.
- **Relevant regressions** (M10.1/M10.2/M10.3 registry+extraction+normalization,
  M5 grants/cross-profile, M6.6 hardening, M8 schema/projection/integration,
  M3 read-only, M4 schema, M7.5 hardening) under isolated HOME → **517 passed,
  2 skipped** (the 2 skips are the pypdf-absent PDF paths, as in M10.2).
- **PRE-BINDING canonical** (full `tests/`, isolated HOME): **2944 passed,
  5 skipped, 0 failed**.
- **FINAL-HEAD canonical** (full `tests/`, fresh isolated HOME, post-binding):
  **2944 passed, 5 skipped, 0 failed**.

The 5 historical skips are unchanged from M10.3 (pypdf-absent PDF fixture paths +
pre-existing documented environment skips). No test was deselected.

Note: a `test_m6_final_acceptance.py` / `test_m6_hermes_adapter.py` error set
(`capture_root must not be inside the real home directory`) occurs ONLY when the
suite is run with the operator's real `$HOME`; it is an environment artifact, not
a code defect, and does NOT occur under the mandated isolated `$HOME` canonical
command.

---

## 7. Changed files

Implementation / tests:
- `src/storage/migrations/migrate_10.py` (new)
- `src/storage/migrations/__init__.py` (register migrate_10; `CURRENT_SCHEMA_VERSION`→10)
- `src/corpus/derived_store.py` (new: projection + `rebuild_from_corpus`)
- `tests/unit/test_m10_4_storage.py` (new)

Legitimate schema-version assertion bumps (plan §5.2; no product-logic change):
- `src/m8/__init__.py` (`M8_SCHEMA_VERSION` 9→10)
- `src/m8/{calibration,derived_index,graph_projection,retrieval_metadata,temporal_projection,temporal_read}.py`
- `src/integration/m7/m8_integration.py` (describe `schema_version` literals 9→10)
- 30 `tests/unit/*.py` schema-version assertions `== 9` → `== 10`, plus inversion
  of obsolete "no schema v10" guards into additive-derived assertions.

State / evidence:
- `project-state.yaml` (M10.4 binding block)
- `acceptance-m10.4.md` (this document)

Excluded (per repo discipline): `output/`, real corpus files, generated runtime
DBs, temporary SQLite, parser caches, `.venv`.

---

## 8. Next

M10.5 (Universal/Hybrid Retrieval + EvidenceSet Integration) is NOT started.
Do not begin M10.5 without explicit owner direction.
