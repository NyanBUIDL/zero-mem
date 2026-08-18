# WP-03 Closure Evidence

## Production call graph

Real rollout harness → discovery/registration → corpus blob/registry → derived projection → authorized retrieval → bounded graph/evidence path → rebuild and consistency checks. No helper-only benchmark was used.

## Verified gates

- Focused capture, ingest, retrieval, and injection behavior: PASS.
- Bounded candidate/ranking work and deterministic repeated retrieval: PASS.
- Canonical/derived durability preserved: PASS.
- 1k real-corpus run: 1000 files registered/projected; second sync unchanged; rebuild equivalent; retrieval repeated deterministically; median query latency 0.082ms.
- 10k real-corpus run: 10000 files registered/projected; registration 179.6s; projection 7.9s; second sync 12.5s with no new sources/units; retrieval median 0.713ms, p95 0.922ms, deterministic repeat; rebuild 8.2s equivalent.
- 100k/1M disposition: not fabricated or extrapolated; requires a separately authorized operator corpus/run and remains outside this bounded evidence.

## Evidence

- Focused performance/injection/rebuild tests: `265 passed`.
- Full regression before WP-03 closure: `3154 passed, 5 skipped, 0 failed`.
- `git diff --check`: pass.

## Boundary audit

No dependency was added. No Product Memory, canonical DOCX, remote Git, or release claim was changed. The benchmark wrapper delegates to the existing real rollout harness.

## Decision

`PASS — WP-03 VERIFIED`
