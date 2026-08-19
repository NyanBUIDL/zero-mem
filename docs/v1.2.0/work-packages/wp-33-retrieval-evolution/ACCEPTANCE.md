# WP-33 Acceptance

**Status:** VERIFIED

## Functional acceptance

- A reproducible labeled lexical benchmark exists with versioned corpus/query inputs.
- Metrics and latency are computed deterministically from recorded runs.
- Authorization remains before candidate discovery in all measured paths.
- Existing lexical retrieval behavior remains compatible and deterministic.
- Any optional derived index has typed missing/stale behavior and a rebuild path.

## Negative/security acceptance

- Unauthorized rows cannot enter benchmark candidates, rankings, counts, or reported identifiers.
- No secret or credential is written to benchmark artifacts.
- No vector/hybrid dependency is introduced without measured justification and documented threat/operational review.

## Scale and limitation acceptance

Attempt the Master Plan scales (1k, 10k, 100k, 1M) when feasible. If a scale is not feasible, record the exact limitation and do not claim a result.

## Regression and review

Run targeted retrieval/authorization tests, benchmark contract tests, compileall, diff-check, isolated full regression, Graphify read-only analysis, and independent fail-closed review.

## Exit gate

WP-33 is VERIFIED only when benchmark evidence is reproducible, the lexical baseline or measured improvement is documented, all security/compatibility checks pass, and no unresolved architecture or dependency escalation remains.
