# M10 — Universal External Knowledge Corpus (Planning)

**Status:** APPROVED — IMPLEMENTATION CONTRACT. M10 implementation has NOT started (M10.1 pending).

**Authority:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` (read the applicable sections before any implementation), `AGENTS.md`, `ARCHITECTURE.md`, `project-state.yaml`, `implementation-plan.json`, and the VERIFIED M1–M9 source tree.

**Scope of this document:** implementation-ready M10 plan only. It writes no product code, no tests, no migration, no schema change, binds no M10 state as started, ingests nothing, and creates no experimental database or corpus data.

---

## 1. State reconciliation

Performed at the start of this planning turn against live `git` and the state artifacts — no stale brief was trusted.

| Fact | Reconciled value |
| --- | --- |
| Repository root | `/home/brian-nguyen/Hermes Workplace/Zero-mem` |
| Branch | `master` |
| HEAD (exact, 40-char) | `7fcdf4bf9863c0a63a66941120f2906292c37b20` |
| HEAD subject | `test(state): align baseline with verified M9 binding` |
| Working tree | clean except pre-existing untracked `output/` (one Coin68 research note, unrelated to product; left untouched) |
| Schema version | **9** (`src/storage/migrations/migrate_9.py` is latest; `CURRENT_SCHEMA_VERSION == 9`; no v10 exists) |
| M1–M8 | VERIFIED (each increment has acceptance artifact + impl/tested commit) |
| M9.1–M9.6 | VERIFIED |
| M9 overall | VERIFIED (`m9_overall_status: "verified"`, `m9_next_incomplete_increment: "none"`) |
| Final M9 canonical (FINAL-HEAD, isolated HOME) | **2849 passed, 3 skipped, 0 failed** (recorded in `acceptance-m9.6.md` and `project-state.yaml`) |
| M10 | `m10_status: "not_started"` |
| Duplicate-key concern (memory: `fa46cf8` appended duplicate `m9_*` keys) | **Not present in current committed file** — `grep -c m9_status` == 1; `m9_status`/`m9_overall_status`/`m9_current_increment` each appear exactly once. State is clean. |
| Existing corpus/PDF/extraction/vector code | **None.** `grep -rln "pdf\|corpus\|extractor\|embed\|vector"` over `src/ tests/ scripts/` returns only unrelated substring hits (`render.py`, `links.py`). |

The short prefix `7fcdf4b` was **not** treated as identity; the full 40-character hash above was resolved from `git rev-parse HEAD`.

**Reconciliation result: PASS.** No `STATE RECONCILIATION REQUIRED` condition. M10 planning proceeds.

### 1.1 Load-bearing M1–M9 contracts M10 must preserve (verified by reading source)

- **M1** (`src/capture/event_types.py`, `src/storage/jsonl_capture.py`): append-only JSONL is canonical raw trace source of record; `sanitized_content` only ever reaches derived stores (M1 fail-closed redactor); secrets never persisted; `append/contains/write_dead_letter` stable interface.
- **M2** (`src/storage/ingest.py`, `src/storage/migrations/migrate_*.py`): SQLite is **derived, disposable, rebuildable**; idempotent ingestion by `event_id` + `sanitized_content_hash`; resumable checkpoint with consumed-prefix hash; sanitized `zm_ingest_log`; no retry/dead-letter in SQLite; `zm_fts` FTS5 over **sanitized** content only, with `FTS5_AVAILABLE` capability guard.
- **M5** (`src/access/contracts.py`, `policy.py`, `authorized_read.py`, `grants.py`, `resolver.py`): the **sole authorization authority**. Closed `AccessRequest`/`AllowedScope`/`AccessDecision`; closed `_VALID_RESOURCE_TYPES`; `requesting_profile_id` explicit (None stays None, never inferred); grants are opaque passthrough to the read service; authorization **before** any retrieval/ranking; fail-closed.
- **M6** (`src/integration/m6/`): read-only MCP projection of M5-authorized reads; **M6.6 resource_type isolation** — a grant scoped to one `resource_type` (e.g. `artifact`) must not leak events/relations/decisions of other types. Identity preserved verbatim.
- **M7** (`src/integration/m7/`): `MemoryRouteDecision` → `AuthorizedReadService` (M5) → eligibility gate (`eligibility.py`) → bounded `EvidenceSet` (5 primary + 3 supporting, token budget). No LLM/network/DB writes. `EvidenceSet` carries `m8_metadata` as DATA-only (no authority).
- **M8** (`src/m8/`): derived graph/temporal/calibration. Closed `RESOURCE_TYPES` (mirrors M5), closed `EntityType`/`RelationType`/`RelationSource` (no `inferred`/`llm` member). Derived tables are rebuildable; M5 remains sole authorizer; authorization-first bounded reads.
- **M9** (`src/projection/`): curated Obsidian projection only; **not** canonical. Three-signal ownership (containment + marker + manifest); sensitivity uses the ONE canonical `Sensitivity` vocabulary; `DEFAULT_PROJECTION_SENSITIVITY_CEILING = internal` (stricter than M7's `private`); secret never projects; `PROJECTION_VERSION` contract versioning; manifest is DATA only.

### 1.2 Benchmark anticipation already present (reuse, do not reinvent)

`benchmark-plan.json` B11–B13 already define a **`research_memory`** route with profile/knowledge-space isolation (`allowed_scopes: ["quant-trading"]`, "Isolated Quant search must not return Web3 evidence"). M10 corpus retrieval is the fulfillment of that already-specified, already-tested isolation contract. M10 must reuse the M7 route/authorization/scoping machinery and the M5 isolation guarantees rather than introduce a parallel path.

---

## 2. M10 problem definition

**Adds:** a *second canonical storage class* — a Universal External Knowledge Corpus — that ingests arbitrary-source documents (PDF, TXT, MD, HTML, DOCX, CSV, JSON, source code, logs, structured text) through a parser/adapter boundary, normalizes them into deterministic generic knowledge units, deduplicates and versions them, builds derived indexes (FTS, metadata, optionally graph/semantic), retrieves them through the **existing** authorization-first retrieval stack, and surfaces results to Hermes as bounded, authority-preserving evidence — reusing the M7 `EvidenceSet` contract.

**Does NOT replace:** memory (M1–M9). Conversations, decisions, tasks, project state, verification, preferences, observations, and agent history remain JSONL-canonical memory traces. **Document contents are never dumped into memory JSONL.** The corpus has its own canonical registry + content-addressed blob store, distinct from the M1 event stream.

**Explicitly out of scope for M10 core:** automatic memory injection of corpus content; any corpus bypass around M5/M6/M7; making Obsidian the corpus canonical store; finance- or PDF-specific behavior; hard dependency on any commercial API/cloud service.

---

## 3. Architecture fit (end-to-end logical flow)

```
external source file (PDF/TXT/MD/HTML/DOCX/CSV/JSON/code/log)
  │  (explicit/allowed origin; path-resolution discipline, no /home/<user> in code)
  ▼
SOURCE / ARTIFACT REGISTRY  (CANONICAL, append-only)
  ├─ content-addressed blob store  (sha256-addressed; large payloads live here)
  └─ corpus_sources.jsonl          (source_id, content_hash, origin, format,
                                     scope, sensitivity, lifecycle, version_chain)
  │  deterministic redaction boundary — src/corpus/redact.py
  │     (reuses M1 fail-closed rules + M9 non-disableable baseline; secret never stored/projected)
  ▼
PARSER / EXTRACTOR ADAPTERS  (per-format, pluggable; zero-LLM structural extraction)
  │  format → raw extraction record (deterministic; provenance to source)
  ▼
NORMALIZED CORPUS UNITS  (DERIVED, deterministic)
  │  unit_kind (closed coarse set) + free optional domain (untrusted, filter-only)
  │  global dedup by content hash; versioning/supersession (reuse M2 active-key)
  ▼
DERIVED INDEXES  (DERIVED, rebuildable — migrate_10 at M10.4)
  ├─ corpus metadata / unit tables
  ├─ corpus FTS5 (sanitized content only; capability-guarded)
  ├─ corpus relations / entities (reuse M8 closed vocabulary)
  └─ (optional, local-only) semantic vectors — never canonical
  ▼
AUTHORIZATION  (M5 AuthorizedReadService — SOLE authority; BEFORE any ranking)
  │  requesting_profile_id explicit; profile/project/knowledge_space/sensitivity/
  │  resource_type(corpus_source|corpus_unit)/grants; M6.6 isolation preserved
  ▼
RETRIEVAL QUERY PLANNER  (reuses M3 FTS, M5 auth, M6 MCP, M7 router, M8 graph/temporal)
  │  metadata filter | FTS | entity | graph | temporal | lifecycle | provenance | scope | version
  ▼
EvidenceSet  (M7 contract; corpus evidence as a bounded, DATA-only channel
  │           parallel to primary/supporting; same eligibility + authorization)
  ▼
HERMES  (final reasoning/action; memory remains DATA, not authority)
```

Memory and corpus meet **only** at the authorization + evidence layer. Their canonical storage semantics stay separated: memory = M1 JSONL event stream; corpus = blob store + `corpus_sources.jsonl`. All indexes on both sides are derived/rebuildable.

### 3.1 Authorization-routing invariant (load-bearing, no bypass)

This invariant is a hard contract, **not** guidance. **Every corpus read path — the M10.5 query planner, M10.6 graph reads, and any corpus projection (including any future deferred Obsidian projection reusing M9) — MUST route through `AuthorizedReadService` (M5). No code path may issue a direct SQLite/FTS/JSONL query to discover, rank, or expand corpus candidates outside M5.** The enforced order is:

```
corpus candidate discovery   (via M5 AuthorizedReadService — sole authority)
  → authorization            (M5 decision: allowed / deny with existence-leak-safe empty result)
  → authorized candidate set
  → ranking / retrieval influence  (FTS, semantic, graph, metadata, snippets)
  → EvidenceSet              (M7, bounded, DATA-only)
  → Hermes
```

Unauthorized/hidden corpus resources have **zero** influence on: ranking, semantic-similarity results, graph expansion, metadata weighting, snippets, and `EvidenceSet` construction. Authorization is **never** performed only after unrestricted ranking. Corpus co-location grants nothing; `resource_type` isolation (`corpus_source`/`corpus_unit`) remains enforced. This mirrors the M8.3 "no graph-derived auth" guard and is gated by a **static/regression test** (M10.1 + M10.5) that fails the build if a corpus read is performed without an M5 authorization boundary.

---

## 4. Canonical / derived data model

### CANONICAL (authoritative, append-first, provenance-preserving, NOT rebuildable from elsewhere)

1. **Content-addressed source blobs** — files stored by `sha256(content)` under a corpus artifact root. Large payloads live here (mirrors the existing artifact-store principle in `ARCHITECTURE.md §2`).
2. **`corpus_sources.jsonl`** — per-source canonical registry. One append-only record per source ingestion event:
   `source_id, content_hash, origin_ref, format, ingested_by, project_id, profile_id, knowledge_space_id, sensitivity, lifecycle_status, version, supersedes, created_at, provenance_blob`.
   Updates create a **linked** record (supersession), never a silent overwrite (mirrors M1/M2 lifecycle + M2.4 active-key).
3. **`corpus_ingest_log.jsonl`** — sanitized ingestion outcomes only (mirrors `zm_ingest_log`): `source_id, line/unit, outcome, diagnostic_code`. No raw payload, secret, or exception text.

### DERIVED (rebuildable from canonical sources via the frozen extractor)

- Normalized corpus units (deterministic function of source + format + extractor_version).
- Corpus FTS5 index (sanitized unit content only).
- Corpus metadata / unit index tables.
- Corpus relations / entities (reuse M8 `RelationType`/`EntityType`; `RelationSource` gains a `corpus_extraction` member — explicit, not `inferred`).
- (Optional) local semantic vectors — never canonical; rebuildable; absent is a safe state.

**Invariant:** dropping every derived corpus table and re-running the frozen extractor over `corpus_sources.jsonl` + blobs must reproduce an equivalent derived state. The source registry is the only corpus system of record.

### 4.1 Redaction / sanitization boundary (distinct from authorization)

Redaction and authorization are **separate** concerns (owner-review §B.2):

- **Authorization** (M5) decides whether a corpus resource *may influence* a request. It is enforced first (§3.1) and never after unrestricted ranking.
- **Redaction / sanitization** decides what *safe representation* may leave the storage boundary.

Boundary stages for corpus-derived text:

1. **Source bytes** — preserved verbatim as content-addressed blobs (canonical). Never mutated by redaction.
2. **Extracted text** — produced by adapters; passes through `src/corpus/redact.py`, which applies the **same M1 fail-closed redaction rules** plus the M9 non-disableable baseline (caller patterns *extend never replace*). Secret/sensitive content is redacted-or-rejected here; raw secrets are never persisted or indexed.
3. **Normalized units** — derived from already-sanitized extracted text.
4. **Indexed / searchable representation** — built only over sanitized unit content (mirrors `zm_fts` over `sanitized_content`); a policy-unsafe transform would be a defect.
5. **Rendered `EvidenceSet` content** — applies the final authorized + sanitized boundary; only authorized, non-secret corpus content reaches Hermes as DATA-only.

Both authorization **and** redaction may be required for a single corpus object.

---

## 5. Storage + indexing plan

### 5.1 Early increments (M10.1–M10.3): NO schema migration

M10.1 establishes the canonical registry (JSONL) + blob store + authorization contract. M10.2–M10.3 produce derived units in-memory / as derived JSONL, validated by focused tests. **v9 is untouched.** This mirrors the M8 pattern (M8.1 froze contracts + a v9 *foundation* before projection) and keeps risk low.

### 5.2 M10.4: `migrate_10` — DERIVED corpus tables only (additive, v9 → v10)

**Why v9 cannot safely represent the requirement:**
- The v1–v9 tables are the **memory** substrate (events, M4 project memory, M8 graph/temporal). Putting corpus units/FTS into them would (a) pollute memory semantics, (b) blur the canonical/derived line, (c) risk M6.6 isolation bleed.
- Corpus units are a *distinct* derived class. The repo's own precedent (M8.1 `migrate_9`) proves the correct shape: **additive derived tables, no alteration of prior tables, down() drops only the new derived structures**.

**What `migrate_10` adds (all DERIVED, additive, rebuildable, down()-safe):**
- `zm_corpus_sources` (metadata mirror of `corpus_sources.jsonl`; NOT canonical — rebuilt from JSONL).
- `zm_corpus_units` (normalized units; `unit_kind` closed CHECK; `domain` free-text column, never used for auth).
- `zm_corpus_fts` (FTS5 virtual table over **sanitized** unit content; `FTS5_AVAILABLE` guard; mirrors `zm_fts`).
- `zm_corpus_relations` / `zm_corpus_entities` (reuse M8 closed enum + `resource_type` CHECK including `corpus_source`/`corpus_unit`).
- Indexes on `(profile_id, project_id, knowledge_space_id)`, `content_hash`, `unit_kind`, `lifecycle_status`, `source_id`.

**Schema-version impact:** `CURRENT_SCHEMA_VERSION` becomes 10. v1–v9 tables, JSONL, and blobs are **never** altered. `down()` returns to v9 by dropping only the new derived tables.

**Canonical vs derived summary:** `migrate_10` writes **zero** canonical data. Canonical corpus truth remains the blob store + `corpus_sources.jsonl`.

---

## 6. Authorization + security plan

M10 introduces **no parallel authorization model.** It extends the existing sole authority (M5) and reuses M6.6 isolation.

1. **New closed resource types** added to `src/access/contracts.py::_VALID_RESOURCE_TYPES` (and mirrored into `src/m8/vocabulary.py::RESOURCE_TYPES` via the existing equality-assertion test):
   - `corpus_source` — the document-level object.
   - `corpus_unit` — the normalized unit-level object.
   Two distinct types preserve M6.6 fidelity (a `corpus_source` grant must not leak `corpus_unit` neighbors, and neither leaks `event`/`artifact`).
2. **Wire corpus reads into `AuthorizedReadService`** exactly as M4 handlers were wired (M9.2 pattern): a `corpus_source` / `corpus_unit` read method that builds an `AllowedScope`, consults grants, returns authorized items only. Hidden/unauthorized resources have **zero** influence on FTS/semantic/graph/metadata ranking.
3. **Authorization BEFORE retrieval** — every corpus query path routes through M5 first; a denial yields an empty, existence-leak-safe result (reuse M8.3 discipline).
4. **Sensitivity / secret fail-closed** — corpus units carry the canonical `Sensitivity` vocabulary. Secret-shaped content is redacted/rejected at the **extraction boundary** by reusing the M1 fail-closed redactor; the M9 engine content-backstop discipline (non-disableable baseline, caller patterns extend never replace) is reused for any corpus→projection path. `secret` never projects.
5. **Scope enforcement** — `profile_id` / `project_id` / `knowledge_space_id` on every source/unit; `RESEARCH`-route retrieval is scoped by these (fulfills `benchmark-plan.json` B11–B13 isolation).
6. **No identity inference** — `requesting_profile_id` explicit; paths/cwd/content never read as identity (reuse `BridgeConfig._resolve_identity` discipline).
7. **Path safety** — corpus blob root resolved explicitly/config-only (no `/home/<username>`, no `Path.home()` discovery, no cwd fallback); `safe_reference` enforcement (absolute/traversal/secret rejected) reused from M4.5/M9.
8. **Security regression gates (mandatory):** M5/M6.6/M7/M8 regressions must stay green whenever auth or resource_type changes.

### 6.1 Authorization-routing invariant (enforced, no bypass)

Corpus retrieval MUST NOT create an authorization bypass or a parallel unrestricted RAG path. The invariant in §3.1 is load-bearing: corpus candidate discovery, ranking influence, graph expansion, and snippet rendering all occur **only after** an `AuthorizedReadService` decision. M10 reuses the existing M5/M6/M7 security model verbatim — there is **no weaker parallel authorization model**. A static/regression gate (test asserts no corpus read reaches SQLite/FTS/JSONL except through `AuthorizedReadService`) is part of M10.1 acceptance and re-checked at M10.5.

---

## 7. Zero-LLM / optional-AI boundary

### CORE / ZERO-LLM (must work deterministically, no model, no network)
- hashing (sha256), source identity, change detection, incremental ingestion (hash skip), structural extraction (parser/regex based), normalization, deterministic chunk/unit construction, dedup (exact + normalized-hash near-dup), versioning, metadata indexing, provenance, **lexical/FTS retrieval**, lifecycle handling, **authorization (M5)**, **deterministic rebuild**.

### OPTIONAL AI ENRICHMENT (never required to rebuild or access the basic corpus)
- semantic labeling, summarization, entity extraction, relationship inference, classification, advanced synthesis, **semantic/vector retrieval**.
- Implemented as a **separate, non-blocking enrichment pass** that writes only derived enrichment metadata (mirrors `m8_metadata` DATA-only discipline). It never alters canonical records, never changes authorization, never promotes a corpus unit to "verified fact," and degrades gracefully (failure → corpus still fully usable via zero-LLM path).
- If semantic retrieval is implemented, it uses **local-only** embeddings (the M0-listed BGE-M3/multilingual local option) as an **optional** adapter; vectors are never canonical; absence is a safe state. **No commercial API or cloud service is mandated.**

---

## 8. Ingestion / normalization / dedup / versioning plan

### Identity scheme
- **source identity** = `sha256(normalized_bytes)` → exact-duplicate detection (renamed copy, re-saved byte-identical → same source_id).
- **artifact identity** = `(project_id, content_hash)` (content-addressed blob).
- **extraction identity** = `(source_hash, format, extractor_version, section_path)` — deterministic.
- **normalized unit identity** = `(extraction_id, unit_index)` — deterministic + `content_hash(unit)` for dedup.
- **version** = new `content_hash` → new version; prior version linked via `supersedes` (reuse M2 active-key + M8 `SUPERSEDES` relation). No silent overwrite.

### Dedup
- **exact file dup** → single source registry entry; subsequent ingests record a link, not a copy.
- **same content, different format** → same `content_hash` → collapsed at source level.
- **duplicate paragraphs/chunks** → dedup at normalized-unit level by `content_hash(unit)`; one retained unit, others carry `duplicate_of`.
- **revised editions / overlapping docs / source updates** → version chain; old version retained (provenance), new version active.
- **deleted/archived source** → lifecycle `deleted`/`archived` (logical, like M2.6); blobs retained for provenance; units excluded from active retrieval.

### Incremental ingestion
- Resumable checkpoint + consumed-prefix hash (reuse M2 `zm_ingest_checkpoint` / `PrefixHasher` discipline). Unchanged content **skipped** via `content_hash` comparison → routine re-ingest is O(changed), not O(N).

---

## 9. Retrieval plan

Hybrid retrieval over a potentially large heterogeneous corpus, **reusing existing Zero-Mem components**:

| Mechanism | Reuse |
| --- | --- |
| Metadata filters / scope / provenance | M5 `AllowedScope` + M2/M4 filters |
| Lexical / FTS | M3 `search.py` pattern + `zm_corpus_fts` (migrate_10) |
| Entity lookup | M8 `zm_entities` (+ corpus entities) |
| Graph traversal | M8 `graph_access.py` (authorization-first, bounded) |
| Temporal | M8 `temporal_read.py` |
| Lifecycle / status | M2 lifecycle projection |
| Version selection | corpus version chain |
| Authorization | M5 `AuthorizedReadService` (sole authority) |

**Query planner:** chooses an appropriate path (or combination) rather than always running every mechanism — e.g. scoped FTS for keyword need, graph expansion for relation need, metadata filter for known identity. Selection is deterministic and authorization-first.

**EvidenceSet integration:** corpus results merge into the existing M7 `EvidenceSet` as a **bounded, DATA-only parallel channel** (`corpus_evidence`), subject to the *same* M5 authorization + M7 eligibility gates. It never promotes corpus to memory authority; `m8_metadata`-style DATA-only discipline applies. Memory routes/evidence remain intact; corpus is additive.

**Authorization-routing invariant (§3.1) applies to every retrieval path:** corpus candidates are discovered only through `AuthorizedReadService`; FTS, semantic, graph, metadata, and snippet influences are computed over the authorized set only. The query planner selects mechanisms deterministically but never selects a path that bypasses M5.

---

## 10. M10 increment plan

A possible starting hypothesis was given in the prompt (M10.1–M10.7). Based on the **actual repository architecture**, I propose the following coherent sequence. Deviations from the hypothesis and why:

- **Pull authorization to M10.1** (not later): §9 forbids any corpus bypass around M5/M6/M7, so corpus must be authorization-wrapped from the first increment.
- **Defer `migrate_10` to M10.4** (not M10.1): freeze canonical model + extraction contracts first (M8.1 pattern); early increments need no SQLite change.
- **Corpus-specific Obsidian projection is DEFERRED OUTSIDE M10** (owner decision Q5: OPTION B) and is NOT an M10 increment. M10 is a 7-increment sequence (M10.1–M10.7); there is no M10.8. Corpus functionality does not depend on Obsidian projection (M9 remains the verified human-facing projection system).
- **Reuse the `RESEARCH` route** for corpus retrieval (benchmark B11–B13 already specify it), rather than inventing a divergent path.

---

### M10.1 — Corpus Source Registry + Authorization Boundary

1. **Objective:** Establish the canonical corpus source registry and wrap corpus under the existing M5 authorization from day one.
2. **Exact scope (as delivered in VERIFIED M10.1):** `corpus_sources.jsonl` registry (append-first, content-addressed, idempotent, provenance-preserving) via `src/corpus/registry.py`; `CorpusSourceRecord` closed contract (`src/corpus/contracts.py`); deterministic identity/hashing reusing `src/m8/identity.content_hash` (`src/corpus/identity.py`); add `corpus_source` + `corpus_unit` to M5 `_VALID_RESOURCE_TYPES` (mirrored into M8 `RESOURCE_TYPES` with the existing equality test); portable corpus-root resolution (explicit → `ZERO_MEM_CORPUS_ROOT` → `config/corpus.yaml`); zero-LLM; NO schema migration. NOTE: M10.1 delivers the registry + auth resource types + M6.6 isolation proof, but does NOT add corpus read handlers to `AuthorizedReadService` yet (no corpus rows exist until M10.2/3/4); the authorization path is proven at the facade's `_resource_allowed` enforcement point. The blob store + `corpus_ingest_log.jsonl` belong to M10.2/M10.4, not M10.1.
3. **Out of scope:** extraction, normalization, FTS, retrieval, projection, blob storage.
4. **M1–M9 reused:** M1 append-only + redactor (boundary principle); M2 idempotence/checkpoint discipline; M5 policy/grants; M6.6 isolation; M8 vocabulary mirror.
5. **Product modules/files:** `src/corpus/__init__.py`, `src/corpus/contracts.py`, `src/corpus/identity.py`, `src/corpus/registry.py`; `src/access/contracts.py` (resource-type add); `src/m8/vocabulary.py` (mirror); `tests/unit/test_m10_1_corpus_registry.py`.
6. **Expected tests:** registry append/idempotence/checkpoint; content-hash identity + exact-dup collapse; scope/sensitivity/lifecycle fields; M5 authorization (resource-type registration + fail-closed unknown type); M6.6 isolation (corpus grant does not leak corpus_unit/event/artifact); portable root resolution; zero-LLM import guard.
7. **Schema implications:** none (v9 unchanged).
8. **Security implications:** extends sole authority; mandatory M5/M6.6/M8 regression.
9. **Canonical vs derived:** registry JSONL = canonical; no derived yet.
10. **Acceptance criteria (MET — VERIFIED):** focused green (28 passed); M5/M6.6/M8 regression green (258 passed combined); pre-binding + FINAL-HEAD canonical green (2869 passed, 3 skipped, 0 failed) under clean isolated HOME.
11. **Regression suites:** M5, M6.6, M8.
12. **Rollback/rebuild:** JSONL is append-only canonical; registry rebuildable by replay.
13. **Evidence before VERIFIED:** `acceptance-m10.1.md`; focused + regression + canonical results.
14. **Commit boundary:** impl + tested + state/plan-binding commits; `m10_current_increment_status: verified` recorded.

### M10.2 — Multi-format Ingestion + Structural Extraction (initial adapters: PDF + TXT)

1. **Objective:** Ingest multiple source formats through a pluggable parser/adapter boundary; structurally extract content deterministically.
2. **Exact scope:** `FormatAdapter` protocol (closed format registry: pdf, txt, md, html, docx, csv, json, code, log); **PDF + TXT adapters first** (PDF via an *optional* parser dependency, see §15); extraction → raw extraction record (text + structure: sections/paragraphs/tables/figures/metadata) with provenance to source; failure/quarantine/unsupported handling; secret scan on extracted text via `src/corpus/redact.py` (reuses M1 fail-closed rules + M9 non-disableable baseline). **No finance/PDF-specific logic.**
3. **Out of scope:** normalization/dedup/versioning (M10.3), FTS/retrieval (M10.4/5).
4. **M1–M9 reused:** M1 redactor (secret boundary); M2 failure classification + `IngestionOutcome` shape; M9 content-backstop discipline.
5. **Product modules/files:** `src/corpus/adapters/__init__.py`, `base.py`, `pdf.py`, `txt.py`, `registry.py`; `src/corpus/extract.py`; `src/corpus/redact.py` (explicit redaction adapter: M1 fail-closed rules + M9 non-disableable baseline, applied to extracted corpus text); `tests/unit/test_m10_2_adapters.py`, fixtures (sample PDF/TXT, corrupt, unsupported).
6. **Expected tests:** each adapter extracts deterministic structure; corrupt → quarantined (not admitted); unsupported format → rejected with reason; secret in source → redacted/rejected; provenance links extraction→source.
7. **Schema implications:** none (derived extraction kept in-memory / derived JSONL).
8. **Security implications:** secret fail-closed at boundary; unsupported-content handled without crash/leak.
9. **Canonical vs derived:** source blobs canonical; extraction record derived.
10. **Acceptance criteria:** focused green; M1/M2 security regression green; canonical green.
11. **Regression suites:** M1 (secret scan), M2 (failure handling), M5 (no auth change but guard).
12. **Rollback/rebuild:** re-extract from canonical blobs.
13. **Evidence before VERIFIED:** focused + regression + canonical results.
14. **Commit boundary:** separate impl/tested/binding commits.

### M10.3 — Normalization + Deduplication + Versioning

1. **Objective:** Turn raw extraction into deterministic normalized corpus units; dedup globally; version/supersede.
2. **Exact scope:** normalization rules (whitespace/Unicode/structure canonicalization); unit construction (`unit_kind` closed **COARSE structural set ONLY**: section, paragraph, table, code, heading, list, figure, metadata — no semantic classes such as definition/fact/claim/reference); global dedup by `content_hash(unit)`; version chain + `supersedes` (reuse M2 active-key + M8 `SUPERSEDES`); incremental re-ingest hash-skip. **Semantic subtypes (definition/fact/claim/reference) are NOT canonical in M10.3; they remain optional derived enrichment in M10.6 and must not be required for basic access/rebuild.**
3. **Out of scope:** SQLite persistence (M10.4), retrieval (M10.5), AI enrichment (M10.6).
4. **M1–M9 reused:** M2 idempotence + active-key supersession; M8 `RelationType`/`RelationSource`; M2 lifecycle.
5. **Product modules/files:** `src/corpus/normalize.py`, `src/corpus/dedup.py`, `src/corpus/versioning.py`; `tests/unit/test_m10_3_normalize.py`.
6. **Expected tests:** deterministic normalization (same input → same units); exact + near (normalized-hash) dedup; version chain correctness; re-ingest skips unchanged; deleted/archived handling.
7. **Schema implications:** none yet (units derived JSONL/in-memory).
8. **Security implications:** none new; provenance preserved on every unit.
9. **Canonical vs derived:** units derived; source registry canonical.
10. **Acceptance criteria:** focused green; M2/M8 regression green; canonical green.
11. **Regression suites:** M2, M8.
12. **Rollback/rebuild:** rebuild units from canonical sources.
13. **Evidence before VERIFIED:** focused + regression + canonical.
14. **Commit boundary:** separate commits.

### M10.4 — Derived Storage + Indexing (`migrate_10`)

1. **Objective:** Persist normalized units + FTS + indexes as derived, rebuildable v10 tables.
2. **Exact scope:** `migrate_10.py` (additive derived tables: `zm_corpus_sources`, `zm_corpus_units`, `zm_corpus_fts`, `zm_corpus_relations`, `zm_corpus_entities` + indexes); `rebuild_from_corpus()`; `FTS5_AVAILABLE` guard; sanitized content only into FTS (reuse M2.5 discipline).
3. **Out of scope:** query planner (M10.5), enrichment (M10.6).
4. **M1–M9 reused:** M2.5 FTS pattern; M8 entity/relation vocabulary + derived-projection discipline; M2 rebuild.
5. **Product modules/files:** `src/storage/migrations/migrate_10.py`, `src/corpus/derived_store.py`; `tests/unit/test_m10_4_storage.py`.
6. **Expected tests:** migrate up/down (v9↔v10); rebuild equivalence; FTS capability guard; no prior-table alteration; `down()` returns to v9.
7. **Schema implications:** **v10 introduced (derived only).** Justification in §5.2.
8. **Security implications:** FTS over sanitized content only; no secret leakage.
9. **Canonical vs derived:** all M10.4 tables derived; blob + `corpus_sources.jsonl` canonical.
10. **Acceptance criteria:** focused green; M2/M5/M8 regression green; canonical green; schema v10 verified.
11. **Regression suites:** M2 (storage/path), M3 (read-only), M5, M8.
12. **Rollback/rebuild:** `down()` to v9; full rebuild from canonical.
13. **Evidence before VERIFIED:** focused + regression + canonical + schema-version check.
14. **Commit boundary:** migrate + store + tests + binding.

### M10.5 — Universal / Hybrid Retrieval + EvidenceSet Integration

1. **Objective:** Retrieve corpus through the existing authorization-first stack and merge into `EvidenceSet`.
2. **Exact scope:** query planner (metadata | FTS | entity | graph | temporal | lifecycle | provenance | scope | version); corpus read via M5; results → bounded `corpus_evidence` channel in `EvidenceSet` (DATA-only, same auth + eligibility); reuse `RESEARCH` route; optional local semantic adapter (never required).
3. **Out of scope:** AI enrichment (M10.6).
4. **M1–M9 reused:** M3 `search.py` (FTS), M5 `AuthorizedReadService`, M6 MCP read-only, M7 router + `evidence_builder.py` + `eligibility.py`, M8 graph/temporal.
5. **Product modules/files:** `src/corpus/retrieval.py`, `src/corpus/query_planner.py`, `src/integration/m7/evidence_builder.py` (corpus channel extension); `tests/unit/test_m10_5_retrieval.py`.
6. **Expected tests:** authorization-before-ranking; hidden resource zero influence; FTS + metadata + (optional) graph paths; EvidenceSet corpus channel bounded + DATA-only; benchmark B11–B13 isolation holds for corpus.
7. **Schema implications:** none new (uses M10.4 tables).
8. **Security implications:** mandatory M5/M6.6/M7/M8 regression.
9. **Canonical vs derived:** retrieval over derived indexes; canonical untouched.
10. **Acceptance criteria:** focused green; M3/M5/M6/M7/M8 regression green; canonical green.
11. **Regression suites:** M3, M5, M6, M7, M8 (mandatory).
12. **Rollback/rebuild:** indexes rebuildable.
13. **Evidence before VERIFIED:** focused + regression + canonical.
14. **Commit boundary:** separate commits.

### M10.6 — Knowledge Graph + Optional Domain/Hierarchy Enrichment

1. **Objective:** Link corpus units into a generic knowledge graph and optional hierarchy; optional AI enrichment as a non-blocking derived pass.
2. **Exact scope:** deterministic linking (references, belongs_to, derived_from, section_of) reusing M8 `RelationType` + new `corpus_extraction` `RelationSource`; source→section→unit hierarchy; **optional** AI enrichment (semantic labels, entity/relation extraction, classification) writing derived enrichment metadata only; `domain` is a **free optional** metadata field (unknown = valid normal case; filter-only, never authorization).
3. **Out of scope:** retrieval changes (M10.5).
4. **M1–M9 reused:** M8 graph projection + `graph_access.py`; M9 DATA-only enrichment discipline; M5 auth on graph reads.
5. **Product modules/files:** `src/corpus/graph.py`, `src/corpus/enrichment.py` (optional); `tests/unit/test_m10_6_graph.py`.
6. **Expected tests:** deterministic links; enrichment never alters canonical/auth; failure degrades gracefully; unknown domain valid.
7. **Schema implications:** may extend `zm_corpus_relations` (derived).
8. **Security implications:** M5 on graph reads; enrichment fail-closed.
9. **Canonical vs derived:** graph + enrichment derived.
10. **Acceptance criteria:** focused green; M8 regression green; canonical green.
11. **Regression suites:** M8, M5.
12. **Rollback/rebuild:** rebuild from canonical.
13. **Evidence before VERIFIED:** focused + regression + canonical.
14. **Commit boundary:** separate commits.

### M10.7 — Large-Corpus Rollout + Benchmark + Final Acceptance

1. **Objective:** Prove 600-PDF stress test is routine and close M10.
2. **Exact scope:** ingest ~600 finance/quant PDFs as a **generic** corpus (no finance-specific code); run benchmark suite (§11); full regression; FINAL-HEAD canonical; M10 closure.
3. **Out of scope:** new features.
4. **M1–M9 reused:** all; benchmark `benchmark-plan.json` (research_memory isolation).
5. **Product modules/files:** `benchmarks/m10_benchmark.py` (scenario harness); `acceptance-m10.7.md`.
6. **Expected tests:** all benchmark categories; regression; canonical green at FINAL-HEAD.
7. **Schema implications:** none.
8. **Security implications:** full M5/M6.6/M7/M8 regression mandatory.
9. **Canonical vs derived:** unchanged model.
10. **Acceptance criteria:** benchmark targets met (no unsupported numbers promised); canonical green; M10 overall VERIFIED.
11. **Regression suites:** full prior-security (M5/M6.6/M7/M8) + M2/M3/M9.
12. **Rollback/rebuild:** full rebuild demonstrated.
13. **Evidence before VERIFIED:** benchmark report + canonical + FINAL-HEAD.
14. **Commit boundary:** benchmark + acceptance + M10 binding.

---

## 11. Cross-milestone regression matrix

| M10 increment | Changed boundary | Prior milestones affected | Regression suites | Security gates |
| --- | --- | --- | --- | --- |
| M10.1 | corpus registry + M5 resource types + auth handlers | M5, M6.6, M7, M8, M2 | M5/M6.6/M7/M8 + M2 path | M5/M6.6 mandatory |
| M10.2 | parser adapters + extraction + secret scan | M1, M2 | M1 secret scan, M2 failure | M1 redactor mandatory |
| M10.3 | normalization/dedup/versioning | M2, M8 | M2, M8 | M2 lifecycle |
| M10.4 | `migrate_10` derived tables + FTS | M2, M3, M5, M8 | M2 storage, M3 read-only, M5, M8 | M2/M5 FTS guard |
| M10.5 | retrieval + EvidenceSet corpus channel | M3, M5, M6, M7, M8 | M3/M5/M6/M7/M8 (mandatory) | M5/M6.6/M7/M8 mandatory |
| M10.6 | corpus graph + optional enrichment | M8, M5 | M8, M5 | M5 on graph reads |
| M10.7 | rollout + benchmark | all | full prior-security + M2/M3/M9 | all mandatory |

Every M10 increment still ends with the canonical acceptance required by the existing project workflow (pre-binding canonical under clean isolated HOME, then FINAL-HEAD canonical; 0 failed, 3 historical skips only).

---

## 12. Schema plan

- **M10.1–M10.3:** **no migration required** (canonical = JSONL + blobs; derived units in-memory/derived JSONL). v9 unchanged.
- **M10.4:** **proposed `migrate_10` (v9 → v10), derived corpus tables only**, additive, `down()`-safe, no alteration of v1–v9 tables/JSONL/blobs. Justification in §5.2. Canonical corpus truth remains blob store + `corpus_sources.jsonl`.
- **Owner decision Q2 is RESOLVED (OPTION A):** semantic/vector retrieval is an OPTIONAL LOCAL-ONLY adapter. It is NOT a core availability requirement; the corpus remains fully functional (ingestion, normalization, dedup/versioning, rebuild, authorization, metadata retrieval, FTS/lexical retrieval, `EvidenceSet` construction) with no semantic adapter installed. If semantic tables are added later, they are a further optional **derived** addition (never canonical), absence-safe, and must not be required for basic access/rebuild.

---

## 13. Performance + scale plan

**Design targets (no unsupported promises):**
- 600 PDFs = routine, not an architectural limit.
- Growth toward ~10,000 then ~100,000 documents without redesign.

**Benchmark categories (M10.7):**
1. initial ingestion (600 docs)
2. unchanged re-ingestion (hash skip → near-zero work)
3. one changed document (O(1) delta)
4. exact lookup (by `content_hash`/source_id — indexed)
5. FTS query (indexed; p95 target like M3's <100ms class)
6. hybrid retrieval (FTS + metadata + optional graph)
7. graph/entity query (bounded, M8 discipline)
8. rebuild (from canonical → derived)
9. memory usage (streaming extraction; no full-corpus in RAM)
10. disk usage (content-addressed blobs; dedup by hash)
11. evidence construction (bounded EvidenceSet)

**No obvious full-corpus O(N) in routine queries:** every routine path is index-backed (scope indexes, `content_hash` index, FTS, `unit_kind`, lifecycle). Incremental ingest skips unchanged content via deterministic hash checks.

---

## 14. Failure / recovery plan

| Condition | Classification | Behavior |
| --- | --- | --- |
| corrupt source | quarantine | source marked `quarantined`; not extracted; log reason; provenance retained |
| parser failure | retryable/partial | partial extraction recorded; failed units not admitted; source marked `partial` |
| partial extraction | derived | units that succeeded persisted; gap logged; re-extract on source change |
| unsupported format | fatal (for that source) | rejected with reason code; not ingested; no crash/leak |
| interrupted ingestion | retryable | idempotent resume via registry + checkpoint (M2 discipline) |
| duplicated source | canonical | single registry entry; subsequent = link, not copy |
| stale index | derived | rebuild from canonical (M10.4) |
| index corruption | derived | drop + rebuild from canonical |
| derived DB loss | derived | full rebuild from `corpus_sources.jsonl` + blobs |
| artifact missing | retryable | fail closed; re-ingest source |
| permission denial | fail-closed | no read; empty existence-leak-safe result |
| secret/sensitivity rejection | fail-closed | redact/reject at boundary (M1); secret never stored/projected |
| source deletion | canonical (logical) | lifecycle `deleted`; blobs retained for provenance; units excluded |
| schema incompatibility | versioned | extractor_version stamped; old units rebuildable with old extractor |

Canonical = source blobs + `corpus_sources.jsonl`. Derived = units/indexes/FTS/graph. Rebuildable = everything derived. Retryable = ingestion interrupts/partial. Quarantined = corrupt/unsupported. Fatal = unsupported format (per source, not system).

---

## 15. 600-PDF first large-corpus rollout (O)

The ~600 finance/quant PDFs are the **first production-scale stress test**. The architecture must treat them as *arbitrary* PDFs:

- **No finance-specific code.** PDF adapter is generic (text/tables/figures/metadata/page boundaries). Domain emerges only as free optional `domain` metadata (filter-only).
- **No PDF-specific architecture.** The parser is one adapter behind `FormatAdapter`; adding DOCX/HTML/code later changes no core.
- **Stress test, not specialization.** M10.7 uses them to validate scale/perf/regression; the same pipeline must accept Markdown, source code, or logs unchanged.
- **Secret hygiene:** finance PDFs may contain credentials/PII → M1 redactor + M9 backstop discipline applied at extraction.

---

## 16. Dependency / technology review

**Core M10 (M10.1–M10.5, M10.7): NO new mandatory dependencies.**
- Stdlib covers: TXT, MD (regex), CSV (`csv`), JSON (`json`), source-code/log structural split, hashing (`hashlib`), path safety (`pathlib`, `os.path.realpath`).
- Existing deps cover: SQLite WAL/FTS5, M5/M6/M7/M8 machinery.

**Optional parser dependencies (adapters only, never core):**
- **PDF:** an optional third-party parser (e.g. `pypdf` or `pdfminer.six`). Stdlib has no PDF parser. Added as an **optional extra** (`extras_require`); absence → PDF adapter reports `unsupported_format`, never crashes. Runtime vs dev: runtime-optional. Security: pinned, local-only, no network. License: permissive (BSD). Deferrable: yes (M10.2 can ship PDF+TXT; other formats later).
- **HTML:** stdlib `html.parser` suffices for structural extraction; `html2text` optional extra if richer text needed.
- **DOCX:** `python-docx` optional extra (no stdlib path).

**Semantic/vector (M10.5/6 optional, Q2 RESOLVED A):** local-only embeddings (BGE-M3/multilingual, per M0 alternatives) as an **optional** adapter, **absence-safe** — a missing or failed semantic adapter degrades safely to the deterministic (FTS/metadata/graph) retrieval path and is NEVER a core availability requirement. **No commercial API/cloud mandated.** Vectors never canonical; removable; rebuildable.

**Principle:** parsers and AI enrichment are **pluggable adapters** isolated from the corpus core. The core (contracts, registry, hashing, dedup, FTS, auth, retrieval, EvidenceSet) depends only on stdlib + existing repo deps. This matches M0's "vector index, embedding model, service framework remain replaceable adapters."

---

## 17. Test strategy

Layered, reusing the successful M1–M9 pattern: focused increment tests → relevant cross-milestone regressions → canonical. No full source audit after every increment.

- **Ingestion/storage change** → M2/M3 path/provenance regressions.
- **Retrieval change** → M3 + M5 + M6 + M7 + M8 relevant regressions (mandatory).
- **Security change** → M5/M6.6/M7/M8 mandatory regression.
- **Every increment** → pre-binding canonical (clean isolated HOME) then FINAL-HEAD canonical (0 failed, 3 historical skips). (M9 regression suites still run as part of the full regression in M10.7; the dedicated corpus→Obsidian integration trigger is removed because M10.8 is deferred per Q5.)

---

## 18. Final post-M10 audit — kept separate

The full M1→M10 end-to-end audit is **reserved for after M10 is VERIFIED** (per project workflow). M10 planning does not perform or fix those broad items unless a specific blocker prevents M10 design. Future audit phases: AUDIT ONLY → FIX PLAN → REMEDIATION → FINAL CANONICAL / END-TO-END REVIEW, covering architecture boundaries, canonical vs derived, read/write boundaries, authorization bypass, resource_type isolation, path safety, hard-coded paths, schema/migrations, dead/duplicate code, state duplication, error handling, secret leakage, concurrency, performance, rebuild/recovery, tests/non-vacuity, and M1→M10 integration. Pre-existing M1/M2 duplicate-state defects (deferred in M9) remain explicitly out of M10 scope and belong to that audit.

---

## 19. Planning artifact

- This file: `plan-m10.md` — **Status: APPROVED / IMPLEMENTATION CONTRACT** (owner-approved; all six owner decisions resolved; three blocking clarifications folded in). **M10.1 VERIFIED.**
- `project-state.yaml`: `m10_plan_status: "approved"` and `m10_plan_artifact: "plan-m10.md"` recorded; `m10_status` is `in_progress` (M10.1 verified; M10.2–M10.7 pending; M10.8 deferred per Q5).
- `acceptance-m10.1.md`: M10.1 VERIFIED evidence.
- No migration performed in M10.1; no product-code change outside the M10.1 file list; no ingestion; no experimental DB; no corpus data created.
- Three owner-review blocking clarifications are folded into this plan (review-m10.md §M): **(1) authorization-routing invariant** (§3.1, §6.1, §9, M10.1/M10.5 acceptance — every corpus read routes through `AuthorizedReadService`; static/regression guard); **(2) corpus redaction adapter `src/corpus/redact.py`** (§4.1, §6, M10.2 — reuses M1 fail-closed rules + M9 non-disableable baseline on extracted corpus text); **(3) coarse `unit_kind`** (M10.3 — trimmed to structural set; semantic subtypes deferred to optional M10.6 enrichment). Q3/Q4 resolved by convention/spec; Q1/Q2/Q5/Q6 resolved by final owner decision (§20). M10.8 removed — corpus→Obsidian projection deferred outside M10 per Q5.

---

## 20. Risks / open questions

All owner decisions are now **RESOLVED** (Q1–Q6). No open owner decisions remain.

**Q1 — Corpus resource-type granularity in M5 — RESOLVED: OPTION A (FINAL).** Use two distinct M5 resource types: `corpus_source` and `corpus_unit`. Preserves M6.6-style `resource_type` isolation — a grant for `corpus_source` must not authorize `corpus_unit`, and a `corpus_unit` grant must not authorize `corpus_source`, `event`, `artifact`, or any other resource type. Mirror the resource-type contract into M8 where the existing equality contract requires it.

**Q2 — Semantic / vector retrieval — RESOLVED: OPTION A (FINAL).** Include semantic/vector retrieval as an OPTIONAL LOCAL-ONLY adapter. Mandatory constraint: it is NOT a core availability requirement. Zero-Mem corpus MUST remain fully functional for ingestion, normalization, dedup/versioning, rebuild, authorization, metadata retrieval, FTS/lexical retrieval, and `EvidenceSet` construction when no semantic adapter/model is installed. No cloud API and no paid LLM/API is mandatory. Optional semantic infrastructure must remain derived, rebuildable, removable, and absence-safe. The query planner MAY use semantic retrieval when available and appropriate. Do NOT design M10 as "embed everything"; a missing or failed semantic adapter degrades safely to the deterministic retrieval path rather than making the corpus unavailable.

**Q3 — Corpus canonical storage root resolution — RESOLVED by repository convention (Option A).** Blob store + `corpus_sources.jsonl` resolve via a dedicated configurable root (env `ZERO_MEM_CORPUS_ROOT` / config key / explicit arg), same explicit-only discipline as `BridgeConfig`/`ProjectionConfig`; no `/home/<user>` in code; portable by one env var/config key, zero code change; never derived from cwd/HOME.

**Q4 — `domain` field: free vs closed vocabulary — RESOLVED by task spec (Option A).** `domain` is a free optional string metadata, untrusted, filter-only; unknown domain = valid normal case (required by the M10 task). A closed vocabulary would contradict the requirement and over-model.

**Q5 — Obsidian corpus projection — RESOLVED: OPTION B (FINAL).** DEFER corpus-specific Obsidian projection OUTSIDE the core M10 milestone. **M10.8 is removed from the required M10 implementation sequence.** Reason: M10 should first complete and stabilize the universal corpus substrate, retrieval, authorization, `EvidenceSet` integration, and large-corpus rollout. Corpus functionality does NOT depend on Obsidian projection; M9 remains the verified curated human-facing projection system. Do NOT create a new M11 or other milestone automatically. Record corpus→Obsidian projection only as a DEFERRED OPTIONAL future/release enhancement (reusing M9 ownership, manifest, path safety, human-edit, and sensitivity contracts if the owner later decides it is necessary). It is NOT required for M10 acceptance or Zero-Mem corpus operation.

**Q6 — First adapter set — RESOLVED: OPTION A (FINAL).** M10.2 ships the universal `FormatAdapter` contract/registry plus PDF and TXT adapters. The architecture must remain format-neutral; the ~600 finance/quant PDFs are the first production-scale corpus test, NOT the architectural domain. Future adapters (Markdown, HTML, DOCX, CSV, JSON, source code, logs) must be addable behind the same adapter contract without redesigning the corpus core. Unknown domain remains valid.

---

## 21. Proposed acceptance definition for M10

M10 is VERIFIED only when **all** hold:
- M10.1–M10.7 each VERIFIED with focused + regression + canonical evidence (0 failed, 3 historical skips only, clean isolated HOME).
- `migrate_10` up/down verified; v1–v9 untouched; canonical corpus = blob store + `corpus_sources.jsonl`.
- Authorization-first proven: hidden/unauthorized corpus resources have zero influence on any ranking/snippet/evidence.
- Secret fail-closed at extraction boundary; `secret` never stored or projected.
- 600-PDF rollout routine; benchmark categories met; no full-corpus O(N) routine query.
- M5/M6.6/M7/M8 security regressions green across FINAL-HEAD canonical.
- Memory JSONL never receives document contents; corpus canonical distinct from memory canonical.
- Deterministic rebuild from canonical demonstrated.
- `m10_overall_status: "verified"` recorded; `m11_status: "not_started"`.

---

## 22. Final recommendation

Adopt the **7-increment M10.1–M10.7 sequence** (there is no M10.8; corpus→Obsidian projection is deferred outside M10 per owner decision Q5). It preserves every load-bearing M1–M9 contract, wraps corpus under the existing M5 authorization from the first increment (no bypass), keeps canonical corpus storage distinct from memory JSONL, defers `migrate_10` to after the canonical model is frozen (M8.1 precedent), adds **no mandatory new dependency**, treats the 600 PDFs as a generic stress test, and makes semantic/vector retrieval an optional local-only absence-safe adapter (Q2). **Schema recommendation: stay v9 through M10.1–M10.3; introduce derived-only `migrate_10` at M10.4 — a derived-store migration-version change that does NOT alter canonical memory authority (the memory substrate stays v-agnostic JSONL + v1–v9 tables; `migrate_10` only adds derived corpus tables).** New mandatory dependencies: **none**.

**M10.1 is VERIFIED; proceed to M10.2 (Multi-format Ingestion + Structural Extraction, PDF + TXT adapters) only after its own pre-binding + FINAL-HEAD canonical gates.**
