# M7.3 — Authorized evidence eligibility + bounded EvidenceSet

Status: VERIFIED (2026-08-09)
Milestone: M7 (Controlled Injection + Master Zero-Mem Runtime Switch) — increment 3
Schema version: 8 (unchanged; no migration)

## Scope

M7.3 constructs bounded, authorized evidence sets from memory-route decisions.
Pipeline (no Hermes context mutation, no LLM, no network, no writes):

    MemoryRouteDecision
      -> route-to-retrieval mapping (M5 AuthorizedReadService; authorization BEFORE retrieval)
      -> eligible authorized candidates (eligibility.py)
      -> conflict grouping
      -> deterministic bounded selection (budget.py)
      -> EvidenceSet

M7.3 reuses the VERIFIED M5 AuthorizedReadService as the authorized-read boundary.
It performs NO injection, NO writes, NO LLM, NO network, NO GrantAdmin, NO raw
SQLite/JSONL access. Resource-type isolation and linked-resource re-checks are
already enforced by M5; M7.3 reuses them unchanged. M7.3 produces only a structured
EvidenceSet for a later increment (M7.4) to consume.

## Modules

- `src/integration/m7/__init__.py` — package exports (updated for M7.3).
- `src/integration/m7/contracts.py` — `EvidenceRole`, `EvidenceItem`,
  `EvidenceSet` (immutable frozen dataclasses; no content injection).
  Also retains M7.2 contracts (`MemoryRoute`, `ReasonCode`, `RouterRequest`,
  `MemoryRouteDecision`, `zero_mem_runtime_enabled()`).
- `src/integration/m7/eligibility.py` — `is_eligible()`, `EligibilityResult`.
  Pure functions over normalized item attributes. No LLM, no DB, no network.
- `src/integration/m7/budget.py` — `select_evidence()`, `estimate_tokens()`,
  `BudgetSelection`. Deterministic 5+3 budget; whole-item omission;
  stable ordering using existing trustworthy metadata.
- `src/integration/m7/evidence_builder.py` — `build_evidence_set()`.
  Route-to-M5-retrieval mapping; authorization-before-retrieval; resource-type
  isolation preserved; conflict grouping; deterministic bounded selection.
- `tests/unit/test_m7_3_evidence_builder.py` — 31 focused tests covering all
  required M7.3 behavior.

## Authorization hard rule

Every protected evidence candidate passes the existing M5 AuthorizedReadService
read boundary BEFORE becoming an evidence candidate. M7.3 never retrieves globally
and filters unauthorized results later. The AccessRequest is built from explicit
RouterRequest fields (verbatim, no inference). Resource-type isolation (M6.6 fix)
is preserved: an artifact-only grant does not authorize event, relation,
requirement, decision, verification, or state evidence.

## Eligibility gate (deterministic, second independent gate after M5 authorization)

- Lifecycle: `deleted` excluded (hard). `superseded`/`archived` not PRIMARY
  (supporting only if `allow_non_current_as_supporting=True`). `raw`/`observed`/
  `candidate` supporting only.
- Memory type: `assistant_claim`/`inference`/`user_statement` not promoted to
  PRIMARY (supporting only; claim-not-fact).
- Sensitivity ceiling: M3 events above the ceiling (default "high") excluded.
  M4 items carry no `sensitivity` field and are already governed by M5.
- Provenance: fail closed if `evidence_id` or (`created_at` or `source_event_id`)
  is missing.
- Role classification: active+verified -> PRIMARY; `decision`/`verified_state`/
  `tool_observation` -> PRIMARY; `confirmed` lifecycle -> PRIMARY. All other
  eligible items are SUPPORTING.

## Budget (deterministic)

- max 5 primary, max 3 supporting, max 8 total.
- Token budget: 6000 (default ~3k-6k target envelope). Whole-item omission from
  the least-important tail when over budget (no mid-claim truncation).
- `omitted_count` reflects only authorized eligible items omitted by the budget;
  unauthorized items are never counted (no existence leak).
- Stable ordering: (role_rank, verified_rank, lifecycle_rank, created_at,
  evidence_id) — deterministic across runs.

## Conflict representation

Items sharing a trace_id with disagreeing lifecycle statuses (or any
`conflicted` lifecycle) are grouped into a conflict dict with `resolved: False`.
No winner is invented; IDs and provenance are preserved.

## Required behavior verification

1. no_memory -> zero retrieval, zero tokens, zero evidence ✅
2. external_current -> insufficient_evidence=True, external_current_required=True,
   zero evidence (no stale-current substitution) ✅
3. same-profile authorized evidence ✅
4. cross-profile denial (E4 not in evidence) ✅
5. exact project grant allow ✅
6. wrong resource-type grant deny (artifact-only -> no event/decision) ✅
7. revoked grant deny ✅
8. linked targets independently authorized (each M4 resource_type independently
   gated by grant) ✅
9. deleted absent ✅
10. superseded not PRIMARY ✅
11. conflict represented without fake winner ✅
12. assistant_claim not promoted to verified fact ✅
13. sensitivity ceiling enforced ✅
14. provenance preserved ✅
15. max 5 primary ✅
16. max 3 supporting ✅
17. max 8 total ✅
18. deterministic token budget ✅
19. unauthorized evidence excluded from omitted_count ✅
20. deterministic ordering ✅
21. artifacts metadata-only (content_source="metadata_only") ✅
22. failure isolation (dead store -> empty/exception, no crash) ✅
23. no writes ✅
24. no GrantAdmin (static audit) ✅
25. zero LLM (static audit: no openai/llm/httpx/requests/aiohttp/socket/urllib) ✅
26. zero network (static audit) ✅
27. schema v8 ✅
28. M7.1 master OFF -> zero M7.3 retrieval (master switch upstream; M7.1 tests
    re-pass) ✅
29. M7.2 router behavior unchanged (59 focused tests re-pass) ✅
30. no M7.4 injection (no injection_adapter.py; no pre_llm/register_hook) ✅
31. no M8 (no vector retrieval/embeddings) ✅

## Static security audit

- AST import analysis: no `AuthorizedWriteService`, `GrantAdminService`,
  `migrations`, `openai`, `llm`, `httpx`, `requests`, `aiohttp`, `socket`,
  `urllib` imported in any M7.3 module.
- No `GrantAdminService` or `create_grant`/`revoke_grant` in evidence_builder.py.
- No `pre_llm` or `register_hook` in evidence_builder.py.
- No `injection_adapter.py` exists.
- No `evidence_selector.py` exists.
- No vector retrieval or embeddings references in any M7 file.

## Tests / acceptance

- Focused suite `tests/unit/test_m7_3_evidence_builder.py`: 31 passed.
- M7.2 focused suite: 59 passed (regression).
- M7.1 focused suite: 40 passed (regression).
- M5 auth/grant regressions: 250 passed.
- M6 integration regressions: 387 passed (in full canonical; 4 test-ordering
  artifacts when M6.6 runs before M6.1 in a custom subset — not product defects;
  full canonical uses alphabetical order where M6.1 precedes M6.6).
- M1 regressions: 82 passed.
- M3 regressions: 283 passed.
- M4 regressions: 243 passed.
- Full canonical (clean isolated HOME): 1627 passed, 3 skipped, 0 failed
  (pre-binding) and 1627 passed, 3 skipped, 0 failed (post-binding final HEAD).
- Ad-hoc verifier (temporary, OS-temp, path-safe): 25/25 PASS, then removed.

## Deferred (NOT implemented in M7.3)

- M7.4 Hermes controlled context-injection adapter/envelope
- M7.5 conflict / insufficient-evidence / prompt-injection hardening
- M7.6 performance, security, end-to-end acceptance
- M8 (graph/temporal/vector/entity retrieval, advanced calibration, Obsidian
  projection, corpus expansion)

## Files changed

- `src/integration/m7/__init__.py` (updated: M7.3 exports)
- `src/integration/m7/contracts.py` (updated: EvidenceRole, EvidenceItem, EvidenceSet)
- `src/integration/m7/budget.py` (new)
- `src/integration/m7/eligibility.py` (new)
- `src/integration/m7/evidence_builder.py` (new)
- `tests/unit/test_m7_3_evidence_builder.py` (new)
