# M10.2 — Acceptance Evidence

**Increment:** M10.2 — Multi-format Ingestion + Structural Extraction (PDF + TXT adapters)
**Status:** VERIFIED
**Parent plan:** `plan-m10.md` (APPROVED / IMPLEMENTATION CONTRACT)
**Sub-plan:** `plan-m10.2.md`

## Scope delivered

- **Universal `FormatAdapter` boundary** (`src/corpus/adapters/`): `FormatKind`,
  `FormatAdapter` protocol, `ADAPTER_REGISTRY`, `select_adapter`. Adding a future
  adapter (Markdown/HTML/DOCX/CSV/JSON/code/logs) requires NO core redesign —
  register it in the list. Corpus core depends only on the protocol, never on
  PDF/format-specific objects.
- **TXT adapter** (`txt.py`): deterministic line/order provenance; encoding
  fallback (utf-8 → utf-8-sig → latin-1); empty/blank handling; no over-structure.
- **PDF adapter** (`pdf.py`): OPTIONAL `pypdf`, import-guarded. Absence →
  deterministic `parser_unavailable` (never crash). Page + order provenance where
  the parser provides it. Corrupt PDF → `corrupt_source`. Image-only/scanned →
  `unsupported_format` (no OCR, no invented text). No LLM/network.
- **Structural extraction model** (`extract.py`): `ExtractionUnit` (coarse
  `unit_kind`: text/heading/table/code/figure/metadata/other — no semantic
  ontology), `ExtractionResult` (closed `ExtractionStatus`), `ExtractionError`.
  Unknown structure stays valid (`other`).
- **Content-addressed blob store** (`blob_store.py`): source bytes live ONLY
  here (`<root>/blobs/<sha[:2]>/<sha>`), never in memory JSONL. Atomic, idempotent,
  path-escape defended. Bound to `CorpusSourceRecord.blob_ref` via
  `register_source_with_blob`.
- **Redaction/sensitivity boundary** (`redact.py`): reuses M1 `redact_payload`
  (fail-closed). `scan_extracted_text` / `require_safe` — secrets never enter a
  derived/searchable representation; ingress is rejected at the boundary. No
  source text reaches Hermes/EvidenceSet in M10.2.
- **Registry blob binding**: `register_source_with_blob` persists bytes to the
  blob store and binds `blob_ref`; idempotent by content+scope.

## MEMORY != CORPUS invariant

Source bytes are in the blob store; the `corpus_sources.jsonl` registry carries
provenance + `blob_ref` only — no document bytes in memory JSONL. No ingestion of
the real ~600-PDF corpus (fixtures only). No normalization/dedup/versioning (M10.3),
no FTS (M10.4/5), no semantic (M10.5/6), no graph (M10.6), no EvidenceSet corpus
retrieval (M10.5), no Obsidian (deferred Q5), no `migrate_10` (M10.4). Schema
remains **v9**.

## Authorization-before-influence invariant

`corpus_source` / `corpus_unit` M5 resource types and M6.6 isolation unchanged
(verified). Ingestion binds extraction to source identity/scope; extraction grants
no access; adapter choice / source path grant nothing (verified by unchanged
M5/M6.6/M8 regressions).

## Verification evidence

- Focused M10.2: **17 passed, 2 skipped** (PDF valid/corrupt skipped because
  `pypdf` is not installed — absence-safe by design; the absence path is tested).
- Relevant regressions (M10.1 registry, M5 auth/grants/cross-profile, M8 mirror):
  **275 passed, 2 skipped** combined with focused.
- **Pre-binding canonical** (clean isolated HOME): **2886 passed, 5 skipped, 0 failed**.
- **FINAL-HEAD canonical** (clean isolated HOME): **2886 passed, 5 skipped, 0 failed**
  at `3a…` (see final commit HEAD in report).
- The 5 skips = 3 historical M6.6/migration skips + 2 PDF paths pending optional
  `pypdf`. No new failures.

## Files changed

- `src/corpus/extract.py` (new) — extraction result/error/unit contracts.
- `src/corpus/adapters/{__init__,base,txt,pdf,registry}.py` (new) — FormatAdapter + adapters.
- `src/corpus/blob_store.py` (new) — content-addressed blob store + shared root resolver.
- `src/corpus/redact.py` (new) — fail-closed redaction boundary (reuses M1).
- `src/corpus/registry.py` — `register_source_with_blob` + `blob_ref` binding (root
  resolver relocated to `blob_store.py` to break a circular import).
- `src/corpus/__init__.py` — exports.
- `tests/unit/test_m10_2_ingestion.py` (new), `tests/fixtures/corpus/*` (new fixtures).
- `plan-m10.md`, `project-state.yaml`, `plan-m10.2.md` — state binding.

## Acceptance gate

All M10.2 acceptance criteria met (approved plan §21): universal adapter boundary;
PDF+TXT only; not PDF-specific; deterministic; no LLM/API; provenance survives;
bytes not in memory JSONL; corpus_source/corpus_unit contracts intact; M6.6 intact;
redaction boundary enforced; unsupported/corrupt deterministic; no real 600-PDF
ingest; schema v9; no M10.3 pulled forward; focused + relevant regressions green;
pre-binding + FINAL-HEAD canonical green.

## Next

M10.3 (Normalization + Deduplication + Versioning) is authorized to begin.
M10.4–M10.7 follow in order. M10.8 remains deferred (owner decision Q5, OPTION B).
