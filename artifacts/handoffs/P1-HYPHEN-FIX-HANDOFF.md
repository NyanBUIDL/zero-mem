# P1 — FTS Hyphen Normalization Fix — Handoff

## Metadata
- Package: `zero-mem` (tree: `zero-mem-v123-engineering`)
- Branch: `v124-post-release-closure`
- Date: 2026-08-22
- Authorized scope: Part 2 of P1-COMMIT-AND-HYPHEN-FIX (local only, no push/tag/release/merge/remote)
- Status: **IMPLEMENTED + VERIFIED** (tests green, benchmark after shows hyphen probe hit)

## Root cause (reproduced, not assumed)
FTS5 `zm_fts` is built with the default `unicode61` tokenizer, which splits
`walk-forward` into `walk` + `forward` at **index** time. But in an unquoted MATCH
expression FTS5 parses a bare `-` as a **column-filter operator** (FTS5 negation is
the `NOT` keyword, not `-`), so `walk-forward` produced:

```
QueryError (operational) "no such column: forward"  ->  malformed_fts_expression
```

swallowed into an empty candidate set → research retrieval returned ZERO for
hyphenated compound terms. Verified by direct probe before the fix:

| query | before | after |
|---|---|---|
| `walk-forward validation` | `malformed_fts_expression`, 0 hits | `E-QUANT` hit, `error=None` |
| `walk forward validation` | `E-QUANT` hit | unchanged |

## Fix (minimal, deterministic, zero-LLM, no schema/migration)
Added `_normalize_fts_query(text)` in `src/retrieval/search.py`:

```python
def _normalize_fts_query(text: str) -> str:
    return " ".join(text.split()).replace("-", " ")
```

Applied in `search_text` (before the cursor fingerprint and MATCH) and in the M3.5
composition path `verification.search_filtered`. Collapsing whitespace matches the
existing `make_fingerprint` normalization, so cursor binding semantics are unchanged
for well-formed queries.

Why replace **every** `-`: FTS5 has no `-token` NOT operator; a bare `-` is always a
column filter. Replacing all hyphens re-tokenizes the query exactly the way the index
already tokenized the content. Legitimate FTS5 syntax (quotes, `OR`, `AND`, `NOT`,
grouping) contains no `-`, so it is untouched.

## Changed files
- `src/retrieval/search.py` — `_normalize_fts_query` helper + apply in `search_text`
- `src/retrieval/verification.py` — apply normalization in `search_filtered`
- `tests/unit/test_m3_fts.py` — 6 new regression tests (hyphen hit; whitespace-equivalence;
  well-formed no-op; true-no-match empty not error; `-` is not NOT (uses `NOT` keyword);
  `search_filtered` path)
- `benchmarks/run_memory_benchmark.py` — new probe `C-QUANT-HYPHEN`

No `src/corpus/*`, no `project-state.yaml`, no schema/migration, no packaging, no Hermes core.

## Verified evidence (real command output)
Focused tests:
```
.venv-v124/bin/python -m pytest tests/unit/test_m3_fts.py -q --disable-warnings --no-header -p no:cacheprovider
38 passed in 0.40s
```

Full suite (ISOLATED TMPDIR/HOME, v1.2.4 convention):
```
.venv-v124/bin/python -m pytest tests/unit tests/integration -q --disable-warnings --no-header -p no:cacheprovider
3375 passed, 5 skipped in 81.23s   # baseline 3369 + 6 new; 0 failed
```

Benchmark before/after (`zero-mem-dev-data/evidence/p1-hyphen-fix/`):
- `before-benchmark.json`: 29 queries, mean_recall@8 = 0.4058, mean_mrr = 0.3497
- `after-benchmark.json`:  30 queries, mean_recall@8 = 0.4305, mean_mrr = 0.3767
- `C-QUANT-HYPHEN` after: recall@8 = 1.0, evidence `["E-QUANT"]` (was impossible before)
- `C-QUANT` unchanged: recall@8 = 1.0, `["E-QUANT"]`
- `B11` still recall@8 = 0.0 (out of scope — finding #2 FTS-AND brittleness: `Only`/`use`/`defines` are out-of-vocabulary)
- determinism `deterministic_repeat = True`; isolation `True`; stale_safe_rate 1.0; all other metrics unchanged except the expected recall/mrr rise from the new passing probe.

Graphify re-extraction (read-only, disposable, code-only): `search_text` now calls
`_normalize_fts_query`; importers are `authorized_read.py` + `retrieval/__init__.py`
only (single retrieval layer). Output at `zero-mem-dev-data/graphify/v124-eval-p1-hyphen/`.

Commits (local only, not pushed):
- `f32d18d` bench: add deterministic memory recall/token benchmark harness (P1) [Part 1]
- `9752bc9` fix(retrieval): normalize hyphenated FTS query terms and fall back safely
- `8fecebe` bench: add hyphenated-query regression probe to memory benchmark

## Risks
- The FTS AND brittleness (finding #2) is intentionally NOT addressed here; multi-term
  queries with out-of-vocabulary words still return zero. A separate WP is required.
- Knowledge-space scope is still not enforced on memory events (finding #4); the hyphen
  fix does not change isolation guarantees — it only stops hyphenated terms from being
  discarded.
- `_normalize_fts_query` collapses all whitespace then all hyphens; a query that is a
  bare `-` or `--` normalizes to empty/whitespace. `search_text` already rejects empty
  text (`empty_fts_text`) before normalization, and `--` normalizes to whitespace which
  then fails the FMatch path safely (no raw SQL injection — MATCH is parameterized).

## Reproduce
```bash
cd "/home/lenovo/Hermes Workspace/zero-mem-v123-engineering"
export TMPDIR=/dev/shm/zm-v124-test && export HOME=/tmp/zm-tmp && mkdir -p "$TMPDIR" "$HOME"
.venv-v124/bin/python -m pytest tests/unit/test_m3_fts.py -q --disable-warnings --no-header -p no:cacheprovider
.venv-v124/bin/python benchmarks/run_memory_benchmark.py --json | python -c "import sys,json; d=json.load(sys.stdin); print([ (r['id'],r['recall@8'],r['evidence_ids']) for r in d['rows'] if r['id']=='C-QUANT-HYPHEN'])"
```

## Authorization
Local commits authorized. NOT authorized / NOT performed: push, tag, release, merge,
remote modification, schema/migration, `src/corpus/*`, `project-state.yaml`, packaging.