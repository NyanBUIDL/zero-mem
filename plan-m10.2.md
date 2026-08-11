# M10.2 — Multi-format Ingestion + Structural Extraction (implementation sub-plan)

**Status:** IN PROGRESS (smallest coherent increment of approved M10).
**Parent plan:** `plan-m10.md` (APPROVED / IMPLEMENTATION CONTRACT).
**Prior increment:** M10.1 VERIFIED (HEAD `95982b8`, schema v9).
**Scope:** PDF + TXT adapters behind a universal `FormatAdapter` boundary; structural
(coarse) extraction; content-addressed blob store; `src/corpus/redact.py` boundary.
**Out of scope:** normalization/dedup/versioning (M10.3), FTS (M10.4/5), semantic
(M10.5/6), graph (M10.6), EvidenceSet corpus retrieval (M10.5), Obsidian (deferred Q5),
`migrate_10` (M10.4), the real ~600-PDF corpus, packaging, post-M10 audit.

---

## 1. PHASE 0 — reconciliation (done)

- HEAD = `95982b8` (M10.1 VERIFIED) ✓
- `m10_current_increment_status: verified` ✓
- `corpus_source` / `corpus_unit` registered M5 resource types; M5↔M8 mirror exact ✓
- M6.6 isolation intact (verified in M10.1) ✓
- No PDF parser installed in `.venv` → PDF adapter MUST be optional ✓
- No `setup.py`/`pyproject`/`requirements` manifest; repo runs from `.venv` directly
  → mandatory new dependencies = NONE (per plan) ✓
- `config/` convention: explicit arg → env var (`ZERO_MEM_*`) → `config/*.yaml`
  (`.example` only) → unavailable-safe. Registry already resolves via
  `ZERO_MEM_CORPUS_ROOT`. Blob store reuses the same root. ✓

No material discrepancy. Proceeding.

---

## 2. M10.2 contract (from approved plan-m10.md §10.2 / §15)

### Objective
Introduce a UNIVERSAL source-format ingestion boundary. Registered source bytes
flow: source bytes → format detection/adapter selection → `FormatAdapter` →
structural extraction → deterministic `ExtractionResult` → (future) M10.3.
Downstream corpus code must NOT depend on PDF-specific objects.

### In-scope
- `FormatAdapter` contract: format identity, support check, deterministic
  extraction, structural output, source/artifact provenance, typed extraction
  error classification.
- `ExtractionUnit` (coarse `unit_kind` set), `ExtractionResult` (status + units),
  `ExtractionError` typed failures.
- TXT adapter: encoding strategy, line/order provenance, empty-file behavior,
  large-file streaming-safe (no full-corpus-in-RAM assumption).
- PDF adapter: optional `pypdf`; absence → deterministic `parser_unavailable`
  status (never crash); page + block/order provenance; corrupt PDF → explicit
  failure; image-only/scanned → `partial`/`unsupported` (no OCR); no LLM/network.
- Source/artifact boundary: content-addressed **blob store** under the resolved
  corpus root (`<root>/blobs/`), populating `CorpusSourceRecord.blob_ref`. Source
  bytes live ONLY in the blob store, never in memory JSONL.
- `src/corpus/redact.py`: reuse M1 `redact_payload` on extracted text; fail-closed;
  secret never stored/projected; extracted text NEVER exposed to Hermes in M10.2.
- Path safety: blobs confined to the resolved root; reject traversal / symlink
  escape / writes outside the approved storage root.

### Out-of-scope (enforced)
M10.3 normalization/dedup/versioning, M10.4 `migrate_10`/FTS, M10.5 semantic/
EvidenceSet retrieval, M10.6 graph/enrichment, Obsidian projection (deferred),
real 600-PDF ingestion, packaging, post-M10 audit.

### Files expected to change
- NEW `src/corpus/extract.py` — `ExtractionUnit`, `ExtractionResult`, `ExtractionError`,
  `ExtractionStatus`.
- NEW `src/corpus/adapters/__init__.py`, `base.py`, `pdf.py`, `txt.py`, `registry.py`
  — `FormatAdapter` protocol + adapters + format selector.
- NEW `src/corpus/blob_store.py` — content-addressed blob store (derived, rebuildable
  from source bytes; the authoritative copy at ingest).
- NEW `src/corpus/redact.py` — fail-closed redaction boundary reusing `src.redaction`.
- EXTEND `src/corpus/registry.py` — `register_source` accepts optional `store_blob=`
  to bind `blob_ref`; add `blob_store` path resolution under same root.
- NEW `tests/unit/test_m10_2_adapters.py`, `tests/unit/test_m10_2_blob_store.py`,
  `tests/unit/test_m10_2_extract.py`, `tests/unit/test_m10_2_redact.py`.
- NEW `tests/fixtures/corpus/` — tiny deterministic PDF/TXT fixtures + corrupt PDF.
- UPDATE `project-state.yaml` + `plan-m10.md` M10.2 marker + `acceptance-m10.2.md`.

### Schema impact
NONE. Stays v9. The blob store is filesystem artifacts under the corpus root
(approved canonical corpus direction: source/artifact blob store +
`corpus_sources.jsonl`). No SQLite migration.

### Dependency impact
Mandatory new dependencies: NONE. PDF uses OPTIONAL `pypdf` (import-guarded; if
absent, PDF adapter reports `parser_unavailable`). No change to how the repo is
run.

### Security impact
- M5 `corpus_source`/`corpus_unit` resource types and M6.6 isolation UNCHANGED.
- Redaction fail-closed at extraction boundary (reuses M1).
- Path escape defended (blob writes confined to resolved root).
- No real corpus touched; fixtures only.

### Canonical / derived impact
- Canonical: source blob bytes (authoritative at ingest) + `corpus_sources.jsonl`
  registry provenance.
- Derived/rebuildable: `ExtractionResult` recomputable from (blob + parser config).

---

## 3. Acceptance criteria (mirrors approved plan §21)
1. Universal `FormatAdapter` boundary exists.
2. PDF + TXT are the only required initial adapters.
3. Core architecture is not PDF-specific.
4. Structural extraction is deterministic.
5. No LLM/API required.
6. Source provenance survives extraction.
7. Source bytes are not dumped into existing memory JSONL.
8. `corpus_source`/`corpus_unit` authorization contracts intact.
9. M6.6 isolation intact.
10. `src/corpus/redact.py` boundary enforced.
11. Unsupported/corrupt input fails deterministically.
12. No real ~600-PDF rollout.
13. Schema v9.
14. No M10.3 pulled forward.
15. Focused tests pass.
16. Relevant regressions pass.
17. PRE-BINDING canonical green (0 failed, 3 historical skips).
18. Acceptance/state committed.
19. FINAL-HEAD canonical green.

## 4. Verification discipline
- Focused M10.2 unit tests.
- Relevant regressions: M10.1 corpus registry tests, M5 auth, M6.6 isolation,
  M8 M5↔M8 mirror.
- PRE-BINDING canonical under fresh isolated HOME.
- FINAL-HEAD canonical under a NEW fresh isolated HOME.
- No full M1–M9 source audit; post-M10 audit deferred per plan.
