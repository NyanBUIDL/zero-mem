# M6.2 — Acceptance Evidence (VERIFIED)

**Milestone:** M6.2 — M3 authorized memory read tools.
**Status:** VERIFIED (M6 overall: IN PROGRESS; M6.3 not begun; M7 not begun).
**Master Zero-Mem ON/OFF switch:** intentionally deferred to M7 (not implemented).

## Verified starting state (carried from M6.1)
- M0–M5: VERIFIED; M5.1–M5.6: VERIFIED; M6.1: VERIFIED; M6 overall: IN PROGRESS; M6.2: NOT STARTED.
- M6 plan commit: `4cd0643`; M6.1 implementation commit: `40eb1af506d88e3520229094eac8a6ee9ab13ac6`.
- Schema: v8. Working tree clean.

## Scope implemented
Wired the four approved M3-oriented M6 read tools through the verified M5 `AuthorizedReadService`, in strict order:
validate (M6.1 contracts) → translate to M5 `AccessRequest` → resolve current READ grants (read-only) → invoke facade → translate `AuthorizedResult` to sanitized M6 envelope → serialize.
- `memory_query` — structured query over M3 query path (profile/project/session/lifecycle/time filters, limit, cursor, include_global, isolated_mode).
- `memory_search` — M3 FTS path (deterministic order, snippet, cursor, scope). No vector/semantic/LLM.
- `memory_get_event` — exact event lookup; event_id is NOT an auth credential; missing → EMPTY (no existence leak).
- `memory_get_related` — relation traversal through M5.5 hardened path (direction: incoming/outgoing/parent/children via `relation` arg); authorized source does NOT imply authorized target.

## Architecture / invariants
- Only allowed direction: Hermes/MCP → M6 Dispatcher → M6 request → M5 AuthorizedReadService → live M5 policy/grant resolution → M3 authorized read path → TRUE READ-ONLY SQLite → sanitized M6 response.
- M6 is transport/integration only; M5 decides requesting profile, target profile, project scope, knowledge-space, global access, isolated mode, persistent grants, resource types, linked-resource authorization. M3 performs retrieval. M6 does NOT duplicate or reinterpret M5 policy.
- Forbidden paths avoided: raw low-level M3 bypass, raw SQLite, raw JSONL, unrestricted FTS, GrantAdminService, AuthorizedWriteService. Static AST import checks confirm none are imported.

## Identity (unchanged from M6.1)
`requesting_profile_id` explicit or null (unbound). Never inferred from cwd, repo path, process user, HOME, Hermes session, MCP connection, client/project name, target profile, or previous request. `session_id` narrows retrieval only; not authorization. Forbidden authority fields (`admin`, `is_admin`, `trusted`, `grant_admin`, `grant`, `verified`, `cross_profile_allowed`, `bypass_policy`, `raw_sql`, `grant_object`, `authorized_read_grant`) rejected by strict validation.

## Grant / revocation behavior
Every independent request resolves the current M5 authorization state (no cross-request caching of grant/decision/scope). READ grant active → request allowed; grant revoked → next request denied. Verified: `A→B` grant allows `B`'s exact scope; `B/P` grant does NOT become `B/Q` or other targets.

## Resource-type mapping
Per-tool fixed resource type preserved from M6.1; caller cannot downgrade/override. Caller-supplied `resource_type` ignored where the tool contract fixes it.

## Global / isolation behavior
Preserves M5 exactly: `include_global=True` only where M5 permits; `include_global=False` excludes global; `isolated_mode=True` disables implicit global. No second global policy in M6.

## Pagination / cursor
M3 cursor contract transported unchanged; cursor bound to normalized query + authorization scope + ordering + limit. Malformed cursor → sanitized `INVALID_REQUEST` (no raw parser errors).

## Response / error mapping
Single sanitized envelope: SUCCESS / EMPTY (distinct from DENY) / POLICY_DENIED / INVALID_REQUEST / UNSUPPORTED_OPERATION / UNSUPPORTED_TOOL / CAPABILITY_UNAVAILABLE / DOWNSTREAM_ERROR. DENY never disguised as empty; denial carries fixed reason_code with no protected-existence detail. No sqlite row objects, SQL text, raw exceptions, filesystem paths, raw grant rows, internal policy internals, or stack traces.

## Database / JSONL
All retrieval uses existing TRUE READ-ONLY path: SQLite URI `?mode=ro` + `PRAGMA query_only=ON`. M6 opens the store read-only and a separate read-only grant connection. M6.2 does NOT open/parse canonical JSONL directly (relies on verified M3/M5 event-read API). No M6 writable-DB path added.

## Audit
M6 calls M5; M5 owns persistent audit. M6 writes nothing to `zm_policy_audit` or canonical policy JSONL.

## M4 project tools
`project_get_charter`, `project_list_requirements`, `project_list_decisions`, `project_get_state`, `project_list_verifications`, `project_list_artifacts` remain registered from M6.1 but execution returns deterministic `CAPABILITY_UNAVAILABLE` (M6.3). Not wired early.

## Master Zero-Mem switch
Not implemented. No `ZERO_MEM_ENABLED` / `zero_mem.enabled` / `master_enable` / `memory_system_enabled` in M6.2 source.

## Secret safety
Synthetic secret `SK-M6R-DONTLEAK-7a8b9c0d` in B's event. Verified: unauthorized A (no grant) reads/search/relations never include the secret in results, snippets, denial envelopes, errors, or cursors. With an explicit valid grant A→B, B's authorized content (incl. secret) is correctly returned to authorized A (expected). Unauthorized secret exclusion is enforced by the M5 authorization boundary, not by M6 filtering.

## No LLM / no external network
Static AST import analysis over `src/integration/m6` confirms 0 imports of openai/llm/requests/httpx/socket/aiohttp/urllib/http. Local MCP/stdio only. 0 LLM calls for any purpose.

## Path safety
No hard-coded `/home/brian-nguyen` or `/home/brian-nguyan` in M6.2 code or verifier. Repo root resolved dynamically via `git rev-parse --show-toplevel`; all fixture paths use OS-temp (`tempfile.mkdtemp`). Verifier confirms all required committed paths resolve under REPO_ROOT; a missing path would report AD-HOC VERIFICATION INCOMPLETE (hard gate). Verifier cleaned up after run.

## Test evidence
- M6.2 focused: **50 passed** (`tests/unit/test_m6_memory_tools.py`).
- M6.1 focused: **69 passed** (contracts hardened; one naive substring static check converted to AST-based import analysis — strictly more correct, no weakening).
- Combined M6.1–M6.2: **119 passed**.
- M5 regressions (authorized_read, cross_profile, access_policy, grants, linked, policy_rebuild): green.
- M3 regressions (query, fts, pagination, relations): green.
- M4 regressions (read, schema, verification_artifact): green.
- M3 parity: M6 logical response equals direct M5-authorized M3 result for query, FTS, get_event (relation parity via same-scope traversal).
- Fresh OS-safe ad-hoc verifier: **27/27 PASS** (independent of committed tests; dynamic repo root; OS-temp fixtures; hard gate on missing paths).

## Canonical result
Full canonical suite under clean isolated HOME: **1223 passed, 3 skipped, 0 failed** (was 1173 after M6.1; +50 M6.2). No deselection, no added skip/xfail. `test_no_real_hermes_home_writes` unchanged and passing.

## Failed / no-op patches
None. (Transient: one M6.1 static-check test and several M6.2 static-check tests initially used naive substring matching that false-flagged deny-list docstrings; converted to AST-based import analysis — strictly more correct, no product weakening.)

## Working tree
Clean at final evidence commit.

## Conclusion
M6.2 satisfies every acceptance criterion. M6.1 remains VERIFIED. M6.3/M7 not begun. Schema remains v8. M6.2: VERIFIED.
