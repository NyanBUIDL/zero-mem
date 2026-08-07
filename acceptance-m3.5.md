# M3.5 — Final Acceptance Evidence

**Milestone:** M3.5 — Verification and lifecycle-aware retrieval
**Status:** VERIFIED
**M3 overall:** IN PROGRESS (M3.6 not started)

## Verified starting state

- M0/M1/M2: VERIFIED
- M3.1/M3.2/M3.3/M3.4: VERIFIED
- M3.5: not started at increment open (HEAD `42fd4b7`)
- SQLite schema: v6; no M3 migration (none)
- SQLite access: TRUE READ-ONLY (`mode=ro` + `PRAGMA query_only=ON`)
- Working tree: clean

## Critical vocabulary correction (during implementation)

The approved M3 plan's §5 examples listed verification-status examples such as `verified`,
`unverified`, `pending`, `rejected`. These do **not** exist in the verified M1/M2 contract.
The authoritative vocabularies (from `src/capture/event_types.py`) are:

- **VerificationStatus**: `none`, `direct_tool_output`, `user_confirmation`,
  `deterministic_verification`, `approval`
- **LifecycleStatus**: `raw`, `observed`, `candidate`, `confirmed`, `active`, `superseded`,
  `conflicted`, `archived`, `deleted`

M3.5 deliberately uses the **real** enum values (imported verbatim from the verified contract) and
rejects any other value with `invalid_verification_status` / `invalid_lifecycle_status`. No statuses
were invented and no schema migration was made.

## Implementation

### Files
- `src/retrieval/verification.py` (new): `validate_verification_status`, `validate_lifecycle_status`,
  `get_provenance`, `list_deleted`, `get_tombstone`, `get_deletion_audit`, `search_filtered`.
- `src/retrieval/models.py`: added `INVALID_VERIFICATION_STATUS`, `INVALID_LIFECYCLE_STATUS` codes and
  `ProvenanceMeta` dataclass.
- `src/retrieval/query.py`: `_build_where` now validates `verification_status` / `lifecycle_status`
  against the real enum vocabularies (exact equality, no invented values).
- `src/retrieval/__init__.py`: exported new public API.

### Behavior delivered
- **Exact verification filter**: equality over `zm_meta.verification_status`; unknown value →
  `invalid_verification_status`.
- **Exact lifecycle filter**: equality over `zm_meta.lifecycle_status`; unknown value →
  `invalid_lifecycle_status`; `deleted` on normal path → `unsupported_filter` (Decision B).
- **Claim-not-fact**: `assistant_claim` / `user_statement` / `inference` / `tool_observation` /
  `verified_state` are surfaced as `event_type` labels only. An unverified `assistant_claim` is never
  promoted to a fact and never reordered above verified results.
- **Provenance enrichment** (`get_provenance`): read-only wrapper over the verified M2
  `zm_provenance` projection (`verifier`, `evidence_ref`, `verification_status`, `recorded_at`).
  Stored `confidence` is returned as-is; never recomputed.
- **Administrative deleted-inspection passthrough**: `list_deleted` / `get_tombstone` /
  `get_deletion_audit` wrap the verified M2 helpers read-only; the ONLY sanctioned route to deleted
  records, separate from normal retrieval.
- **FTS composition** (`search_filtered`): FTS5 selects text candidates; verification/lifecycle
  filters applied as exact AND predicates; deterministic ordering unchanged; no ranking by
  verification/recency/confidence.
- **Relation composition**: M3.4 relation results already carry `target: EventView`, which preserves
  `verification_status` / `lifecycle_status` of related events (tested).
- **Supersession / conflict**: returned verbatim from `zm_lifecycle`; no replacement relationship
  invented, no winner chosen, no LLM reasoning.
- **Deterministic ordering**: `(created_at ASC, event_id ASC)`; verification/lifecycle state never
  alters order.
- **Pagination**: reuses M3.2 cursor; fingerprint binds text + verification + lifecycle so a cursor is
  not reusable across differently-filtered queries (tested: `cursor_query_mismatch`).
- **TRUE READ-ONLY**: `mode=ro` + `PRAGMA query_only=ON`; no writes / migrations / LLM / network.

## Exclusions honored
No truth inference; no automatic fact promotion; no conflict resolution; no automatic supersession;
no trust scoring; no relevance/recency/confidence ranking; no vector/semantic search; no LLM query
rewriting; no automatic memory selection; no context injection; no authorization/access control;
no M4 project state; no Requirement Registry / Decision Log mutation; no MCP; no Obsidian; no schema
migration; no M3.6 (integration/final acceptance) behavior.

## Test results

- M3.5 focused (`tests/unit/test_m3_verification.py`): **56 passed**
- M3.1 + M3.2 + M3.3 + M3.4 + M3.5 combined: **205 passed**
- Full canonical suite (`tests/ -q`, no deselect): **539 passed, 3 skipped**
  - The 3 skipped are the pre-existing environment-bound baselines (not M3.5-attributable).
- `test_readonly_no_mutation` (M3.1) was updated to use the real `deterministic_verification` status
  value (the prior `verified` literal was an invented value that the new validator correctly rejects).

## Acceptance criteria

- [x] all mapped M3.5 acceptance criteria pass
- [x] M3.1–M3.4 remain VERIFIED
- [x] focused M3.5 passes (56)
- [x] combined M3.1–M3.5 passes (205)
- [x] canonical suite passes (539 passed, 3 skipped) — no deselect
- [x] assistant_claim never silently promoted (claim-not-fact tests)
- [x] conflict remains unresolved (conflict test)
- [x] supersession is read-only (superseded test)
- [x] lifecycle filtering is deterministic (per-status tests)
- [x] verification filtering is deterministic (per-status tests)
- [x] pagination remains stable (tests)
- [x] TRUE READ-ONLY proof passes (Snapshot before/after on sqlite_master/counts/meta/JSONL)
- [x] no ranking exists (no_ranking test)
- [x] no schema migration exists
- [x] no M3.6 behavior
- [x] working tree clean after commit

## Conclusion

M3.5: VERIFIED. M3 overall: IN PROGRESS. Next: M3.6 — Integration, performance, and final acceptance.

## Files changed

- src/retrieval/verification.py (new)
- src/retrieval/models.py
- src/retrieval/query.py
- src/retrieval/__init__.py
- tests/unit/test_m3_verification.py (new, 56 tests)
- tests/unit/test_m3_query.py (fixed an invented `verified` literal → `deterministic_verification`)
