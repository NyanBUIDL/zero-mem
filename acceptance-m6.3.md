# M6.3 — Acceptance Evidence (VERIFIED)

**Milestone:** M6.3 — M4 project-memory read tools.
**Status:** VERIFIED (M6 overall: IN PROGRESS; M6.4 not begun; M7 not begun).
**Master Zero-Mem ON/OFF switch:** intentionally deferred to M7 (not implemented).

## Verified starting state (carried from M6.2)
- M0–M5: VERIFIED; M5.1–M5.6: VERIFIED; M6.1: VERIFIED; M6.2: VERIFIED; M6 overall: IN PROGRESS; M6.3: NOT STARTED.
- Starting HEAD: b1fe13411ff6ec2ae067e4e56cd515557e9ad427.
- Schema: v8. Working tree clean at start (an uncommitted M6.3 draft was reset to committed M6.2 before work began).

## Scope implemented
Wired the six approved M4 project_* read tools through the verified M5 AuthorizedReadService, in strict order:
validate (M6.1 contracts) to translate to M5 AccessRequest (explicit identity, no injected resource_type) to resolve current READ grants (read-only) to invoke the approved M4 facade method to translate AuthorizedResult to sanitized M6 envelope to serialize.
- project_get_charter to M4 charter API (charter_id optional; include_source_event supported via M5.5 hardened path).
- project_list_requirements to M4 requirements API (deterministic order, lifecycle/state, limit/cursor).
- project_list_decisions to M4 decision-log API (explicit decision identity; supersession/conflict preserved, no winner inferred).
- project_get_state to M4 current-state API (project plus state_key).
- project_list_verifications to M4 verification API (verification is evidence, NOT authorization).
- project_list_artifacts to M4 artifact API, metadata-only (stored_path / file content stripped).

## Architecture / invariants
Hermes/MCP to M6 Dispatcher to typed project_* request to M5 AuthorizedReadService to live policy/grant resolution to M4 TRUE READ-ONLY APIs to M5.5 linked hardening where applicable to sanitized M6 response. M6 is transport/integration only; M4 owns project-memory semantics; M5 owns authorization; M6 validates, translates, authorizes, invokes, sanitizes, serializes. Forbidden paths avoided (raw M4 SQLite tables, raw SQLite, raw JSONL, direct M4 internals bypassing M5, AuthorizedWriteService, GrantAdminService). Static AST import checks confirm none are imported.

## Resource-type mapping (tool-fixed, caller cannot override)
Each project_* tool has a fixed M5 resource type (charter / requirement / decision / project_state / verification / artifact). Critical finding: M6 does NOT inject the tool-fixed resource_type into the M5 AccessRequest for M4 calls — doing so was found to pollute the M5 effective-scope computation (caused POLICY_DENIED for authorized reads). The fixed mapping is enforced by the M5 facade internally via _m4_resource_allowed; a caller-supplied resource_type is dropped (never broadens access). Verified: a requirements grant cannot expose decisions/artifacts/verifications; B/P grant does not become B/Q.

## Identity (unchanged)
requesting_profile_id explicit or null (unbound). Never inferred from cwd/repo/HOME/process user/project_id/session/MCP/client/previous request. project_id selects/narrows target project; not requester identity. session_id narrows retrieval only; not authorization. Forbidden authority fields rejected.

## Grant / revocation
Every independent request resolves current M5 policy/grant state (no cross-request caching). Exact persistent READ grant (profile or project plus resource type) authorizes only its exact scope/resource. Revocation affects the next independent request.

## Linked-resource boundaries (M5.5)
- source_event: authorized M4 plus authorized M3 source event allowed; unauthorized source event withheld; existence not leaked.
- supersession/history: links never grant authorization; each returned historical object remains independently inside EffectiveReadScope.
- verification link: subject to verification and verification to subject remain independently authorized; verification_status equals verified does NOT make a verification globally readable.
- artifact link: requirement/decision/verification to artifact does not authorize the artifact; artifact to target does not authorize the target.

## Cross-profile / global / isolation
Without exact READ grant: A to B project memory DENIED. Same project does NOT bypass profile boundary. Isolated mode / include_global preserved exactly as M5.

## Unbound caller
requesting_profile_id equals null preserves exact M5 behavior (no default profile invented).

## Response envelopes
Reuses M6.1 model: SUCCESS / EMPTY / POLICY_DENIED / INVALID_REQUEST / CAPABILITY_UNAVAILABLE / DOWNSTREAM_ERROR. DENY never disguised as EMPTY; denial carries fixed reason_code with no protected-existence detail. No sqlite rows/SQL/stack-trace/unrestricted paths/protected IDs/raw grant data.

## Artifact content
Only the approved SAFE artifact metadata/reference model is exposed (safe_reference, artifact_id, type, version, linked ids). stored_path, file content, and absolute filesystem paths are stripped. Artifact content access remains deferred.

## TRUE READ-ONLY
All project_* paths use existing M4 TRUE READ-ONLY access over the M6-opened mode=ro plus query_only store. No migration, projector writer, M4 writer, or canonical append.

## Audit
M6 calls M5; M5 owns persistent audit. M6 writes nothing to zm_policy_audit or canonical policy JSONL.

## Existing M3 tools (regression)
memory_query / memory_search / memory_get_event / memory_get_related remain green (M6.2 verified, unchanged except the smallest required shared fix: the M6.2 test asserting project_* CAPABILITY_UNAVAILABLE was updated to assert they are now wired and still enforce authorization — not a product regression).

## Write behavior
M6.3 remains READ-only. No project_set_state / requirement create/update / decision create / verification create/update / artifact_write. No GrantAdminService exposure.

## Master Zero-Mem switch
Not implemented. No ZERO_MEM_ENABLED / zero_mem.enabled / master_enable / memory_system_enabled.

## Secret safety
M4 corpus carries a synthetic secret in the artifact stored_path (artifacts/SK-M4-6-SECRET-XYZ.md). Verified: the artifact response strips stored_path and exposes only safe_reference; the secret never appears in results, snapshots, denial envelopes, errors, or cursors.

## No LLM / no external network
AST import analysis over src/integration/m6 confirms 0 imports of openai/llm/requests/httpx/socket/aiohttp/urllib/http. Local MCP/stdio only. 0 LLM calls.

## Path safety
No hard-coded /home/brian-nguyen or /home/brian-nguyan in M6.3 code or verifier. Repo root resolved dynamically via git rev-parse --show-toplevel; fixtures OS-temp. Verifier confirms all required committed paths resolve under REPO_ROOT; missing path would report AD-HOC VERIFICATION INCOMPLETE. Verifier cleaned up after run.

## Test evidence
- M6.3 focused: 44 passed (tests/unit/test_m6_project_tools.py, reuses the verified M4 rebuild pipeline plus m4base corpus builder).
- M6.1 focused: 69 passed (unchanged).
- M6.2 focused: 50 passed (one test updated: project_* tools now wired, still enforce auth).
- Combined M6.1 to M6.3: 163 passed.
- M3 regressions: green. M4 regressions: green. M5 regressions (base policy, authorized read, persistent grants, verification, linked boundaries, audit/rebuild): green.
- M4 parity: M6 project_* logical response equals direct M5-authorized M4 result for charter/requirements/decisions/state/verifications/artifacts.
- Fresh OS-safe ad-hoc verifier: 30/30 PASS (independent of committed tests; dynamic repo root; OS-temp fixtures; hard gate on missing paths).

## Canonical result
Full canonical suite under clean isolated HOME: 1267 passed, 3 skipped, 0 failed (was 1223 after M6.2; +44 M6.3). No deselection, no added skip/xfail. test_no_real_hermes_home_writes unchanged and passing.

## Failed / no-op patches
None. (One transient: an uncommitted M6.3 draft referencing facade methods was found mid-edit at session start and reset to committed M6.2 before building; the final implementation is clean and committed.)

## Working tree
Clean at final evidence commit.

## Conclusion
M6.3 satisfies every acceptance criterion. M6.1 and M6.2 remain VERIFIED. M6.4/M7 not begun. Schema remains v8. M6.3: VERIFIED.
