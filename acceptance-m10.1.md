# M10.1 — Acceptance Evidence

**Increment:** M10.1 — Corpus Source Registry + Authorization Boundary
**Status:** VERIFIED
**Parent plan:** `plan-m10.md` (APPROVED / IMPLEMENTATION CONTRACT)
**Sub-plan:** `plan-m10.1.md`

## Scope delivered

- Corpus source identity + append-first registry (`corpus_sources.jsonl`),
  content-addressed, idempotent, zero LLM, no document bytes stored (blob_ref
  stays None; blob store is M10.2/M10.4).
- Two new M5 authorization resource types: `corpus_source`, `corpus_unit`
  (owner decision Q1, OPTION A).
- M8 `RESOURCE_TYPES` mirror updated; existing equality regression stays green.
- Portable corpus-root resolution (explicit → `ZERO_MEM_CORPUS_ROOT` →
  `config/corpus.yaml` → None). No username / `$HOME` / repo-relative default.
- Closed `CorpusSourceRecord` contract (lifecycle + sensitivity enums) fails
  closed on unknown values.

## MEMORY != CORPUS invariant

Corpus source records live in their own registry store; nothing enters memory
JSONL. No ingestion, no normalization, no FTS, no embeddings, no graph, no
`migrate_10`. Schema remains **v9**.

## Authorization-before-influence invariant

Corpus reads route through `AuthorizedReadService` with an explicit
`resource_type`. M6.6 isolation verified: a grant scoped to `corpus_source`
does NOT authorize `corpus_unit`, `event`, `artifact`, or `project_artifact`,
and vice-versa (enforced at the facade's `_resource_allowed`).

## Verification evidence

- Focused suite `tests/unit/test_m10_1_corpus_registry.py`: **28 passed**.
- M5/M6.6/M8 regression suite (access + m8 contracts/grants/cross-profile/
  authorized_read): **258 passed** (combined run).
- **Pre-binding canonical** (clean isolated HOME): **2869 passed, 3 skipped, 0 failed**.
- **FINAL-HEAD canonical** at `749380db7813c0f42610421cc6e426299c98a81d`
  (clean isolated HOME): **2869 passed, 3 skipped, 0 failed**.
- The 3 skipped are the historical M6.6/migration skips carried from M9; no new skips.

## Files changed

- `src/access/contracts.py` — add `corpus_source`, `corpus_unit` to `_VALID_RESOURCE_TYPES`.
- `src/m8/vocabulary.py` — add `corpus_source`, `corpus_unit` to `RESOURCE_TYPES` (mirror).
- `src/corpus/__init__.py`, `src/corpus/identity.py`, `src/corpus/contracts.py`,
  `src/corpus/registry.py` — new package.
- `tests/unit/test_m10_1_corpus_registry.py` — new focused tests.
- `tests/baseline/test_project_artifacts.py` — baseline state binding updated to
  the genuine post-approval state (M10 plan APPROVED; M10.1 IN PROGRESS).

## Acceptance gate

All M10.1 acceptance criteria met: focused green; M5/M6.6/M8 regressions green;
pre-binding + FINAL-HEAD canonical green (0 failed, 3 historical skips only);
schema v9; no migration; no ingestion. M10.1 is VERIFIED.

## Next

M10.2 (Multi-format Ingestion + Structural Extraction, PDF + TXT adapters) is
authorized to begin. M10.3–M10.7 follow in order. M10.8 remains deferred (owner
decision Q5, OPTION B).
