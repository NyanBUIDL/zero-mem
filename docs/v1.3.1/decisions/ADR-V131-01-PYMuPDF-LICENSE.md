# ADR-V131-01 — pymupdf license handling (Decision D-01)

**Status:** ACCEPTED (Phương án A) — 2026-08-23, v1.3.1 WP-2
**Decision owner:** maintainer (per V131-FULL-PROMPT default recommendation)

## Context

The v1.3.0 corpus tooling (`scripts/corpus_extract_pdfs.py`,
`scripts/corpus_project_quant_lab.py`) imports `pymupdf`, which is
AGPL-3.0 / commercial dual-licensed. `pyproject.toml` declared only
`pypdf` (BSD) under the `pdf` extra, and TECH_STACK/EVIDENCE claimed
"no new dependency" — an incorrect claim.

## Decision (Phương án A)

- Declare a new **optional extra**: `pdf-advanced = ["pymupdf"]` with an
  in-file AGPL warning comment in `pyproject.toml`.
- Keep `pdf = ["pypdf"]` (BSD) as the default BSD-safe PDF extra.
- Correct TECH_STACK.md / EVIDENCE.md wording to: **"no new RUNTIME
  dependency; tooling-only optional extra."**
- Guard imports: scripts fail with an actionable message
  (`pip install zero-mem[pdf-advanced]`) instead of a bare ImportError
  (`scripts/_pdf_tooling_guard.py`).

## Rejected alternative (Phương án B)

Rewrite the pipeline on pure `pypdf` (no AGPL) at the cost of lower
extraction quality. Only preferable if strict-MIT/BSD-only is ever
mandated for tooling as well.

## Consequences

- `pip install -e .` (no extras) never pulls pymupdf; runtime stays
  dependency-clean and license-clean.
- pymupdf remains an explicit, documented, removable tooling choice;
  canonical JSONL and derived stores never depend on it.
- Reversibility: dropping the extra and the guard leaves only script-level
  impact; no migration needed.
