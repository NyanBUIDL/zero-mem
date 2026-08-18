# V1.1.0 Agent Interface and MCP Capability Contract

**Status:** PROPOSED — normative planning contract

**Owners:** WP-08 (capability semantics), WP-21 (transport binding), WP-07 (Hermes adapter only)

## Sources and Scope

- Canonical DOCX §§11.1–11.5, 13.1–13.3, 16.1, 17.1–17.2, 18 stage 6 and Appendix C.
- ADR-001, ADR-002, ADR-005, and ADR-006.
- Exact-master M6 dispatcher/MCP wrapper and its ten read-only operations are compatibility evidence, not the v1.1.0 external naming authority.

This contract is transport-neutral. The same request, authorization result, evidence order, status, error code, timeout classification, and provenance must be produced by the embedded public API and every supported local transport. A transport may add framing metadata but cannot change domain semantics.

## Common Request Contract

Every request contains:

- `contract_version`: independent of package patch version;
- `request_id` and optional idempotency key for retried non-mutating calls;
- explicit `caller_id` and `requesting_profile_id`; neither may be inferred from cwd, endpoint, session text, or prior calls;
- `access_mode`: `profile_first`, `explicit_union`, `isolated`, `global`, or `source_restricted`;
- optional `target_profile_ids`, `knowledge_space_ids`, `project_id`, `session_id`, `source_ids`, and time interval;
- `privacy_ceiling`, requested evidence budget, and a deadline no greater than configured service maximum;
- no caller-supplied grant, admin flag, verification override, SQL, raw path, or policy-bypass field.

Unknown fields and ambiguous identity fail closed with `INVALID_REQUEST` or `IDENTITY_REQUIRED` before storage access.

## Common Response Envelope

Every successful or empty response contains:

- `contract_version`, `request_id`, `status`, `route`, `active_profile`, and `used_scopes`;
- `evidence` in deterministic order, with each item carrying `trace_id`, source/artifact locator, timestamp/time validity, profile/project/task relation, lifecycle status, verification, sensitivity-safe content/reference, score components or selection reason, and transformation/projection metadata when applicable;
- `conflicts`, `insufficient_evidence`, `omitted_count`, applied budget, canonical/derived watermark or freshness state, `index_version`, and `latency_ms`;
- no prompt, secret, raw credential, unauthorized identifier, SQL, traceback, or filesystem path beyond an authorized source locator.

`EMPTY` is a successful authorized query with zero matches. `POLICY_DENIED`, `SOURCE_RESTRICTED`, `CAPABILITY_UNAVAILABLE`, `STALE_DERIVED`, `DEADLINE_EXCEEDED`, `OVERLOADED`, and `DOWNSTREAM_ERROR` are distinct typed states. Denied and hidden resources use non-probing-safe messages.

## Determinism and Deadline Rules

- Normal routing, filters, authorization, deduplication, ranking, pagination, conflict grouping, and envelope construction make zero LLM calls and no mandatory network call.
- Stable inputs, canonical watermark, configuration, and index version produce stable ordering and pagination tokens.
- Authorization is applied before unauthorized content can influence scoring, fusion, expansion, counts, or error detail.
- A deadline may stop derived retrieval but cannot pretend an already committed canonical write was rolled back. These four MVP capabilities are read-only.
- The transport enforces configured request/response byte ceilings and bounded concurrency; overflow is explicit, never an unbounded queue.

## `zero_mem.search`

**Purpose:** Return a bounded evidence set for a query or memory route across authorized memory/corpus scopes.

**Inputs:** Common request fields plus `query`, optional `memory_route`, `top_k`, `max_evidence_tokens`, `max_supporting`, `include_neighbors`, `ordering_mode`, and `require_provenance=true`. `top_k` and budgets are capped by server/profile policy; callers cannot raise the ceiling.

**Outputs:** Common envelope with primary/supporting evidence, deterministic scores/selection reasons, conflict sets, omitted count, freshness, and insufficiency reason.

**Scope and authorization:** WP-20 resolves access-mode semantics; WP-05 executes only against the authorized scope. `isolated` and `source_restricted` never fall back. `profile_first` may use authorized global/shared fallback after current-profile priority.

**Empty/error/timeout:** `EMPTY` means an authorized complete search found none. `INSUFFICIENT_EVIDENCE` means evidence exists but fails threshold/closure. `STALE_DERIVED` reports freshness rather than silently querying canonical JSONL. Deadline returns partial results only when the contract marks them `partial=true` with omitted/reason metadata; otherwise it returns `DEADLINE_EXCEEDED` and no evidence.

**Compatibility:** Existing `memory_query`/`memory_search` and related project readers may be mapped internally; the canonical external name and response contract are stable and versioned.

**Acceptance:** Given identical data/configuration, repeated calls are order-identical; unauthorized rows cannot change authorized scores; all modes pass positive, negative, leakage, budget, empty, stale, timeout, and pagination tests; p95 is measured by WP-16.

## `zero_mem.get_trace`

**Purpose:** Resolve one canonical trace identifier to its authorized provenance envelope and, when permitted, bounded expanded content.

**Inputs:** Common request fields plus `trace_id`, `view` (`metadata` or `expanded`), and optional authorized neighbor/parent limit.

**Outputs:** One evidence item with complete canonical provenance, lifecycle/replacement links, verification and content/artifact locator allowed by policy; optional bounded related IDs.

**Scope and authorization:** Authorization applies to the trace, linked sources, artifact, and every expansion independently. The existence of a hidden trace is not disclosed.

**Empty/error/timeout:** Authorized nonexistent and unauthorized/hidden identifiers use the approved non-probing contract. Malformed ID is `INVALID_REQUEST`; unavailable canonical/derived state is explicit. No arbitrary file or raw JSONL read is exposed.

**Compatibility:** Maps the supported subset of exact-master `memory_get_event`/`memory_get_related`; raw storage/debug operations remain forbidden.

**Acceptance:** Direct/API/MCP parity, hidden-ID probing resistance, source-locator authorization, bounded expansion, lifecycle/supersession visibility, and zero mutation are proven.

## `zero_mem.get_task_state`

**Purpose:** Return the current verified project/task state needed to continue work across sessions.

**Inputs:** Common request fields plus required `project_id` and optional `task_id`; optional `include_requirements`, `include_verifications`, and bounded next-action/history limits.

**Outputs:** Current step/status, objective/requirements references, blockers, next action, verification evidence, source traces, state time validity, conflict/stale flags, and omitted count.

**Scope and authorization:** Project/task and each linked requirement, artifact, verification, or source are separately authorized. Assistant claims cannot become active state without user/tool/deterministic verification.

**Empty/error/timeout:** `EMPTY` means no authorized task state exists. Conflicted current state returns all authorized positions and no silent winner. Stale state is labeled and cannot be represented as current verified state.

**Compatibility:** Maps exact-master `project_get_state` plus bounded authorized linked readers behind one canonical capability.

**Acceptance:** New-session task continuation meets the canonical 90% scenario target; superseded failures do not appear active; linked-resource denials cannot leak counts or IDs; conflict and stale fixtures remain visible.

## `zero_mem.get_decisions`

**Purpose:** Retrieve authorized active, superseded, and conflicted decisions for a scope with rationale and provenance.

**Inputs:** Common request fields plus optional `decision_id`, required scope selector (`project_id`, profile/space, or source restriction), `states`, time interval, and bounded pagination.

**Outputs:** Decision ID/key, state, selected value where unambiguous, rationale/source references, verification, valid time, supersedes/replaces links, conflict group, and deterministic ordering.

**Scope and authorization:** Decision and linked evidence are authorized independently. An explicit union cannot grant WRITE or reveal a non-authorized profile.

**Empty/error/timeout:** `EMPTY` is distinct from denial. Conflicted decisions return all authorized positions and resolution status; unresolved conflicts never auto-overwrite or auto-select.

**Compatibility:** Maps exact-master `project_list_decisions` and decision lookup primitives without preserving internal field names as the external contract.

**Acceptance:** Active/superseded/conflicted fixtures, temporal ordering, source conflict, cross-profile leakage, pagination, timeout, and direct/transport parity tests pass.

## Explicitly Deferred Canonical Capabilities

The canonical specification marks these as “Sau MVP”; they are therefore `DEFERRED`, not silently dropped:

- `zero_mem.expand`: bounded neighbor/parent/graph bridge expansion;
- `zero_mem.propose_memory`: creates a candidate only and never curates directly;
- `zero_mem.project_to_obsidian`: requests projection under policy and never bypasses WP-22 review/write boundaries.

Their reserved names and non-conflicting version namespace are maintained in V1.1.0. Implementing any of them requires the owning WP, authorization, and acceptance tests; transports must return `CAPABILITY_UNAVAILABLE` until enabled.

## Transport Conformance and Backward Compatibility

- MCP is the baseline local binding in V1.1.0; local HTTP/Unix socket may be added only as conforming bindings to the same capability contract.
- Existing ten M6 read tools remain supported for the declared compatibility window or receive documented aliases/migration; they do not redefine canonical requirements.
- A generic non-Hermes client and the Hermes adapter execute the same conformance fixtures. Replacing Hermes with a test client requires no core/storage/retrieval rewrite.
- Contract-version negotiation, deprecation, and incompatible-version errors are independent of package patch version and are covered by WP-09/WP-17.
