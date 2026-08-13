# M6.1 — Acceptance Evidence (VERIFIED)

**Milestone:** M6.1 — Integration contracts and read-only transport/tool surface.
**Status:** VERIFIED (M6 overall: IN PROGRESS; M6.2 next; M7 not started).
**M6 plan commit:** 4cd0643f15cad7b3ee634c217550bb9e1c3b26f6
**Starting commit:** 30ef4858270ab64f041eb7b82846d5c1f28e5354
**Implementation commit:** 40eb1af506d88e3520229094eac8a6ee9ab13ac6
**Tested commit:** 40eb1af506d88e3520229094eac8a6ee9ab13ac6
**Evidence/state-binding commit:** <filled on commit>
**Schema version:** 8 (unchanged; NO migration v9)
**Working tree:** clean

---

## Objective

Implement ONLY the integration contracts and read-only tool/transport surface
that later M6 increments connect to the verified M5 authorized-read service.
M6.1 does NOT wire M3/M4 execution (M6.2/M6.3). It proves the surface is
READ-ONLY by construction and cannot be turned into a policy/identity bypass.

## Delivered (M6.1 scope only)

- **src/integration/m6/contracts.py** — strict typed `M6Request`, `M6Response`,
  `Operation` (READ only), `ResourceType`, `ResponseStatus`, `validate_request`.
  Rejects unknown fields, forbidden caller-authority fields (`admin`, `is_admin`,
  `trusted`, `grant_admin`, `grant`, `verified`, `cross_profile_allowed`,
  `bypass_policy`, `raw_sql`, `authorization`, `grant_object`,
  `authorized_read_grant`, `grant_rows`), non-READ operation, invalid enums/limits.
  Identity is explicit (`requesting_profile_id` may be None=unbound); never inferred.
- **src/integration/m6/errors.py** — `M6Error`/`M6ErrorCode` → sanitized envelope;
  never exposes traceback/SQL/SQLite internals/path/secret/grant rows.
- **src/integration/m6/tools.py** — allowlisted READ tool registry (10 tools) with
  FIXED per-tool `resource_type`; forbidden write/grant-admin/SQL/JSONL tools
  excluded and unreachable. Caller cannot downgrade/override resource type.
- **src/integration/m6/dispatcher.py** — transport-independent `Dispatcher`:
  validate → allowlist → fixed resource type → READ-only → invoke registered
  handler (none in M6.1) or return deterministic `CAPABILITY_UNAVAILABLE`.
  No SQLite/JSONL/projector/migration/grant/WRITE path imported or invoked.
- **src/integration/m6/mcp_wrapper.py** — thin MCP-facing wrapper (`tool_schemas`,
  `handle_call`, `serialize`): transport only; no policy/SQL/grant/M3/M4 logic.
- **tests/unit/test_m6_contracts.py** — 69 focused tests.

## Acceptance criteria proven

- **M6 plan committed** (`4cd0643`); M5 remains VERIFIED; no schema v9; M6.1 started.
- **Tool registry narrow/allowlisted:** 10 READ tools; unknown tool → UNSUPPORTED_TOOL;
  no dynamic function execution; forbidden tools absent (execute_sql, raw_sql,
  sqlite_query, database_query, read_jsonl, raw_jsonl, read_file_arbitrary,
  write_memory, create_memory, update_memory, delete_memory, create_grant,
  revoke_grant, supersede_grant, grant_admin, project_write, requirement_write,
  decision_write).
- **Normal M6 tools READ-only:** every tool `operation=READ`; WRITE operation →
  UNSUPPORTED_OPERATION (never routed to WRITE authorization).
- **Caller cannot self-authorize:** `admin`/`trusted`/`grant_admin`/`grant_object`/
  `authorized_read_grant` rejected; no grant structure accepted as proof.
- **Identity explicit/non-inferred:** from cwd/repo/session/client/process/MCP/
  previous request — none used; `session_id` is query-narrowing only, NOT authority.
- **Tool resource types fixed:** `project_list_requirements`→requirement,
  `project_list_decisions`→decision, `project_list_artifacts`→artifact (metadata),
  `memory_get_related`→relation; caller substitute rejected.
- **Response envelope sanitized:** SUCCESS / EMPTY (distinct from DENY) / POLICY_DENIED
  / INVALID_REQUEST / UNSUPPORTED_OPERATION / UNSUPPORTED_TOOL /
  CAPABILITY_UNAVAILABLE / DOWNSTREAM_ERROR; no raw traceback/SQL/path/secret.
- **Transport wrapper thin:** schemas map with `operation="READ"` const; malformed
  payload / unknown tool / unknown field / admin field → safe envelope.
- **No M3/M4/M5 semantic duplication:** M6.1 imports no M3/M4/WRITE/grant/migration
  logic; dispatch defers execution to later increments.
- **No schema change:** v8; no migration v9; no integration/MCP/session-auth tables.
- **Read-only proof by construction:** static AST check — no import of
  GrantAdminService / AuthorizedWriteService / grant_events / migrations / ingest;
  no SQLite/JSONL/projector/canonical-writer path reachable.
- **Zero LLM + zero external network:** static import check + runtime dispatch
  performs no network I/O.
- **No automatic context injection; no M7 behavior.**

## Files changed

- `src/integration/m6/__init__.py`, `contracts.py`, `errors.py`, `tools.py`,
  `dispatcher.py`, `mcp_wrapper.py`
- `tests/unit/test_m6_contracts.py`
- `acceptance-m6.1.md`, `project-state.yaml`, `implementation-plan.json`

## Test results

- M6.1 focused: **69 passed**
- M5 integration regressions: green (M5.1-5.6 suites)
- M3/M4 regressions: green (query/relations/pagination/read/verification-artifact/schema)
- Full canonical under clean isolated HOME: **1173 passed, 3 skipped, 0 failed**
- Fresh OS-safe ad-hoc verifier: **21/21 PASS** (run, then removed)

## Final-HEAD hard gate

M6.1 VERIFIED: M6 plan committed, M5 VERIFIED, contracts complete, allowlisted
registry, READ-only, no SQL/JSONL/write/grant-admin tool, no self-authorization,
explicit identity, fixed resource types, sanitized envelope, thin wrapper, no
M3/M4/M5 duplication, schema v8, zero LLM/network, canonical 0 failed, no M6.2+
impl, no M7, working tree clean.

M6.1: VERIFIED
M6 overall: IN PROGRESS
Schema version: 8
Next: M6.2 — M3 authorized memory read tools
