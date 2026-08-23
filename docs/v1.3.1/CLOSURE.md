# Zero-Mem v1.3.1 — Closure Handoff

**Status:** `IMPLEMENTATION_COMPLETE` — chờ user phê duyệt release
(`APPROVE-RELEASE-V131.md`). KHÔNG tag/push/publish khi chưa có approval.
**Branch:** `release/v1.3.1-remediation` | **Base:** master `8264711` | **Date:** 2026-08-23
**Scope:** Remediation release integrity + corpus tooling defects (V131-FULL-PROMPT).

## Kiến trúc & data flow (không đổi khung)

JSONL canonical (append-only) → ingest/registry → derived SQLite/FTS →
retrieval/eligibility → EvidenceSet. v1.3.1 chỉ sửa tooling (`scripts/`,
`benchmarks/`, tests, docs, version metadata); không đụng canonical schema,
không đổi src/ runtime behavior trừ `benchmarks/v130_real_corpus_pipeline.py`
gate semantics (WP-6, có chủ đích).

## Changed paths (theo WP)

| WP | Paths |
|---|---|
| 1 | `zero_mem/version.py`; `tests/unit/test_v131_version_integrity.py`; `tests/unit/test_pkg{1,2}_packaging.py`; `tests/unit/test_pkg6_upgrade_lifecycle.py`; `release_helpers/release_common.py`; `docs/releases/RELEASE-NOTES-v1.3.1.md` |
| 2 | `pyproject.toml` (extra `pdf-advanced`); `scripts/_pdf_tooling_guard.py` (mới); `scripts/corpus_extract_pdfs.py`; `scripts/corpus_project_quant_lab.py`; `tests/unit/test_v131_pdf_tooling_guard.py`; `docs/v1.3.0/{TECH_STACK,EVIDENCE}.md`; `docs/v1.3.1/decisions/ADR-V131-01-PYMuPDF-LICENSE.md` |
| 3 | `docs/v1.3.0/CLOSURE.md`; `docs/v1.3.0/evidence/POST_RELEASE_CLOSURE.md` |
| 4 | `scripts/corpus_ingest_quant_lab.py`; `tests/unit/test_v131_ingest_stats.py` |
| 5 | `scripts/corpus_project_quant_lab.py`; `tests/unit/test_v131_project_runner_safety.py` |
| 6 | `benchmarks/v130_real_corpus_pipeline.py`; `tests/unit/test_v130_05_redaction_gate.py` |
| 7 | `tests/unit/test_v130_05_redaction_gate.py` |
| 8 | `docs/v1.3.1/analysis/is-verified-enum-mismatch.md` |

Commits: `d27465c` `20907cf` `f348bd8` `5cb9632` `3f817b9` `68e36da` `532c59c`
`8cd80d1` `0adc1b4` (+ docs G6).

## Evidence

Xem `docs/v1.3.1/EVIDENCE.md`. Baseline 3434/5; final suite
(`zero-mem-dev-data/evidence/v131/final-suite.log`) = **3448 passed / 6 skipped**
(skip tăng do portability skip của WP-7 — đúng semantic).

## Risks

1. **WP-6 behavior change:** dòng đã-redact («redacted:…») giờ đi qua gate.
   Secret thật vẫn fail-closed (test giữ case block). Đã ghi release notes.
2. **D-01 (ADR-V131-01):** pymupdf là optional-extra AGPL tooling-only; không
   phải runtime dep. Nếu sau này yêu cầu strict-BSD tuyệt đối cho tooling →
   chuyển phương án B (pypdf thuần).
3. **WP-8 OPEN QUESTION:** is_verified enum mismatch — chờ user quyết
   (Option A align enum / Option B freeze). Không có code change trong v1.3.1.
4. Skip count 5→6: archive fixture env unset — không phải regress.

## Draft release notes

`docs/releases/RELEASE-NOTES-v1.3.1.md`.

## Next integration steps

1. User review CLOSURE + OPEN QUESTION WP-8 → quyết Option A/B/defer.
2. Tạo `APPROVE-RELEASE-V131.md` để mở khóa tag/push (local Git; publish theo
   GITHUB-POLICY).
3. Sau release: WP-8 follow-up package nếu chọn Option A.
