# M6.5 — Acceptance Evidence (VERIFIED)

**Milestone:** M6.5 — Hermes adapter / registration + failure isolation.
**Status:** VERIFIED (M6 overall: IN PROGRESS; M6.6 not begun; M7 not begun).
**Starting commit:** `9020d39` (M6.4 evidence/state-binding).
**Implementation commit:** `fc1ea9b`.
**Tested commit:** `fc1ea9b`.
**Evidence/state-binding commit:** (this file + state update, committed after the final-HEAD gate).
**Current HEAD:** (evidence commit hash, recorded below in final-HEAD gate).
**Schema version:** 8 (unchanged; no v9, no persistent registration table).

---

## Objective

Connect the VERIFIED M6 read-only integration surface to Hermes through the
approved external adapter / plugin-context registration mechanism. Do NOT add
new memory semantics, automatic context injection, write/admin capability, or a
master ON/OFF switch.

## Architecture

```
Hermes
  -> external M6 adapter / plugin-context registration   (src/integration/hermes_read_adapter.py)
  -> thin local transport (stdio/loopback owned by host)
  -> M6 Dispatcher (reused M6.1-M6.4)
  -> M5 AuthorizedReadService
  -> M3 / M4
  -> SQLite TRUE READ-ONLY
```

The adapter reuses `m6.tool_schemas`, `m6.mcp_wrapper.handle_call`, and
`m6.configure`. It contains NO SQL, NO JSONL logic, NO policy/grant/M3/M4/relation
logic, NO ranking/selection/injection, NO LLM, NO network. It forwards and
serializes only.

## Hermes-core modification rule — COMPLIED

The approved external registration surface is the project-local plugin-context
idiom (`register_tool(name, schema, handler)`), mirrored by
`src/integration/hermes_registration.py` (`register_hook`) and `capture_adapter.py`.
No Hermes-core source was modified. No `M6 PLAN DEVIATION` was raised.

## Tool registration (req: exactly the 10 approved read tools)

Registered via `HermesReadAdapter.register(context)`:
1. memory_query
2. memory_search
3. memory_get_event
4. memory_get_related
5. project_get_charter
6. project_list_requirements
7. project_list_decisions
8. project_get_state
9. project_list_verifications
10. project_list_artifacts

No extra/hidden tools. `FORBIDDEN_TOOL_NAMES` blocks any write/admin tool from
being registered even if a future schema change attempted it. Verified absent:
execute_sql, raw_sql, database_query, read_jsonl, raw_jsonl, write_memory,
create_memory, update_memory, delete_memory, project_set_state,
project_create_requirement, project_create_decision, create_grant, revoke_grant,
supersede_grant, grant_admin.

## Schema parity + READ-only + authority rejection

- `tool_schemas()` (M6.4) is the single source; adapter exposes `inputSchema` 1:1.
- Every schema constrains `operation == "READ"` and `additionalProperties: false`.
- Top-level forbidden authority fields (admin, is_admin, trusted, grant_admin,
  grant, authorized_read_grant, effective_scope, bypass_policy, verified,
  cross_profile_allowed, raw_sql, ...) are rejected at M6 contract validation
  (`INVALID_REQUEST`).
- WRITE operation -> `UNSUPPORTED_OPERATION`. Never routed to a writer.

## Identity (explicit/unbound, no inference, no retention)

- `requesting_profile_id` is passed through from the explicit caller argument;
  if absent, the request is unbound (null).
- The adapter does NOT derive identity from OS user, HOME, cwd, session, project,
  connection, or process.
- No `connection.profile` / `last_requester` / `session_default_profile` state is
  stored. Concurrent calls with different `requesting_profile_id` are isolated
  (verified with parallel threads).

## Authorization (current-grant behavior preserved)

- Same-profile read (PR1 -> P, target PR1): SUCCESS.
- Cross-profile (PR1 -> P, target PR2) for all 10 tools: POLICY_DENIED.
- Exact persistent READ grant (requirement/decision): SUCCESS; other project
  resources remain POLICY_DENIED (resource-type isolation enforced by M5).
- Revoked grant: the NEXT request is DENIED — M5 grant state is resolved fresh
  per request; the adapter caches nothing.
- Linked-resource target independently authorized: cross-profile project read
  with `include_source_event=True` is POLICY_DENIED.

## Direct vs adapter parity

For all 10 tools, `M6 Dispatcher` and `HermesReadAdapter.call` produce identical
status for SUCCESS, EMPTY, POLICY_DENIED, INVALID_REQUEST, CAPABILITY_UNAVAILABLE.
The adapter adds transport/registration only.

## Failure isolation

- Missing DB at startup: `RegistrationFailure` (bounded); `call` returns
  CAPABILITY_UNAVAILABLE; Hermes remains usable.
- Unreadable/invalid-schema DB: same bounded path; no crash.
- Internal exception during a call: handler returns sanitized DOWNSTREAM_ERROR
  (no raw traceback, SQL, path, secret, grant row, or stack snippet).
- No unsafe fallback to raw JSONL / unrestricted storage.

## Lifecycle

- `startup()`: validates config, resolves store path dynamically, opens a
  read-only connection, confirms a queryable table, initializes the read-only
  M6 runtime. Performs NO migration, NO rebuild, NO mutation (verified via DB
  byte-hash before/after).
- `shutdown()`: drops registration + runtime state; no writes (verified).
- `restart()`: deterministic re-init; re-registration yields the same 10 tools.
- No orphan adapter state after shutdown; no persistent M6 session state.

## Read-only / no-write / no-master-switch / no-injection

- Schema remains v8; no migration executed by the adapter.
- M3/M4/M5 tables and canonical JSONL are never written by the adapter.
- No write/admin tools; no GrantAdminService / AuthorizedWriteService imported.
- No master ON/OFF switch (ZERO_MEM_ENABLED / zero_mem.enabled / master_enable /
  memory_system_enabled / disable_zero_mem absent from src/integration).
- No automatic context injection (controlled_injection / auto_inject absent).
- No ranking/vector/embedding/LLM reranking.

## Security-sensitive logs

Adapter diagnostics carry only bounded operational status (e.g.,
`store_unavailable`, `registration_failed`); no protected content, FTS snippets,
grant rows, credentials, or unrestricted paths.

## Regression gates (all green)

- M6.1 focused: 69 passed
- M6.2 focused: 50 passed
- M6.3 focused: 44 passed
- M6.4 focused: 79 passed
- M6.5 focused: 59 passed
- Combined M6 (M6.1-M6.5): 301 passed
- M1 / M3 / M4 / M5 regressions: 659 passed
- Full canonical under clean isolated HOME: 1405 passed, 3 skipped, 0 failed
- Fresh ad-hoc verifier (hermes-verify-m65.py, OS-safe, 36 required checks +
  11 authority-field sub-checks): 46 passed, 0 failed; verifier removed after run.

## Path safety

- All repo paths resolved via `git rev-parse --show-toplevel`; fixtures use
  pytest `tmp_path`; no hard-coded /home/<user> paths.
- Verifier targeted committed paths: all resolved (acceptance-m6.5.md,
  project-state.yaml, implementation-plan.json, src/integration/hermes_read_adapter.py,
  tests/unit/test_m6_hermes_adapter.py, src/integration/m6/*).

## Deferred scope (untouched)

- M6.6: not started.
- M7: not started.
- Master Zero-Mem ON/OFF switch: not implemented (reserved for M7).
- Automatic context injection: absent.
- Ranking / vector / embedding: absent.

## Final-HEAD canonical gate

Run against the freshly committed evidence/state-binding HEAD (this file +
state update) under clean isolated HOME:

```
.venv/bin/python -m pytest tests/ -q
```

Required outcome: 0 failed, no deselection, no added skip/xfail. (Executed after
this file and state are committed; result recorded in the final report.)
