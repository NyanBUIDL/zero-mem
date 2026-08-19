# WP-32 Technical Design

**Status:** PLANNING

## Authority and boundary

WP-32 consumes only authorized, typed evidence from WP-29/M7. Authorization precedes candidate discovery. Context is a derived DATA envelope for Hermes; it is not canonical memory, instruction, transcript state, or a new retrieval engine.

## Existing technologies

- Python 3.11 project environment;
- standard-library dataclasses, sorting, JSON, and bounded string/byte operations;
- existing M7 `EvidenceSet`, `EvidenceItem`, `budget.py`, `envelope.py`, `hardening.py`;
- existing M8 temporal/provenance/calibration metadata;
- existing Hermes PluginContext adapter from WP-31.

No new dependency is justified or approved.

## Algorithm

```text
authorized EvidenceSet
→ validate route and evidence invariants
→ reject/mark external-current when live data is required
→ preserve provenance/freshness/lifecycle/verification fields
→ deterministic stable ordering with explicit tie-breaks
→ apply governed primary/supporting and token/byte budgets
→ omit complete items or safely shorten only according to contract
→ serialize DATA-only envelope
→ return bounded context without mutating input or canonical state
```

Authorization is not repeated by context assembly and is never deferred until after packing; it is consumed as a precondition from WP-29.

## Ordering

The exact ranking weights remain TBD until repository tests establish whether existing M7 ordering is sufficient. No arbitrary new weights may be introduced. Any tie-break must be stable, explicit, and include a final immutable evidence identity.

## Freshness and provenance

Freshness uses the existing M8 temporal contract: `TemporalDimension.TRANSACTION` or `TemporalDimension.VALID`, explicit `as_of`, and `TEMPORAL_VALID`/`TEMPORAL_UNKNOWN`/`TEMPORAL_INVALID` metadata. Missing time remains unknown; no wall clock or inferred timestamp is permitted. `EXTERNAL_CURRENT` remains a route-level live-data requirement, not a temporal shortcut.

## Budget

Reuse governed M7 ceilings unless the WP-32 acceptance contract requires a narrowly documented extension. Token estimation remains deterministic and explicitly approximate. Client requests cannot raise ceilings. Whole-item omission is preferred; output must not split UTF-8/code points or strip provenance. Omitted counts describe only authorized candidates.

## Data structures

Expected reuse: immutable `EvidenceSet`, immutable `EvidenceItem`, `BudgetSelection`, and serialized string envelope. A new immutable context result is permitted only if existing structures cannot express status, omitted count, estimated tokens, freshness, and provenance safely.

## Concurrency/lifecycle

Assembly is synchronous, bounded, and read-only. No worker, queue, retry, lock, or persistent lifecycle is needed. Hermes callback failures remain isolated by WP-31.

## Error/status vocabulary

Reuse existing typed route/reason/status values. New statuses require evidence and documentation. Fail closed on malformed evidence, unavailable freshness metadata where currentness is required, serialization failure, or budget invariant violation.

## Complexity

Sorting is O(n log n) over the already-authorized bounded candidate set; packing is O(n). Output memory is O(budget), with no unbounded history load introduced.

## Security constraints

No raw SQL, direct store access, authorization bypass, secret logging, prompt-role promotion, path inference, or canonical write. Input strings are escaped only at the final DATA serialization boundary, while authorization/ranking use structured values.

## Compatibility and rollback

Existing M7/Hermes call signatures remain compatible. No schema migration. WP-32-owned code can be removed without affecting canonical events or derived storage.

## Open technical decisions

`TBD — exact freshness field/status mapping requires inspection of existing M8 temporal contracts before implementation.`
