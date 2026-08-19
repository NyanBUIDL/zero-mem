# WP-32 Acceptance

**Status:** VERIFIED

## Functional acceptance

- Identical authorized inputs produce byte-stable context output.
- Stable ordering has explicit deterministic tie-breaks.
- Primary/supporting roles and governed evidence budgets are respected.
- Provenance, source, trace, lifecycle, verification, and freshness metadata survive selection/serialization.
- UTF-8/code-point safety is preserved; no malformed output is produced.
- `EXTERNAL_CURRENT` never injects stale historical memory as current information.
- Context remains DATA-only and does not mutate the original request, evidence, transcript, canonical JSONL, or derived SQLite.

## Negative/security acceptance

- Unauthorized candidates are absent before packing and cannot affect ordering, counts, omitted metadata, or output.
- Prompt-role markers and envelope delimiters in evidence are escaped/sanitized.
- Malformed evidence, unavailable required freshness, serializer failure, and budget violation fail closed.
- Client values cannot raise governed token/byte/item limits.
- No LLM/network call is required.

## Failure/restart/regression

- Unit tests cover empty, oversized, conflicting, stale, external-current, malformed, and non-serializable cases.
- WP-29 authorization and WP-31 Hermes restart/failure-isolation tests remain green.
- Isolated full regression excluding the known baseline artifact mismatch passes.
- Compileall, diff check, final Graphify, and independent fail-closed review pass.

## Exit gate

WP-32 becomes VERIFIED only with executable focused evidence, security/leakage-negative evidence, isolated regression, and independent review. Otherwise remain VERIFYING/FAILED_VERIFICATION.
