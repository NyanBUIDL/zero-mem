# M10.1 — Corpus Source Registry + Authorization Boundary (implementation sub-plan)

**Status:** IN PROGRESS (smallest coherent increment of approved M10).
**Parent plan:** `plan-m10.md` (APPROVED / IMPLEMENTATION CONTRACT, owner-approved).
**Schema:** v9 (no migration; `migrate_10` belongs to M10.4).
**HEAD at start:** `97950e8929cc976a4ded373c05bc00fcd47f4cfc`

This document is the focused implementation plan for M10.1 only. It does NOT
change M10 scope, canonical authority, authorization order, resource_type
decisions, zero-LLM core, optional-semantic requirement, the 7-increment
structure, or the deferred-Obsidian decision. Any material architectural
deviation requires explicit owner review (per the approved plan §10).

## 1. Objective

Establish the corpus source identity/registry contract and wire corpus under the
existing M5 authorization boundary from the first increment — no bypass, no
parallel unrestricted RAG path. No actual document bytes are ingested.

## 2. Exact scope

1. Corpus source identity + registry contract (deterministic, content-addressed).
2. Two new M5 authorization resource types: **`corpus_source`** and **`corpus_unit`**.
3. M5 `_VALID_RESOURCE_TYPES` integration (mirror into M8 `RESOURCE_TYPES`).
4. M6.6 isolation regression proving the two corpus types (and vs event/artifact)
   do not leak across one another.
5. Source-level provenance/identity contracts (content hash, version identity,
   unchanged-source detection) — deterministic, zero LLM.
6. The registry is append-first JSONL (`corpus_sources.jsonl`) per the approved
   canonical/derived direction; **NO blob bytes are stored in M10.1** (blob store
   + artifact wiring is M10.2/M10.4). M10.1 only records source identity metadata
   and provenance; the `blob_ref`/path is a declared-but-unpopulated field.

## 3. Out of scope (hard)

- No PDF/actual ingestion (M10.2).
- No extraction / normalization / dedup / versioning of content (M10.3).
- No FTS / lexical retrieval (M10.4/5).
- No semantic/vector embeddings (M10.5, optional).
- No graph enrichment (M10.6).
- No `migrate_10` / derived SQLite tables (M10.4).
- No Obsidian projection (deferred, not part of M10).
- No corpus content reaches memory JSONL (MEMORY != CORPUS invariant).

## 4. Reuse (load-bearing, do not reinvent)

- **M5 contracts** `src/access/contracts.py::_VALID_RESOURCE_TYPES`,
  `AccessRequest` (carries `resource_type`, `resource_id`), `AllowedScope`,
  `AccessDecision`.
- **M5 policy** `src/access/policy.py::evaluate` — unchanged; new resource types
  flow through the existing validation (`resource_type` must be in
  `_VALID_RESOURCE_TYPES`).
- **M5.3 grants** `src/access/grants.py::AuthorizedReadGrant` /
  `compose_effective_scope` — already supports `resource_types` restriction per
  project; corpus types inherit this with no change.
- **M8 vocabulary** `src/m8/vocabulary.py::RESOURCE_TYPES` — kept in exact sync
  with M5 via `tests/unit/test_m8_1_contracts.py::test_resource_type_mirror`
  (`RESOURCE_TYPES == frozenset(_VALID_RESOURCE_TYPES)`). Adding two types to
  **both** sets keeps the equality test green (verified: no test hard-codes the
  resource-type count).
- **M8 identity** `src/m8/identity.py::content_hash` — deterministic sha256
  content hash; reuse for source identity hashing.
- **Append-only JSONL** `src/storage/jsonl_capture.py::JsonlCaptureStore` pattern
  (0o600/0o700, fsync, duplicate-by-event_id and duplicate-by-content_hash) —
  mirror the append/checkpoint discipline for `corpus_sources.jsonl` (registry
  store, NOT memory envelope; a new registry store class, not a memory event).
- **Config-root discipline** `src/projection/config.py` / `src/integration/
  bridge_config.py::_resolve_identity`: explicit-arg → env var (`ZERO_MEM_CORPUS_ROOT`)
  → project-local `config/` file → None. NO username/`$HOME`/repository-relative
  default. Fully portable.
- **Artifact-store metadata pattern** `src/storage/ingest.py` (`zm_artifacts`
  metadata row with `content_hash`, `kind`, `stored_path`): M10.1's registry
  record mirrors this metadata shape (declares `blob_ref`/`stored_path` without
  populating bytes yet).

## 5. New product modules / files

- `src/corpus/__init__.py`
- `src/corpus/registry.py` — `CorpusSourceRegistry` (append-first `corpus_sources.jsonl`
  + in-memory index by `source_id` and `content_hash`); `register_source(...)`
  returns identity (source_id, content_hash, version identity); idempotent append
  (duplicate-by-source_id and by-content_hash). Pure, zero LLM.
- `src/corpus/identity.py` — `compute_source_hash(...)` reusing `m8.identity.content_hash`;
  `source_id` derivation; version-identity helper (unchanged-source detection).
- `src/corpus/contracts.py` — closed `CorpusSourceRecord` dataclass (source_id,
  content_hash, resource_type="corpus_source", scope fields profile_id/
  project_id/knowledge_space_id, sensitivity, lifecycle_status, created_at,
  provenance, blob_ref=None). CLOSED enum; unknown value fails closed.
- `src/access/contracts.py` — add `"corpus_source"`, `"corpus_unit"` to
  `_VALID_RESOURCE_TYPES`.
- `src/m8/vocabulary.py` — add `"corpus_source"`, `"corpus_unit"` to `RESOURCE_TYPES`
  (mirror).

## 6. Authorization wiring (no bypass)

- Every future corpus read MUST route through `AuthorizedReadService`
  (`src/access/authorized_read.py`) with `resource_type="corpus_source"` (or
  `"corpus_unit"`). M10.1 does not add a query method yet (no rows exist), but the
  resource types are registered so M10.5's `query_corpus_sources` will reuse the
  existing facade unchanged.
- M5.3 `covers_resource` already enforces per-type restriction: a grant scoped to
  `corpus_source` MUST NOT authorize `corpus_unit`, `event`, `artifact`, or any
  other type (Q1 owner decision enforced by the existing `resource_types` filter).
- Unauthorized corpus resource has ZERO influence (authorization-before-influence
  invariant §3.1 of the parent plan).

## 7. Provenance / identity contract

- `source_id` = deterministic from (content_hash, scope) where applicable.
- `content_hash` via `m8.identity.content_hash` over the source descriptor.
- Unchanged-source detection: re-registering identical bytes yields the same
  content_hash → idempotent (no duplicate append).
- Version identity: a source_id + content_hash pair identifies a source version;
  re-ingestion of a changed source later (M10.3) produces a new version row, never
  a silent overwrite (append-only).

## 8. Portability

- Corpus root resolved via explicit arg → `ZERO_MEM_CORPUS_ROOT` env →
  `config/corpus.yaml` (`corpus_root`) → None (unavailable = safe, silent). No
  `/home/<user>` or repo-relative default.
- No hard-coded username, machine path, or cloud dependency.

## 9. Expected tests (`tests/unit/test_m10_1_corpus_registry.py`)

- registry append is append-first and idempotent (by source_id and by content_hash).
- `compute_source_hash` deterministic; identical bytes → identical hash → no dup.
- closed `CorpusSourceRecord` rejects unknown lifecycle/resource type (fail closed).
- M5 `_VALID_RESOURCE_TYPES` now contains `corpus_source` + `corpus_unit`.
- M8 `RESOURCE_TYPES` mirror equality still holds (existing test stays green).
- M6.6 isolation regression: a grant scoped to `corpus_source` does NOT authorize
  `corpus_unit` / `event` / `artifact` (use `AuthorizedReadGrant` with
  `resource_types=["corpus_source"]` through `compose_effective_scope` +
  `_resource_allowed`). Symmetric: `corpus_unit` grant does not authorize
  `corpus_source`.
- config-root resolution: explicit wins; env wins over file; unconfigured → None.
- zero-LLM: no network/LLM import in `src/corpus/*`.

## 10. Regression gates

- M5/M6.6/M8 regressions green (run the full `tests/unit` for access + m8).
- The existing `test_m8_1_contracts.py::test_resource_type_mirror` must stay green
  (proves M5/M8 stay in sync).
- Pre-binding canonical (clean isolated HOME) then FINAL-HEAD canonical: 0 failed,
  3 historical skips only.
- M9 regressions untouched (corpus projection deferred).

## 11. Acceptance criteria (M10.1 VERIFIED gate)

- focused `test_m10_1_*` green;
- M5/M6.6/M8 regression green;
- pre-binding + FINAL-HEAD canonical green (0 failed, 3 historical skips only);
- state binding commits the M10.1 increment and records `m10_current_increment:
  m10_1` in `project-state.yaml` WITHOUT flipping `m10_status` away from
  `not_started` semantics incorrectly (M10 as a whole is still in-progress across
  increments; the approved convention uses per-increment tracking, not a single
  completed flag).
- no product code change outside the files listed in §5;
- schema remains v9 (no migration).

## 12. Implementation order

1. `src/access/contracts.py` + `src/m8/vocabulary.py` — add the two resource types
   (both sets, keep mirror test green).
2. `src/corpus/identity.py` (reuse `m8.identity.content_hash`).
3. `src/corpus/contracts.py` (closed record).
4. `src/corpus/registry.py` (append-first JSONL, config-root resolution).
5. tests (§9).
6. run focused + M5/M6.6/M8 regressions; run canonical under clean isolated HOME
   (pre-binding).
7. on green: commit; re-run canonical FINAL-HEAD; state binding; mark M10.1 done.
