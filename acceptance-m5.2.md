# M5.2 — Profile/project/knowledge-space read authorization integration

**Status:** VERIFIED
**Milestone:** M5 (overall IN PROGRESS; M5.1 VERIFIED; M5.2 complete; M5.3 not started)
**Schema version:** 7 (no migration v8; no `zm_access_grants` / `zm_policy_audit`)
**Starting commit:** `076c7e7a69fd02f0fa1376f4e14bd5c3e6ec6849`
**Implementation commit:** `92eb70b083b5c7e6b0aeae0a3a3ade1609ec7111`
**FTS-fix commit:** `dfdacf2ea1bce24cfb6def91a3cd1eb33ea64e7f`
**Tested commit:** `dfdacf2ea1bce24cfb6def91a3cd1eb33ea64e7f`
**Evidence/state-binding commit:** (this file + state commits, see below)

## Objective

Integrate the VERIFIED M5.1 READ policy boundary with the existing M3 (structured
query, FTS, get_event/get_trace) and M4 (Charter, Requirements, Decisions, Current
State, Verifications, Project Artifacts) read surfaces. Authorization is evaluated
BEFORE protected retrieval; the low-level query is never invoked on DENY.

## Architecture — authorized-read facade

`src/access/authorized_read.py` defines `AuthorizedReadService(store, requesting_profile_id)`:

```
AccessRequest
  -> evaluate()            (M5.1 policy, pure/in-memory, no LLM/network)
  -> AccessDecision
  -> ALLOW: translate AllowedScope -> restrictive query filters
            -> invoke LOW-LEVEL M3/M4 read API (TRUE READ-ONLY: mode=ro + query_only)
            -> DEFENSIVE post-validation: drop any record outside AllowedScope
  -> DENY:  return typed AuthorizedResult WITHOUT invoking any low-level query
```

LOW-LEVEL READ (existing M3/M4 TRUE READ-ONLY query implementation) is unchanged.
AUTHORIZED READ (this facade) wraps it; it never rewrites lower-level contracts.

### Query composition from AllowedScope

- `_profile_predicate(scope, requester)` builds the restrictive profile SQL:
  - scoped profiles: `profile_id IN (...)`
  - global read (bound): `(profile_id = requester OR profile_id IS NULL)` — global/default
    means NULL-profile (unowned) records; cross-profile is NEVER included.
  - unbound + global: `profile_id IS NULL` only.
  - implicit local (no global): `profile_id = requester` (fail closed; never cross-profile).
- M3 structured query builds the WHERE from `_build_where` (reuses M3 deleted-exclusion
  + filters) AND the profile predicate, plus the request's `project_ids` as the project
  filter. Authorization filters AND with caller filters.
- M4 project reads require `project_id in scope.allowed_project_ids` (explicit project
  membership; no well-defined "global project" in M4, so cross-project stays DENIED).
- FTS: SQL pinned to the explicit allowed profile(s) when present; under global with no
  explicit profile the SQL is broader but post-validation keeps only NULL-profile and
  requester-owned hits (defense-in-depth; no unauthorized content returned).

### Defense-in-depth post-validation

After the low-level query returns, every row is checked by `_scope_allows`. Any row
outside `AllowedScope` triggers a fixed `DENY_ISOLATED_SCOPE_ESCAPE` result (fail
closed), never a silent partial return. `_scope_allows` always includes the requesting
profile in the allowed set (the caller owns their own data) and DENIES cross-profile.

## TRUE READ-ONLY proof

- All facade reads go through `open_readonly` stores (`file:...?mode=ro` +
  `PRAGMA query_only=ON`). No writer/projector, no migration, no canonical event
  append, no audit write.
- Verified by `test_true_read_only_store_unchanged`: store snapshot before/after a full
  authorized-read workload is byte-identical. `test_schema_remains_v7`: schema == 7.
  `test_no_migration_or_audit_tables_created`: no `zm_access_grants`/`zm_policy_audit`.

## Secret safety

Synthetic secret `SK-M5-2-SECRET-ABC` is stored only in an out-of-scope PR2 record
(`M-E2`). Verified absent from:
- M3 structured results (cross-profile PR2 never returned to PR1),
- FTS snippets (point 12),
- M4 object results,
- denial metadata (point 15: `SECRET not in denial.__dict__`).

## Denial information-leak

A denied request returns only a fixed `reason_code` + audit-safe metadata. It never
discloses record count, matching IDs, artifact names, lifecycle state, FTS snippets, or
source-event existence (`test_denial_leaks_no_existence_information`,
`test_denial_distinct_from_zero_result_success`).

## Boundary results

- Same-project does NOT bypass profile boundary: `target_profile_ids=['PR2'],
  project_ids=['P']` for requester PR1 → DENY (project membership ≠ profile access).
- Global READ correct: implicit + global returns PR1 + NULL-profile (default) records;
  `include_global=False` excludes default; `isolated_mode=True` removes implicit global.
- Knowledge spaces remain explicit: space-only scope maps to own-profile (fail closed);
  profile does not expand spaces.
- FTS cannot expose unauthorized content (point 12); SQL pinned to authorized profile.
- M4 reads (all six surfaces) obey policy; cross-profile M4 reads denied.
- Minimum linked-resource boundary: `get_event` on an out-of-scope PR2 id is DENIED
  (source-event resolution cannot escape scope); verification/artifact subject
  references do not grant access.

## Verification evidence

| suite | result |
|-------|--------|
| M5.1 focused (`test_m5_access_policy.py`) | 50 passed |
| M5.2 focused (`test_m5_authorized_read.py`) | 35 passed |
| Combined M5 (M5.1 + M5.2) | 85 passed |
| M3 regressions (query/fts/relations/integration/verification/pagination) | passed |
| M4 regressions (rebuild/read/verification_artifact/state/decision) | passed |
| Full canonical suite (isolated HOME) | 945 passed, 3 skipped, 0 failed |
| Fresh ad-hoc verifier (18 points) | 18/18 PASS |

The 3 skips are pre-existing capability skips (unchanged from M5.1). `test_no_real_hermes_home_writes`
is intact and runs under the isolated HOME.

## Result contract

`AuthorizedResult` distinguishes: allowed+results, allowed+zero, denied (explicit,
with reason_code, no existence disclosure), invalid request, and downstream sanitized
error (distinct from DENY — carries `error` code, `denied=False`). A DENY is never
disguised as `results=[]/error=None`.

## Boundaries preserved (no M5.3+/grants/v8/audit/WRITE)

- schema remains v7; no migration v8; no `zm_access_grants`/`zm_policy_audit`.
- no grant-backed cross-profile access (M5.4+).
- no WRITE integration (M5.4).
- no audit persistence; `AccessDecision` stays in memory.
- no LLM / no network / no real `~/.hermes` writes.
- M5.1 rules unchanged.
