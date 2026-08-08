# M5.1 — Policy contracts and authoritative access matrix

**Status:** VERIFIED
**Milestone:** M5 (overall IN PROGRESS; M5.1 complete, M5.2 not started)
**Schema version:** 7 (no migration v8 introduced)
**Plan:** `.hermes/plans/2026-08-08_000001-m5-access-policy-plan.md` (committed `4d68316`)

## Objective (M5.1 only)

Implement the deterministic policy **contracts** and the **authoritative base
access matrix**. M5.1 does NOT integrate authorization into M3/M4 retrieval, does
NOT implement persistent grants, does NOT create schema v8, and does NOT write
policy-audit events. It decides an authorized *scope*; it does not retrieve,
rank, select, inject, mutate, authenticate, or infer identity.

## Architecture boundaries (verified)

| Boundary | Result |
|---|---|
| No retrieval / ranking / context injection | ✅ `evaluate` performs no M3/M4 queries |
| No identity inference | ✅ null `requesting_profile_id` stays null; no cwd/path/session inference |
| No persistent grants (M5.4) | ✅ `zm_access_grants` / `zm_policy_audit` absent; no grant tables referenced |
| Schema remains v7 | ✅ `CURRENT_SCHEMA_VERSION == 7`; no `migrate_8` |
| No audit persistence | ✅ no `policy_decision` events written |
| No M5.2+ / M6 behavior | ✅ only contracts + base precedence |
| Zero LLM / network | ✅ static analysis confirms no openai/requests/http/llm/socket/urllib/aiohttp |
| No real `~/.hermes` writes | ✅ evaluated under isolated HOME; no home-path in scope |

## Contracts

- **`AccessRequest`** — frozen dataclass: `operation` (READ|WRITE), `requesting_profile_id`
  (explicit or None=unbound), `target_profile_ids`, `project_ids`, `knowledge_space_ids`,
  `include_global` (None→default True), `isolated_mode`, `resource_type`, `resource_id`.
  `validate()` normalizes: parses operation, validates resource_type, de-duplicates
  and sorts id lists (deterministic), resolves `include_global`, preserves explicit
  identifiers (never infers missing ones).
- **`AllowedScope`** — frozen normalized scope: `operation`, `allowed_profile_ids`,
  `allowed_project_ids`, `allowed_knowledge_space_ids`, `global_read_allowed`,
  `resource_types`, `isolated`. Invariants: project permission adds NO profile;
  profile permission adds NO projects/spaces implicitly; relations never expand scope;
  `global_read_allowed` set only by global-READ rule or explicit grant.
- **`AccessDecision`** — frozen result: `allow`, `normalized_scope`, `denied_scopes`,
  `reason_code`, `grant_refs`, `decision_id` (correlation only, never affects semantics).
  Contains only audit-safe, non-secret metadata.

## Reason codes (fixed, sanitized)

`ALLOW_LOCAL_PROFILE_READ`, `ALLOW_GLOBAL_READ`, `ALLOW_LOCAL_WRITE`,
`DENY_GLOBAL_WRITE`, `DENY_CROSS_PROFILE_READ`, `DENY_CROSS_PROFILE_WRITE`,
`DENY_CROSS_PROJECT`, `DENY_ISOLATED_SCOPE_ESCAPE`, `DENY_UNKNOWN_PROFILE`,
`DENY_UNKNOWN_PROJECT`, `DENY_UNKNOWN_SPACE`, `DENY_UNAUTHORIZED_SPACE`,
`DENY_UNBOUND_PROTECTED`, `DENY_INVALID_REQUEST`.

## Base precedence (M5.1 subset, no grants)

1. invalid request → `DENY_INVALID_REQUEST`
2. isolated implicit scope escape → `DENY_ISOLATED_SCOPE_ESCAPE`
3. cross-profile boundary (no grants) → `DENY_CROSS_PROFILE_*`
4. cross-project protected boundary → `DENY_CROSS_PROJECT`
5. permitted same-profile local scope → `ALLOW_LOCAL_*`
6. permitted global READ → `ALLOW_GLOBAL_READ`
7. otherwise → `DENY_*` (fail closed)

## Authoritative access matrix (encoded exactly)

| Scenario | Result |
|---|---|
| same profile READ | ALLOW (local) |
| global READ default | ALLOW (global_read_allowed) |
| include_global=False | global excluded |
| different profile READ | DENY (cross-profile) |
| different profile + same project READ | DENY (cross-profile; project membership ≠ profile access) |
| different project READ | DENY (cross-project) |
| unbound global READ | ALLOW (global only) |
| unbound protected profile READ | DENY |
| same-profile local WRITE | ALLOW |
| global WRITE | DENY |
| different profile WRITE | DENY |
| different profile + same project WRITE | DENY |
| cross-project WRITE | DENY |
| unbound WRITE | DENY |
| READ allowance ≠ WRITE allowance | confirmed (separate operations) |
| isolated local same-profile | ALLOW, no global |
| isolated removes implicit global | DENY escape when nothing explicitly selected |
| isolated blocks implicit expansion | explicit local scope only |

**Regression case (mandatory):** requesting A, target B, project P (both relate to
P) → **DENY** (`DENY_CROSS_PROFILE_READ`); project membership does NOT override the
profile boundary.

## Determinism & zero-token

Same `AccessRequest` → identical `AccessDecision` (allow/deny/scope/reason).
`decision_id` (if supplied) does not alter semantics. No LLM, no network, no
wall-clock logic, no random ids in policy result.

## Verification evidence

- **Focused M5.1 suite:** `tests/unit/test_m5_access_policy.py` —
  **50 passed in 0.07s** (contract validation, READ matrix, WRITE matrix,
  isolation, scope normalization, reason codes, determinism, architecture boundaries).
- **M3/M4 compatibility regression:** M5.1 is contracts-only with no M3/M4 import;
  existing retrieval results unchanged (confirmed by full canonical suite below).
- **Full canonical suite (clean isolated HOME):** **910 passed, 3 skipped, 0 failed**
  (860 prior + 50 new M5.1). The 3 skips are pre-existing capability skips (FTS5
  unavailability class), unchanged from M4 final. `test_no_real_hermes_home_writes`
  intact (not weakened/skipped/deslected).
- **Fresh OS-safe ad-hoc verifier (16/16 PASS):** same-profile READ, global READ,
  global disabled, cross-profile READ deny, same-project/diff-profile READ deny,
  same-profile local WRITE, global WRITE deny, cross-profile WRITE deny, READ≠WRITE,
  unbound global READ, unbound protected deny, isolated removes global, profile-not-
  expanded-from-project, deterministic repeat, schema v7, no M3/M4 mutation. Script
  removed after run.

## Files changed (M5.1 only)

- `src/access/__init__.py` (new package)
- `src/access/contracts.py` (new)
- `src/access/policy.py` (new)
- `tests/unit/test_m5_access_policy.py` (new)

No product source beyond `src/access/`, no schema migration, no `project-state.yaml`/
`implementation-plan.json` logic change beyond M5.1 state binding.

## Commits

- M5 plan commit: `4d68316894e04b3db0fc433d627ed98b595232b9`
- M5.1 implementation commit: `4296085f4788a1bf44863ac6913235f694e199da`
- M5.1 tested commit: `4296085f4788a1bf44863ac6913235f694e199da`
- M5.1 evidence/state-binding commit: (this commit)

## Next

M5.2 — Profile/project/knowledge-space READ authorization integration (wire
`AllowedScope` into M3/M4 read APIs; no grants yet).
