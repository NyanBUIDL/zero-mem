# CORPUS-QUANT-LAB Handoff — quant_lab ingest (QL-1 + QL-2)

**Status:** IMPLEMENTED_VERIFIED (local-only; no push/tag/release)
**Date:** 2026-08-23 · **Operator:** ox-alpha under CORPUS-QUANT-LAB-PROMPT.md
**Base:** v1.3.0 released (`4983756` tag; master `19996c2` post-release docs)

## Architecture & data flow

```
quant_lab/ (600 dirs .md + papers/ 471 PDF, read-only source)
  └─ scripts/corpus_ingest_quant_lab.py        [tooling]
       ├─ parse: dir name → date/arxiv_id/title; PDF matched by (date, arxiv_id);
       │         PDF w/o dir ⇒ primary-pdf-only source
       ├─ CorpusSourceRegistry.register_source[_with_blob]  → corpus_sources.jsonl (CANONICAL)
       └─ blob store (content-addressed) for PDF bytes      → blobs/            (CANONICAL)
  └─ projection runner (zm-proj-final-ox.py)   [tooling]
       ├─ runtime adapter shims: primary-pdf→pymupdf pages; md kinds→text lines
       ├─ blob-backs the 599 md/orphan sources (idempotent puts)
       ├─ M10.2 extractor + M10.3 normalize/dedup + fail-closed secret gate
       └─ project_corpus → corpus-derived.sqlite (DERIVED, rebuildable; schema v11)
```

Canonical = registry JSONL + blobs. Derived DB can be dropped and rebuilt by
re-running the projection runner — no canonical loss.

## Changed paths

| Path | Kind | Note |
|---|---|---|
| `scripts/corpus_ingest_quant_lab.py` | new tooling | QL-1/QL-2 registration |
| `scripts/corpus_extract_pdfs.py` | new tooling | standalone pymupdf extractor CLI |
| `zero-mem-dev-data/corpus-quant-lab/` | data (untracked) | registry JSONL + blobs + derived sqlite |
| `zero-mem-dev-data/evidence/v130-corpus-ingest/` | evidence (untracked) | logs + EVIDENCE-SUMMARY.md |

**src/ untouched** ✓ (verified via git status).

## Results

- Sources: **1.070** = 471 primary-pdf + 470 derived-md + 129 orphan-md
  (600 papers total check ✓)
- Derived units: **9.863**, all ks=`quant-theory`, fts_rows=9.863
- Secret gate: **1 unit rejected fail-closed** (never stored)
- Extraction failures: 0
- Idempotent: re-ingest dedups at registry; re-projection upserts identical rows
- FTS smoke: Kelly criterion / limit order book / rough volatility all hit

## Verification evidence

- `evidence/v130-corpus-ingest/EVIDENCE-SUMMARY.md` (counts + method)
- `ingest-run1.log`, `ingest-run2-idempotency.log`, `projection-final-ox.log`
- Spot-checks in session transcript (content identity ×10 PASS; verbatim page-1 text)

## Risks / gaps

1. Ingest script registers .md without `blob_ref`; the projection runner
   compensates. Follow-up: fold blob-backing into ingest script.
2. MuPDF warnings on some malformed embedded objects — benign, deterministic.
3. `units_rejected_secret=1` — expected fail-closed behavior, not a defect.
4. Projection runner currently lives outside repo (`zm-proj-final-ox.py`);
   recommend promoting it to `scripts/corpus_project_derived.py` in a follow-up.

## Next integration steps

1. Commit tooling scripts locally (exact paths only).
2. Optional follow-up WP: merge blob-backing into ingest script + promote
   projection runner into `scripts/`.
3. Retrieval-side: wire ks-filtered corpus search (`quant-theory`) through the
   existing AuthorizedScope path for downstream research-insight pipeline.
