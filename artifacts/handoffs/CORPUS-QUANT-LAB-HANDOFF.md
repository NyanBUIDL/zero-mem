# CORPUS-QUANT-LAB HANDOFF — ingest quant_lab vào ks `quant-theory`

**Status:** COMPLETE (QL-1 + QL-2) | **Date:** 2026-08-23 | **Branch:** release/v1.3.0
**Điều kiện tiền đề:** release v1.3.0 đã duyệt + master ff xong (Verifier audit PASS). ✓

## Kiến trúc & data flow

`quant_lab/` (600 md + 471 pdf, read-only source) →
- **QL-1** `scripts/corpus_ingest_quant_lab.py`: parse dir → `CorpusSourceRegistry.register_source()` (content-hash dedup) + `register_source_with_blob()` cho PDF → registry `corpus_sources.jsonl` (ks=quant-theory).
- **QL-2** `scripts/corpus_extract_pdfs.py` (pymupdf text layer) + `scripts/corpus_project_quant_lab.py` (PyMuPdfAdapter shim + blob-backfill md + `project_corpus`) → derived `corpus-derived.sqlite` (zm_corpus_sources/units/fts).

PDF = **nguồn chính thống** (blob store); text = derived. Orphan-md ghi provenance `original-pdf-unavailable`.

## Changed paths

- `scripts/corpus_ingest_quant_lab.py` (mới) — QL-1 ingest + QL-2 blob/extract integration.
- `scripts/corpus_extract_pdfs.py` (mới) — pymupdf verbatim text extraction, SKIP quality gate.
- `scripts/corpus_project_quant_lab.py` (mới) — pymupdf adapter shim + projection + idempotent migrations.
- Không đụng `src/` (WP thuần tooling + data op) — adapter shim ở tầng tooling.
- Dev-data (ngoài git): `zero-mem-dev-data/corpus-quant-lab/` (registry + blobs + derived sqlite), `zero-mem-dev-data/evidence/v130-corpus-ingest/`.

## Verified evidence

- QL-1: 1070 sources (471 primary-pdf / 470 derived-md / 129 orphan-md), idempotent run2=0 mới, spot-check 10/10.
- QL-2: 9863 units projected, extraction_failed=0, FTS smoke xanh (Kelly 8 / LOB 620 / rough-vol 381), verbatim 10/10.
- Redaction gate fail-closed đúng: 1 unit TimeGPT-1 p12 bị loại (secret), không leak.
- pymupdf 1.28.2 venv-local.

## Risks / gaps

1. **TimeGPT-1.pdf p12** — unit bị redaction loại (fail-closed đúng). Nếu bài này quan trọng cần xử lý nguồn thủ công (quyết định riêng).
2. Corpus là **tài liệu học thuật arXiv** — có thể chứa mã nguồn/mô hình mẫu trong text; redaction gate vẫn quét mọi unit (đúng quy tắc).
3. `corpus-derived.sqlite` là **derived** — rebuildable từ registry + blobs qua `corpus_project_quant_lab.py`.
4. FTS `match_mode`/ks filter tái sử dụng core v1.3.0 — query cross-ks giữ nguyên authorization.

## Next integration

1. Research-insight pipeline (v1.4+): citation-check ưu tiên primary-pdf origin; orphan-md gắn nhãn `[orphan-source]`.
2. Multi-value knowledge-space (master spec L148) nếu cần 1 paper thuộc nhiều ks.
3. Query smoke-test qua AuthorizedReadService đầy đủ (hiện tại FTS raw).
