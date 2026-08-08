# M6.4 — Acceptance Evidence (VERIFIED)

**Milestone:** M6.4 — Policy, linked-resource, and MCP integration hardening.
**Status:** VERIFIED (M6 overall: IN PROGRESS; M6.5/M6.6 not begun; M7 not begun).
**Master Zero-Mem ON/OFF switch:** intentionally deferred to M7 (not implemented).

## Verified starting state (carried from M6.3)
- M0–M6.3: VERIFIED; M6 overall: IN PROGRESS; M6.4: NOT STARTED.
- Starting HEAD: a9f2936. Schema: v8. Final-HEAD canonical (M6.3): 1267 passed, 3 skipped, 0 failed. Working tree clean.

## Scope
M6.4 hardens the COMPLETE exposed M6 read surface (10 tools: memory_query, memory_search, memory_get_event, memory_get_related, project_get_charter, project_list_requirements, project_list_decisions, project_get_state, project_list_verifications, project_list_artifacts) against policy bypass, linked-resource bypass, malformed MCP input, stale authorization, information leakage, and transport-layer inconsistencies. No new memory capabilities; M6 remains integration-only.

## Latent bug fixed (found by M6.4 hardening)
The M3 handlers referenced `req.resource_id`, which does not exist on M6Request. When `event_id`/`query` were absent, this raised AttributeError, which the dispatcher's broad except swallowed as DOWNSTREAM_ERROR (a misleading status, not the intended INVALID_REQUEST). This was masked in M6.2 tests because they always supplied `filters.event_id` (short-circuit). M6.4 removed the reference; missing event_id now correctly returns INVALID_REQUEST. This is a hardening fix to shared M6 code, not a regression in M6.2/M6.3 product behavior (which remains VERIFIED).

## Complete tool-surface audit (req 1)
`audit_tool_surface()` enumerates all 10 registered tools. Each is proven READ-only, has a fixed resource type, is wired to an M5 facade call, performs no low-level bypass (no raw SQLite/JSONL in the module), returns sanitized items, and accepts no caller-supplied authorization object (contracts reject every forbidden authority field). The forbidden-tool set (execute_sql/raw_sql/read_jsonl/write_memory/create_grant/grant_admin/project_write/...) is confirmed unreachable. The registry is an explicit allowlist.

## MCP transport hardening (req 2)
Strict validation rejects: malformed payload (non-object), oversized payload (>64 fields), unknown fields, unknown tool, wrong field type (requesting_profile_id must be str), invalid enum (resource_type/relation), oversized id-list (>64 items), oversized cursor (>4096), oversized query/limit, invalid relation enum, non-boolean isolated_mode/include_global, non-READ operation. All errors map to a deterministic sanitized envelope (INVALID_REQUEST / UNSUPPORTED_TOOL / UNSUPPORTED_OPERATION) with reason_code only — no traceback, no raw exception string, no SQLite/SQL/path/secret leakage.

## Caller privilege-injection matrix (req 3)
The forbidden-authority field set is extended to the complete matrix: admin, is_admin, trusted, grant_admin, grant, grant_valid, grant_rows, verified, authorized, allowed_scope, effective_scope, bypass_policy, cross_profile_allowed, raw_sql, sql, database, jsonl_path, authorization, authorized_read_grant, grant_object, requesting_authority, session_authority, policy_override, assume_identity, identity, auth, token, credential. No payload field grants authority; the fake `grant_object` is rejected.

## Identity hardening (req 4)
requesting_profile_id remains explicit or null (unbound). Never inferred from cwd/repo/HOME/process user/MCP client/session_id/project_id/target_profile/previous request. A concurrent-identity test (3 threads, distinct profiles) confirms no identity leakage across callers; isolated_mode/include_global/project scope do not persist between requests.

## Live grant-state hardening (req 5)
Every independent request resolves current persistent grant state (fresh grant connection per request, no caching of AccessDecision/AuthorizedReadGrant/EffectiveReadScope/grant rows). Sequence proven: request #1 with active grant → allowed; revoke → request #2 → denied.

## Cross-profile matrix (req 6)
All six M4 tools: A→A (owner) allowed, A→B denied, A/P→B/P denied, A/P→B/Q denied (resource-isolated), unbound→protected denied. Same project never bypasses profile boundary. M3 event tools for the project owner legitimately succeed via project-scoped event reads (correct M5 semantics, not a bypass).

## Resource-type matrix (req 7)
A requirement READ grant authorizes only requirements; it does NOT authorize decisions/charter/state/verifications/artifacts/memory_query. A decision grant does not authorize requirements. A tool-fixed resource type cannot be overridden by the caller (resource_type mismatch → INVALID_REQUEST).

## Linked-resource matrix through M6 (req 8)
Tested through the dispatcher AND MCP wrapper: relation (incoming/outgoing/parent/children), source_event, verification links, artifact links. Authorized SOURCE does NOT imply authorized TARGET. source_event on an unauthorized project → POLICY_DENIED; verification link does not confer subject access; artifact link does not authorize linked requirement/decision. Supersession/history links never grant authorization (enforced by M5.5; M6 never bypasses).

## FTS bypass hardening (req 9)
memory_search always uses authorized FTS; no post-filter or second-stage unrestricted snippet lookup in M6. Unauthorized secrets never appear in snippet/score/cursor/error (the synthetic corpus secret absent from search results).

## Exact-event probing resistance (req 10)
memory_get_event for a protected event ID returns POLICY_DENIED with no existence/lifecycle/profile/timestamp/content-length disclosure (the event_id is not echoed back).

## Project-object probing resistance (req 11)
Unauthorized project-memory lookups return POLICY_DENIED; differing internal conditions are not exposed to the caller (uniform safe denial).

## Artifact hardening (req 12)
Artifact exposure is METADATA-ONLY via an explicit field whitelist: artifact_id, project_id, artifact_type, version, safe_reference, source_event_id, created_at, verification_status, linked_requirement_ids, linked_decision_ids, linked_state_keys. stored_path, file content, absolute paths, and hashes are dropped. No file reads, no open-file capability. Content remains deferred.

## Verification hardening (req 13)
verified is evidence status only; it never grants READ permission. Authorized subject + protected verification → verification withheld; authorized verification + protected subject → subject withheld. M5 WRITE-verification internal behavior unaffected (M6 invokes M5 only).

## Global + isolated-mode matrix (req 14)
include_global=True/False and isolated_mode=True/False verified across tools. isolated_mode=True never re-enables global through relations/source_event/artifact/verification/M4 links.

## Pagination security (req 15)
Deterministic ordering; limit bounded (<=500); malformed cursor → INVALID_REQUEST; cursor tied to existing M3/M5 authorization; no secret/grant data in cursor. Grant revocation prevents an old request context from continuing outside current authorization.

## Direct vs MCP parity (req 16)
For every registered tool, the direct Dispatcher result is logically equivalent to the MCP wrapper result for success/empty/deny/invalid/unavailable. The MCP wrapper contains no policy/retrieval logic (transport-only).

## Failure isolation (req 17)
Missing/unreadable DB → CAPABILITY_UNAVAILABLE or DOWNSTREAM_ERROR (sanitized); corrupted/invalid request → INVALID_REQUEST; unavailable policy/retrieval dependency → sanitized. No fallback to raw storage, no fabricated memory, no state mutation, no traceback.

## Read-only integrity (req 18)
Ordinary M6 reads leave M2/M3 tables, M4 tables, M5 grant tables, and canonical memory JSONL unchanged. The store is opened mode=ro + query_only; M4 TRUE READ-ONLY. Approved M5 audit side effects remain separate (M6 never writes them).

## Audit separation (req 19)
M6 never writes zm_policy_audit or canonical policy JSONL. M6 invokes M5 authorization only; any approved DENY/grant/conflict audit is M5-owned and uses its existing canonical sink. No duplicate M6 audit implementation.

## Concurrent-request isolation (req 20)
Bounded concurrency test confirms A's identity never leaks to B, B's grant state never leaks to A, and isolated_mode/include_global/project scope do not persist between requests. No mutable global request context.

## Transport size/resource bounds (req 21)
Existing M3/M6 limits reused (MAX_LIMIT=500, MAX_SEARCH_LENGTH=4000, MAX_PAYLOAD_FIELDS=64, plus new MAX_LIST_ITEMS=64, MAX_CURSOR_LENGTH=4096, MAX_QUERY_LENGTH=4000). Excessive query/list/limit/relation sizes fail deterministically. No conflicting retrieval limits introduced.

## No write/admin surface (req 22)
Confirmed no normal M6 tool can write memory, change lifecycle, mutate project state, create requirement/decision, update verification, read arbitrary artifact content, or create/revoke/supersede grant. No normal M6 request converts into GrantAdminRequest (GrantAdminService unreachable from M6 module; static import analysis confirms).

## Master switch remains deferred (req 23)
Not implemented. No ZERO_MEM_ENABLED / zero_mem.enabled / master_enable / memory_system_enabled.

## No automatic context injection (req 24)
M6.4 returns explicit tool results. No automatic memory injection, evidence selection, prompt/context alteration, or M7 controlled injection.

## Schema (req 25)
Remains v8. No v9. No persistent M6 integration state.

## No LLM / external network (req 26)
AST import analysis over src/integration/m6 confirms 0 imports of openai/llm/requests/httpx/socket/aiohttp/urllib/http. Local MCP/stdio only. 0 LLM calls.

## Path safety (req 27)
No hard-coded /home/brian-nguyen or /home/brian-nguyan in M6.4 code or verifier. Repo root resolved dynamically via git rev-parse --show-toplevel; fixtures OS-temp. The external mutation-verifier typo (/home/brian-nguyan) was NOT copied into any project script/evidence. Verifier confirms all required committed paths resolve under REPO_ROOT; missing path would report AD-HOC VERIFICATION INCOMPLETE. Verifier cleaned up after run.

## Test evidence
- M6.4 focused: 79 passed (tests/unit/test_m6_hardening.py) covering the full hardening matrix (tool-surface audit, MCP transport, privilege-injection, identity/concurrency, grant freshness, cross-profile, resource-type isolation, linked boundaries via M6, artifact whitelist, probing resistance, global/isolated, pagination, direct/MCP parity, failure isolation, read-only/audit, no-write/absence, schema/no-switch/no-LLM/no-network/path-safety).
- M6.1 focused: 69 passed (unchanged). M6.2 focused: 50 passed (unchanged). M6.3 focused: 44 passed (unchanged).
- Combined M6.1–M6.4: 242 passed.
- M3 regressions: green. M4 regressions: green. M5 regressions (access policy, persistent grants, revocation, linked boundaries, audit/rebuild): green.
- Fresh OS-safe ad-hoc verifier (hermes-verify-m64.py): 30/30 PASS (independent; dynamic repo root; OS-temp fixtures; hard gate on missing paths), then removed.

## Canonical result
Full canonical suite under clean isolated HOME: 1346 passed, 3 skipped, 0 failed (was 1267 after M6.3; +79 M6.4). No deselection, no added skip/xfail. test_no_real_hermes_home_writes unchanged and passing.

## Failed / no-op patches
None. The only code change beyond hardening was fixing the latent req.resource_id AttributeError (a correctness hardening, not a weakening).

## Working tree
Clean at final evidence commit.

## Conclusion
M6.4 satisfies every acceptance criterion. M6.1–M6.3 remain VERIFIED. M6.5/M6.6/M7 not begun. Schema remains v8. M6.4: VERIFIED.
