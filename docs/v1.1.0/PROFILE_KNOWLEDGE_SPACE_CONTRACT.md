# V1.1.0 Profile and Knowledge-Space Contract

**Status:** PROPOSED — normative planning contract

**Owner:** WP-20; consumed by WP-05, WP-08, WP-12, WP-21, and WP-22

## Canonical Sources

- `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` §§3.1, 8.1–8.5, 11.2, 12.5, 17.1, 19.2–19.3, 21.1 and Appendix B.
- ADR-005 and ADR-007.

## Domain Model

- A **profile** is a versioned policy: behavior reference, knowledge priority, memory priority, access policy, tool policy, privacy ceiling, evidence budget, and write policy. It is not inherently a directory, Vault, process, or authorization grant.
- A **knowledge space** is a logical data scope. One canonical trace/note can belong to multiple spaces without duplicating its source-of-record.
- **Behavior profile** controls presentation/action behavior. **Retrieval profile and scopes** control evidence selection. They are independently selectable and auditable.
- Authorization resolves the maximum readable resources first. Access modes then narrow/prioritize inside that set; no mode creates authority.
- Cross-profile WRITE requires an explicit write grant and review/verification. Read capability never implies write capability.

## Mode Semantics

| Mode | Candidate scope | Ordering/fallback | Required authorization behavior | Empty behavior |
|---|---|---|---|---|
| `profile_first` | All resources authorized for the caller, including authorized shared/global data | Current profile/current project/current spaces first; one bounded global/shared fallback when primary evidence is insufficient | Each fallback candidate remains authorized before scoring; no hidden profile IDs/counts | `EMPTY` only after the bounded authorized fallback is exhausted |
| `explicit_union` | Exact caller-requested profile/space set plus `shared` only when explicitly included by policy | Deterministic union, canonical-ID dedupe, one global rank with provenance retaining original scopes; no implicit fallback | Caller must be authorized for every requested member; unauthorized member causes fail-closed request denial or an explicitly documented all-or-nothing policy, never a silent partial union | `EMPTY` after all authorized selected members return none |
| `isolated` | Exactly one explicitly selected profile/space/project scope | No global/shared/cross-profile fallback; rank only inside scope | Scope is validated and authorized before retrieval; linked-resource expansion is independently constrained | `EMPTY` reveals no information about outside scopes |
| `global` | All caller-authorized scopes | No profile-priority multiplier, or uses the general profile exactly as configured; still bounded | Global access is not admin access; privacy/sensitivity/source restrictions remain | `EMPTY` only for the bounded authorized global query |
| `source_restricted` | Only explicitly listed file/source/project/session/note IDs and authorized descendants | No fallback; expansion cannot cross source boundary | Every source locator and linked artifact is authorized and path-safe; nonexistent/hidden sources are non-probing | `EMPTY` reveals nothing about excluded sources |

## Ranking and Deduplication

Authorization filters run before lexical/dense fusion and before counts. Candidate ordering uses deterministic documented factors: base retrieval score, profile/space priority, memory scope, verification, source quality, temporal validity, provenance completeness, and conflict penalty. Canonical `trace_id`/artifact identity is the primary dedupe key; near-duplicate handling may group evidence but never delete or hide provenance. Tie-breaking is stable and versioned.

## Provenance Requirements

Every returned or projected item retains canonical trace/source IDs, original profile/space memberships, project/task/session relation, timestamp/time validity, lifecycle and verification state, and any transformation/projection version. A union result cannot rewrite provenance to appear native to the requesting profile.

## Configuration Defaults

The canonical default profile is `general-assistant` with `default_access=global`, `retrieval_mode=profile_first`, `global_fallback=true`, `cross_profile_search=true`, provenance required, and the approved bounded evidence budget. Exact numeric evidence defaults remain governed by WP-06/WP-13 and begin from canonical 5 primary, 3 supporting, 6,000 evidence-token maximum unless benchmark evidence changes them through review.

## Acceptance Matrix

### `profile_first`

- Given current profile A, authorized shared/global evidence, and profile B evidence, when A has sufficient primary evidence, then B/global fallback is not queried or returned.
- Given insufficient A evidence and authorized global fallback, when retrieval expands once, then A-priority remains first, provenance is unchanged, and the total candidate/evidence budget is not increased.
- Given B is unauthorized, when fallback runs, then B content, identifiers, counts, and ranking influence are zero.

### `explicit_union`

- Given authorized A and B, when `explicit_union=[A,B]`, then results are deduplicated by canonical identity, globally ranked deterministically, and each result retains A/B source provenance.
- Given the caller lacks B, when requesting `[A,B]`, then the request fails closed before retrieval and returns no partial A result under the all-or-nothing contract.
- Reversing `[A,B]` to `[B,A]` produces identical ordered results and pagination.

### `isolated`

- Given data exclusively in B, when A queries isolated A, then no B record, identifier, count, score contribution, neighbor, artifact, or conflict metadata appears.
- Given an allowed A trace links to B, when expanding, then the B link is withheld without revealing existence.
- No configuration flag, empty result, or retry may enable fallback.

### `global`

- Given caller-authorized A/B/shared data, when global mode runs, then profile weighting is disabled/generalized as documented while privacy, source, lifecycle, and evidence budgets remain enforced.
- Global mode cannot read a profile outside caller authorization or raise a privacy ceiling.

### `source_restricted`

- Given sources S1 and S2, when restricted to S1, then no S2 evidence or influence appears, including through dense retrieval, neighbors, graph edges, or duplicated content.
- Malformed, path-traversing, hidden, or unauthorized source selectors fail closed before content access.

## Cross-Mode Gates

- Positive, negative, cross-profile leakage, privilege-injection, concurrent-request identity, pagination, cache isolation, timeout, and malformed-request tests pass for every mode.
- The same fixtures pass through embedded API, MCP/local transport, Hermes adapter, and generic client.
- Normal operations perform zero LLM calls, use bounded candidates/evidence, and emit content-safe mode/scope diagnostics.
- Adding a profile or knowledge system follows the canonical versioning and benchmark workflow in DOCX §§19.2–19.3.
