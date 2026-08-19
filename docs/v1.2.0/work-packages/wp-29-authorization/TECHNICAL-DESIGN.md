# WP-29 Technical Design

## Technologies/dependencies

Python 3.11 standard library, existing `src.access` contracts/policy/grants/resolver/facade, SQLite read-only connection, existing retrieval/project-memory APIs. No new dependency or schema.

## Algorithm

```text
AccessRequest + explicit identity
→ validate/normalize literals and identifiers
→ evaluate base policy
→ resolve only authorizing READ grants for subject
→ compose restrictive effective scopes
→ if denied: typed denial, zero low-level calls
→ discover candidates using per-scope predicates
→ defensive post-validation against each scope
→ deduplicate
→ deterministic sort and keyset cursor binding
→ bounded response
```

Authorization is before candidate discovery, not merely before serialization.

## Data structures/statuses

- `AccessRequest`, `AllowedScope`, `AccessDecision`, `AuthorizedReadGrant`, `EffectiveReadScope`.
- `AuthorizedResult`: allowed/denied, fixed reason code, items, query metadata, sanitized downstream error, cursor.
- Reason codes are the existing `ReasonCode` enum; no raw SQL/path/exception text.

## Scope semantics

Profile grants restrict profile; project grants restrict project and do not implicitly grant another profile; knowledge-space grants require a matching existing row predicate; global/null-profile reads are explicit policy behavior; isolated mode never expands scope. READ grants cannot authorize WRITE.

## Ordering/pagination

Merge per-scope results, deduplicate by stable event/resource identifier, sort by `(created_at, event_id)` or existing owner-defined stable key, and bind cursors to request plus effective-scope fingerprint. Unauthorized rows are absent before limit/count/cursor generation.

## Concurrency/locking/retry

Reads use existing read-only/query-only stores. No authorization retry, mutation, or cache of mutable grants. Grant resolution occurs per request from current derived state.

## Security constraints

No caller-supplied boolean can widen scope. Deny must not query low-level backends. Post-validation is defense-in-depth, not the primary authorization placement. No secret/raw content/error leakage. Canonical JSONL is never written.

## Compatibility/complexity

Preserve existing M5/M8 APIs and reason codes. Candidate work is proportional to authorized predicates/results, not total unauthorized history where backend supports predicates; per-grant decomposition may add bounded queries proportional to grants.

## Prohibited approaches

Retrieve-all-then-filter, rank-before-auth, count-before-auth, pagination-before-auth, relationship expansion as authorization, inferred identity, WRITE/READ conflation, and silent fallback to global scope.

## Open technical decisions

None blocking. Benchmark optimization is deferred; correctness and leakage gates take priority.
