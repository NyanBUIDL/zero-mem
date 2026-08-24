# Zero-Mem v1.4.0 Release Notes (V140 — corpus import + MCP adapter + retrieval baseline)

**Date:** 2026-08-25 · **Scope:** V140-00..04 (see `docs/v1.4/CHECKLIST.md`, `docs/v1.4/EVIDENCE.md`)

## What changed

### Corpus import pipeline (generic, not arxiv-hardcoded)
A parameterized corpus-import pipeline (`scripts/corpus_generic_ingest.py` +
`scripts/adapters/arxiv_quant_adapter.py`) ingests a user-supplied markdown/PDF
corpus into the Zero-Mem derived corpus store. The quant_lab sample corpus
(599 markdown notes + 1 primary PDF) was imported as a reference dataset:
**217,256 units** with 100% `blob_ref` set, full-text FTS5 index.

The pipeline is corpus-agnostic — operators point it at their own source folder
with `--source-dir / --ks-name / --adapter`. It is not coupled to arxiv format.

### Knowledge-space resolution (DEF-004, Option B)
A resolution layer (`src/access/knowledge_space_resolver.py`) maps a
knowledge-space grant to the `(profile, project)` tuples that own resources in
that space, so the existing authorization scope can authorize them without a
schema migration. The `zm_meta` event-store schema is **unchanged**. Verified
by 9 RED→GREEN unit tests; full suite green before/after.

### MCP read adapter + non-Hermes POC
A stdlib-only MCP server (`src/integration/m6/mcp_server.py`) wraps the existing
M6 read dispatcher over stdio JSON-RPC — it reuses the dispatcher and handlers,
it does **not** fork any core logic. A new `corpus_search` tool (M6.5) exposes
the derived corpus knowledge base through the same authorization-safe path as
the rest of M6. A reference non-Hermes client (`examples/mcp_client_poc.py`)
demonstrates an external agent querying the corpus without being Hermes.

### Retrieval-quality baseline (engineering metric)
A deterministic, zero-LLM benchmark harness
(`benchmarks/v140_04_retrieval_bench.py` + `benchmarks/qa_quant_lab_heldout.jsonl`)
establishes a reproducible precision@k baseline over the quant_lab corpus, reusing
the exact product retrieval path. This is an **internal engineering baseline** for
tracking future retrieval improvements (e.g. a v1.5 semantic adapter); it is not a
user-facing feature and is not a performance claim.

## Defects

- **DEF-004** (knowledge-space authorization gap): FIXED via Option B resolution
  layer, no schema change.
- **DEF-010** (space-grant coarsening — grant space ≡ grant project): OPEN,
  deferred to v1.5+ (documented limitation; behavior is fail-closed and intentional).
- **DEF-011** (authorization reads from derived corpus state): OPEN, deferred to
  v1.5+ (rebuildable, operationally bounded; recommended rule: verify projection
  digest before trusting space-grant authorization results).

## Known limitations

- Corpus retrieval in v1.4.0 is lexical-only (FTS5). No semantic/embedding fusion
  yet — that is the v1.5 decision input, not part of this release.
- The retrieval baseline is a self-retrieval probe (queries drawn from the corpus
  itself). It is an upper bound for in-vocabulary queries; real user paraphrases
  will score lower. The numeric baseline is recorded in `docs/v1.4/EVIDENCE.md`
  for reproducibility and future comparison, not as a marketing metric.

## Verification

- Full unit suite: **3425 passed, 7 skipped, 0 failed** (Python 3.13.15, isolated HOME).
- Independent verifiers (READ-ONLY, anti-conflict-of-interest): V140-02 (6/6),
  V140-03 (11/11), V140-04 (7/7).
- No production code forked for the MCP/M6 surface; the wrapper reuses the existing
  dispatcher and handlers.

## Upgrade notes

- `zero_mem/version.py` bumped 1.3.4 → 1.4.0.
- No database migration required for existing event stores (DEF-004 Option B is
  schema-preserving). Corpus-derived stores are rebuilt from source on ingest.
