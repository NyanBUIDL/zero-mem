# M6 — Hermes / MCP Read-Only Integration Plan

**Status:** PLANNING — READY FOR APPROVAL (no implementation).
**Authoritative spec:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` (M6 section).
**Schema impact:** NONE (v8 unchanged; M6 is a pure integration/transport layer).
**Normal M6 memory tools:** READ-ONLY.
**GrantAdminService exposure:** NONE.
**Automatic context injection:** NONE.
**Working-tree change from this planning step:** this plan file only.

---

## 1. Reconciled starting state

| Item | Verified value |
|---|---|
| M0–M4 | VERIFIED |
| M5 / M5.1–M5.6 | VERIFIED (final-HEAD `30ef485`, 1104 passed / 3 skipped / 0 failed) |
| Schema | v8 (migration v8; no v9) |
| HEAD | `30ef4858270ab64f041eb7b82846d5c1f28e5354` (final M5) |
| M5 focused | 244 passed, 0 skipped |
| Canonical | 1104 passed, 3 skipped, 0 failed |
| Working tree | clean |
| M6 | not started |
| M7 | not started |
| Context-injection behavior | none introduced (M5 decided scope only; M6 likewise) |

No repository conflict. Proceed to M6 planning.

## 2. Selected integration architecture

**Read-direction sidecar adapter behind a typed tool/transport boundary.** Hermes (or an MCP client) calls narrow typed tools; each tool builds an `AccessRequest` (M5 contract), invokes the verified `AuthorizedReadService` (M5 facade over M3+M4 via `open_readonly`), and returns a sanitized envelope. The adapter owns **no** memory semantics, **no** policy, **no** LLM, **no** SQLite writes.

```
Hermes / MCP client
   │  typed tool call (e.g. memory_search)
   ▼
M6 Integration Adapter (src/integration/m6/)
   │  builds AccessRequest{operation=READ, requesting_profile_id, project_id,
   │                       isolated_mode, include_global, resource_type, ...}
   ▼
AuthorizedReadService (M5, src/access/authorized_read.py)   ← mandatory policy gate
   │  uses M3+M4 via open_readonly(store) → mode=ro + PRAGMA query_only=ON
   ▼
typed sanitized result  ──►  Hermes receives explicit tool result
```

**NOT** Hermes → raw SQLite. **NOT** Hermes → raw JSONL. **NOT** auto-injected memory.

This reuses the already-verified M3/M4/M5 READ path unchanged; M6 adds transport + typed contracts only.

### Relationship to the existing `src/integration/` capture bridge
`src/integration/*` is the **capture** direction (Hermes hook → sidecar, M1). It is a separate pipeline and MUST NOT be entangled with M6. M6 adds a new sub-package `src/integration/m6/` (read direction) that imports only the verified READ facades (`AuthorizedReadService`, `open_readonly`, M5 contracts). No modification to `src/integration/capture_adapter.py` or `bridge_config.py` is required or permitted by this plan unless a later approved decision requires a shared extension point (none identified).

## 3. MCP vs native-adapter decision

**Decision: implement M6 as a thin native Python adapter module (`src/integration/m6/`) AND expose it through an MCP server surface where Hermes supports MCP.** The adapter core is transport-agnostic; the MCP server is a thin wrapper that maps MCP tool calls → adapter calls → sanitized MCP results. If Hermes' only supported local integration is MCP (stdio), the MCP server is the delivery vehicle; if Hermes also supports a native tool/extension registration, the same adapter powers both. **No new external/network dependency is introduced** — the MCP transport, if used, is local stdio or loopback only (see §15).

Rationale: the verified memory layer is pure Python with a stable facade. Building the policy/typed logic once in a transport-agnostic adapter maximizes reuse and makes the MCP surface trivially thin. This avoids inventing a separate SQL/JSONL path and avoids patching Hermes internals.

## 4. Sidecar boundary

External Zero-Mem remains a sidecar/integration layer. M6 does **not** modify Hermes core memory semantics. The only Hermes-side requirement is a supported extension/tool/MCP hook already approved by the project (M1 established the verified Hermes hook/extension point for capture; the read side uses the corresponding read/tool extension point). **No Hermes core patch is required** for M6 — the integration is satisfied by an external tool/MCP server Hermes launches or connects to. If a specific Hermes API is found during implementation to be missing a read-extension point, that becomes a planning decision escalated for approval (none required by current evidence).

## 5. Tool surface (typed, narrow)

M6 exposes typed read tools only. No generic SQL/JSONL tool. Proposed minimal surface (names mirror the M5 facade for traceability; adjust only if the authoritative spec dictates others):

**M3 memory**
- `memory_query` — structured event retrieval (filters, pagination cursor).
- `memory_search` — M5-authorized M3 FTS (no semantic/vector, no LLM rewrite).
- `memory_get_event` — single event by id, scope-checked.
- `memory_get_related` — M5.5-hardened relation expansion (incoming/outgoing/parent/children via distinct tools or a `relation` arg).

**M4 project-memory**
- `project_get_charter`
- `project_list_requirements` (supports `include_source_event` via hardened path)
- `project_list_decisions`
- `project_get_state` (current project state)
- `project_list_verifications`
- `project_list_artifacts` (metadata only; no file contents)

Each tool declares its `resource_type` (e.g. requirement/decision/verification/artifact/event) so M5 grant resource restrictions survive translation. No tool performs create/update/delete or grant administration.

## 6. Request contract

Typed request fields per tool (all validated; unknown fields rejected):

- `requesting_profile_id: str` (required; may be `null`/unbound per M5 — explicit only, never inferred).
- `operation` — fixed to `READ` (hard-forced; any other value → `UNSUPPORTED_OPERATION`).
- `project_id: Optional[str]`.
- `profile_targets: Optional[list[str]]` (explicit READ targets; no inference).
- `knowledge_space_ids: Optional[list[str]]`.
- `isolated_mode: bool` (default False; when True, disables implicit global/project expansion).
- `include_global: bool` (default False).
- `resource_type: str` (declared; must match the tool's allowed type).
- `filters` — structured M3 filter bag (event_type, subject_type, lifecycle_status, date bounds, etc.).
- `query` / `search_text` — only for `memory_query`/`memory_search`.
- `cursor` — opaque pagination token carrying query+scope+limit bindings (encoding §10).
- `limit: Optional[int]` — bounded (reuse M3 limit defaults).

No caller-controlled authority fields (`is_admin`, `trusted`, `grant_admin`, `verified`, `allow_grant_creation`, `admin`) are accepted — they are rejected at the contract layer and never reach policy.

## 7. Response contract (sanitized envelope)

Stable envelope:

```
{ "status": "OK" | "EMPTY" | "DENIED" | "INVALID_REQUEST"
             | "UNSUPPORTED_OPERATION" | "RETRIEVAL_ERROR" | "UNAVAILABLE",
  "results": [ <typed M3/M4 view models> ],
  "next_cursor": "<opaque or null>",
  "reason_code": "<M5 ReasonCode or adapter code, safe>",
  "diagnostics": { "tool": "...", "bounded": true } }
```

- `DENIED` returns a **fixed safe outcome** (e.g. `DENY_CROSS_PROFILE_READ`) — never "record X exists but you lack access".
- `RETRIEVAL_ERROR` returns a sanitized message; **never** raw SQLite errors, stack traces, unrestricted paths, secrets, or internal policy implementation details.
- `UNAVAILABLE` used when sidecar/SQLite/MCP/schema is unavailable (§14).
- Results are the M3/M4 view models already returned by the facade (no raw rows, no JSONL).
- No `next_cursor` leakage of grant details or secrets.

## 8. Identity transport

`requesting_profile_id`, `project_id`, `knowledge_space_ids`, `isolated_mode` are **explicit request fields supplied by the caller/Hermes tool invocation**. M6 does **NOT** infer identity from cwd, repo path, session text, project name, MCP client name, process user, or previous request. If Hermes already carries an explicit profile/session field in its verified tool/extension contract, M6 reuses that **field value verbatim** — it does not derive a profile from it. Unbound (`null`) is a valid M5 state and is passed through. This matches M5's "consume explicit `requesting_profile_id` (or null=unbound); never infer identity" rule.

## 9. Authorization flow (mandatory)

Every protected M6 request flows:

`tool call → adapter validates request → build AccessRequest(READ, requesting_profile_id, ...) → resolve current M5 policy (grants read live from zm_access_grants via resolver) → AuthorizedReadService method → defensive result validation (M5.5 linked checks) → sanitized envelope.`

The adapter **never** calls low-level M3/M4/SQLite APIs directly for protected reads; it always goes through `AuthorizedReadService`. Grant resolution is internal; an external caller cannot submit an `AuthorizedReadGrant` object as proof of authorization. `isolated_mode`, persistent grants, resource types, and linked-resource checks are enforced by the facade, not re-implemented in M6.

## 10. M3 pagination / cursor transport

Reuse M3 deterministic keyset pagination exactly. The `cursor` is an **opaque, server-side-encoded** token binding: querying profile, effective project/scope, resource types, `isolated_mode`, `include_global`, filters, limit. If grant state/scope changes so `EffectiveReadScope` changes, an old cursor must not silently continue — M6 re-derives scope from the *current* request (cursors carry bindings, not grant snapshots) and the adapter re-validates against current policy on each page. No grant secrets in cursor. No second conflicting pagination policy.

## 11. FTS / relations / M4 source-event / artifacts / verification

- **FTS:** `memory_search` uses M5-authorized M3 FTS only. No unrestricted pre-search, no semantic/vector search, no LLM query rewriting.
- **Relations:** `memory_get_related*` uses M5.5 hardened `get_related/get_outgoing/get_incoming/get_parent/get_children` (source-scope precheck + target-scope recheck, fail-closed). No raw relation-table queries that skip endpoint authorization.
- **M4 source-event:** `include_source_event` routes through `harden_m4_source_event` (M5.5); M6 does not independently resolve `source_event_id` via low-level M3.
- **Artifacts:** only safe metadata (id, type, name) returned where M4 already allows; M6 does **NOT** open arbitrary files, read arbitrary paths, return unrestricted `stored_path`, or auto-send artifact contents. Artifact-content access is explicitly **deferred** to a later milestone.
- **Verification:** authorized verification metadata only; `verified` status is not a global-access grant and is not treated as authorization.

## 12. Global / isolated-mode behavior

M6 preserves exact M5 behavior: permitted global READ only where policy allows; `include_global=False` excludes it; `isolated_mode=True` disables implicit global/project/profile/space/relation expansion. M6 applies **no separate** global policy.

## 13. Cross-profile behavior

Explicit cross-profile READ occurs **only** via validated persistent M5 READ grants resolved internally. M6 does not expose M5.3 raw pre-authorized objects to external callers. Revocation/supersession is reflected on the **next** request because each call re-resolves current policy state (no indefinite authorization cache).

## 14. Failure isolation / sidecar-unavailable

M6 integration failure must not crash or corrupt the substrate. Define sanitized `UNAVAILABLE` tool results for: sidecar unavailable, SQLite unavailable, MCP unavailable, schema mismatch (v8 expected), policy DB unavailable. M6 must **not** silently fabricate memory. If the authoritative spec allows Hermes to function without Zero-Mem, M6 degradation is graceful (tool returns `UNAVAILABLE`, Hermes continues). JSONL/SQLite/Hermes process are preserved; no orphan temp files; no DB mutation on failure.

## 15. Transport safety / bounds / concurrency

- **Validation:** reject oversized payloads, invalid JSON, unknown fields, malformed cursor, unexpected tool name, unsupported operation, invalid enum, null/unknown protected identity. Fail safely; transport exceptions never expose internal paths/stack traces.
- **Bounds:** reuse M3 result `limit` defaults; bound search length, relation result count, pagination; single tool-execution duration timeout. No second conflicting pagination policy.
- **Concurrency:** multiple read-only requests share no mutable state; reads never mutate M3/M4. Grant revocation observed on next request. No indefinite authorization cache.
- **Transport type:** if MCP is used, local stdio or loopback HTTP only. Distinguish **transport I/O** from **external network dependencies**: routine M6 memory operations must not depend on external network services. No outbound network calls for policy/retrieval/response/error.

## 16. Audit interaction

M6 must not write directly to `zm_policy_audit`. Persistent M5 audit behavior is preserved: DENY + grant-using authorization decisions + policy conflicts emit approved `policy_decision` canonical events through the **separate M5 audit sink** (`record_decision`), exactly as M5 already does. Ordinary local/global ALLOW READs remain ephemeral per M5. The memory DB being queried stays TRUE READ-ONLY; the audit sink is a separate append path. M6 calls the existing `record_decision`/`_should_audit` helpers — it does not invent new audit logic.

## 17. Read-only DB guarantee

M6 ultimately uses M3/M4 TRUE READ-ONLY paths: `open_readonly(store)` → `file:...?mode=ro` + `PRAGMA query_only=ON`. The MCP/adapter process must **not** open SQLite read-write merely because it owns the connection. The `SQLiteStore` real-home guard (`_guard_real_hermes_home`) remains in force; M6 never writes to real `~/.hermes`.

## 18. Startup / shutdown / configuration

- **Startup:** validate config (store path, schema v8, dependency health); refuse to serve if schema mismatch or real-home guard trips. No DB mutation; no orphan temp files.
- **Shutdown:** graceful; release connections; no writes.
- **Configuration:** minimal, project-local (e.g. `integration.m6.yaml` under project config, or env passed by Hermes launcher). **No embedded secrets.** Do not silently edit global Hermes config during tests. Discovery is explicit (Hermes launches/connects with a configured path/transport).
- **Real `~/.hermes` rule:** tests use isolated `HERMES_HOME`/temp store; existing `test_no_real_hermes_home_writes` hard gate is preserved; no weakening.

## 19. Schema impact

**NONE.** M6 is an integration/transport layer over existing v8 derived tables and the verified facades. No migration v9. If a v9 proposal becomes objectively required (e.g. new derived persistent MCP-state), it is escalated for explicit approval before any implementation — not decided in planning.

## 20. Zero-token routine behavior

M6 integration uses **0 LLM calls** for policy evaluation, retrieval, response formatting, and error handling. Hermes may later use the returned tool result in its own LLM call, but M6 itself never invokes an LLM to decide what memory to retrieve. **0 external network dependencies** for routine memory operations.

## 21. Proposed M6 increments (smallest independently verifiable)

| Increment | Objective | Files (planned) | Schema | Authorization | Tests | Acceptance | Rollback | Deps | Exclusions |
|---|---|---|---|---|---|---|---|---|---|
| **M6.1** | Integration contracts + transport/tool surface (validation, envelope, no policy yet behind a stub) | `src/integration/m6/contracts.py`, `transport.py`, `envelope.py` | none | request validated only | contract/validation/transport unit tests | typed requests rejected when malformed; envelope safe on error | delete module; no state | M3/M4/M5 facades exist | no real reads yet |
| **M6.2** | M3 authorized read tools (`memory_query`, `memory_search`, `memory_get_event`, `memory_get_related*`) | `src/integration/m6/m3_tools.py` | none | routes through `AuthorizedReadService` | positive+negative M3 policy parity vs M5 | same logical data as M5 low-level call; relation cannot bypass | revert file | M6.1 | no writes |
| **M6.3** | M4 project-memory read tools (charter/requirements/decisions/state/verifications/artifacts) | `src/integration/m6/m4_tools.py` | none | routes through facade; hardened source_event; metadata-only artifacts | M4 parity; source_event/artifact/verification boundaries | same logical data as M5-authorized M4 call | revert file | M6.1,M6.2 | no file contents, no writes |
| **M6.4** | Policy/linked-resource/MCP hardening (cross-profile grant, isolation, resource-type, denied-leak-free, no admin exposure, no raw SQL/JSONL) | `src/integration/m6/security.py`, MCP wrapper | none | full M5.5 matrix via tools | 16+ security tests from §22 | no bypass; no leak; GrantAdminService not reachable | revert | M6.2,M6.3 | no GrantAdminService exposure |
| **M6.5** | Hermes adapter/registration + failure isolation (startup/shutdown, sidecar-unavailable, concurrency, audit sink wiring) | `src/integration/m6/server.py` (MCP), `adapter.py` | none | reuses M5 audit sink | non-interference, UNAVAILABLE, audit parity | clean isolated canonical 0 fail; no substrate corruption | revert | M6.4 | no core Hermes patch |
| **M6.6** | Performance/security/final integration acceptance | benchmarks + tests | none | full | full M6 focused + M3/M4/M5 parity + canonical | all hard gates; 0 fail final-HEAD | n/a | all prior | no M7 |

This split is approximately the recommended structure; adjust only on authoritative evidence.

## 22. Acceptance matrix (scenario → M5 expectation → M3/M4 op → expected tool response → side effects → automated test → increment)

| Scenario | M5 expectation | M3/M4 op | Expected tool response | Side effects | Test | Increment |
|---|---|---|---|---|---|---|
| Same-profile READ | allow | query_events | OK/results | none | `test_same_profile_read` | M6.2 |
| Global READ default allowed | allow (policy) | query_events include_global | OK | none | `test_global_read` | M6.2 |
| Global disabled (include_global=False) | deny implicit global | query_events | EMPTY/DENIED | none | `test_global_disabled` | M6.2 |
| Cross-profile no grant | DENY_CROSS_PROFILE_READ | query_events | DENIED (safe) | none | `test_cross_profile_denied` | M6.2 |
| Persistent READ grant exact resource | allow exact | query_events | OK (scoped) | none | `test_grant_allows_exact` | M6.4 |
| Resource-type mismatch | deny (grant restricts type) | query_events | DENIED | none | `test_resource_type_restriction` | M6.4 |
| Revoked grant → next request | deny | query_events | DENIED | none | `test_revoked_immediately_denies` | M6.4 |
| Isolated mode via MCP | deny implicit scope | query_events | EMPTY/DENIED | none | `test_isolated_mode` | M6.4 |
| Relation cannot bypass | target rechecked | memory_get_related | only in-scope targets | none | `test_relation_no_bypass` | M6.4 |
| Source_event cannot bypass | hardened | project_list_requirements(include_source_event) | out-of-scope source withheld | none | `test_source_event_no_bypass` | M6.3 |
| Artifact cannot bypass | metadata only | project_list_artifacts | metadata, no path/contents | none | `test_artifact_no_bypass` | M6.3 |
| Verification cannot bypass | not authz | project_list_verifications | metadata, no grant | none | `test_verification_no_bypass` | M6.3 |
| Caller submits fake grant object | rejected | (n/a) | INVALID_REQUEST | none | `test_no_fake_grant` | M6.4 |
| Caller uses `admin=true` | rejected | (n/a) | INVALID_REQUEST | none | `test_no_admin_flag` | M6.4 |
| GrantAdminService not exposed | not reachable | (n/a) | UNSUPPORTED_OPERATION | none | `test_grant_admin_not_exposed` | M6.4 |
| Raw SQL tool unavailable | not exposed | (n/a) | UNSUPPORTED_OPERATION | none | `test_no_raw_sql` | M6.1/M6.4 |
| Raw JSONL tool unavailable | not exposed | (n/a) | UNSUPPORTED_OPERATION | none | `test_no_raw_jsonl` | M6.1/M6.4 |
| Secret absent | sanitized | any | no secret in envelope/results/error | none | `test_secret_absent` | M6.4 |
| Unrestricted path absent | sanitized | any | no path in envelope/error | none | `test_no_path_leak` | M6.4 |
| FTS authorized only | M5-authorized | memory_search | OK (scoped) | none | `test_fts_authorized` | M6.2 |
| Denied result no existence leak | fixed outcome | any | DENIED (safe) | none | `test_deny_no_leak` | M6.4 |
| Sidecar unavailable | graceful | (n/a) | UNAVAILABLE | none | `test_sidecar_unavailable` | M6.5 |
| TRUE READ-ONLY DB | ro+query_only | open_readonly | OK | no writes | `test_read_only_db` | M6.5 |
| Canonical audit semantics | DENY/grant-using → policy_decision | record_decision | (internal) | audit event via sink | `test_audit_parity` | M6.5 |

## 23. Compatibility / parity tests

Authorized M6 requests return the **same logical data** as the corresponding verified M5-authorized low-level call. Plan parity checks for M3 (structured query, FTS, relation) and M4 (requirements, decisions, project state, verifications, artifacts) by invoking both the facade directly and the M6 tool with identical `AccessRequest` parameters and asserting equivalent sanitized results. M6 adds transport/integration only — memory semantics unchanged.

## 24. Performance baseline

Measure M6 adapter overhead relative to the direct M5-authorized call:
- adapter overhead (request parse + envelope);
- same-profile read;
- global read;
- persistent cross-profile grant read;
- FTS;
- M4 object retrieval;
- relation retrieval.
No arbitrary production SLA. Record corpus size, grant count, profiles, projects, spaces, Python/SQLite versions, iteration count, median, p95 where meaningful. No caching added solely to improve benchmark numbers.

## 25. Required planning decisions — resolved

1. **MCP vs native vs both** → both; transport-agnostic adapter + thin MCP wrapper.
2. **Exact tool surface** → §5 (typed read tools only).
3. **Identity fields** → explicit `requesting_profile_id`/`project_id`/`knowledge_space_ids`/`isolated_mode`; never inferred.
4. **How `requesting_profile_id` reaches M6** → explicit tool-request field; passed verbatim to M5.
5. **Global/default** → M5 governs; M6 adds no policy.
6. **Isolated-mode transport** → `isolated_mode: bool` request field; identical to M5.
7. **Cross-profile persistent grant** → internal M5 resolver; not exposed.
8. **Resource-type mapping** → each tool declares `resource_type`; M5 grant restrictions enforced by facade.
9. **Error/result envelope** → §7.
10. **Pagination/cursor** → §10 (opaque, binding-aware, re-validated).
11. **Audit behavior** → §16 (reuse M5 sink; M6 writes nothing directly).
12. **Transport type** → local stdio/loopback MCP; no external network.
13. **Startup/shutdown** → §18.
14. **Sidecar-unavailable** → §14 (`UNAVAILABLE`, no fabrication).
15. **Schema impact** → NONE (v8).
16. **Hermes core change required?** → NO (external tool/MCP server).
17. **Can normal M6 tool write memory?** → NO (READ-ONLY).
18. **Grant-admin exposure?** → NO (not exposed; `admin` flag rejected).

No identity/security ambiguity deferred into implementation.

## 26. Unresolved decisions

**None that block planning.** All 18 planning decisions are resolved from authoritative evidence (M5 contracts, M5.5 hardening, existing `src/integration` capture bridge, `open_readonly`, `AuthorizedReadService`). The only forward note: if, during M6.5 implementation, Hermes is found to lack a verified read/tool extension point (distinct from the M1 capture hook), that specific gap becomes an explicit approval request before any Hermes-core change — but current evidence indicates the read surface is satisfied by an external MCP server Hermes launches, requiring no core patch.

## 27. State/commit protocol (for future implementation)

plan → approval → plan commit → smallest increment → focused tests → compatibility tests → canonical → acceptance evidence → state binding → clean commit → next increment. Do not combine unverified M6 increments. Do not modify `project-state.yaml`/`implementation-plan.json` until implementation begins.

## 28. Final M6 acceptance planning (must hold before M6 VERIFIED)

- all M6.1–M6.6 VERIFIED;
- M0–M5 remain VERIFIED;
- complete M6 focused suite green;
- M3/M4/M5 parity green;
- unauthorized-access tests green;
- linked-resource bypass tests green;
- isolated mode green;
- persistent grant behavior green;
- grant revocation reflected immediately;
- no GrantAdminService exposure;
- raw SQL unavailable; raw JSONL unavailable;
- TRUE READ-ONLY memory DB;
- canonical audit semantics preserved;
- secret/path safety;
- deterministic responses;
- no M7 behavior;
- no automatic context injection;
- zero LLM inside M6;
- no external network dependency for routine memory ops;
- clean isolated canonical suite 0 failed;
- final-HEAD canonical 0 failed;
- working tree clean.

---

**Verdict:** M6 PLAN: READY FOR APPROVAL
Schema impact: NONE
Normal M6 memory tools: READ-ONLY
GrantAdminService exposure: NONE
Automatic context injection: NONE
Working tree change: M6 plan file only
