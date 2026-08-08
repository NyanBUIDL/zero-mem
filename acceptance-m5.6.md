# M5.6 — Acceptance Evidence (VERIFIED)

**Milestone:** M5.6 — Policy rebuild, audit, security/performance, final M5 acceptance.
**Status:** VERIFIED (M5 overall now VERIFIED; M6 next, not started).
**Starting commit:** aa2d180f85550f81b499cc006aa61fe62f1c5dad
**Implementation commit:** bbcd8b46394dc39d56104447055d63f52ba8902a
**Tested commit:** bbcd8b46394dc39d56104447055d63f52ba8902a
**Evidence/state-binding commit:** <filled on commit>
**Schema version:** 8 (unchanged; NO migration v9)
**Working tree:** clean

---

## Objective

Complete final integration acceptance for the entire M5 policy layer: deterministic
policy rebuild, incremental/rebuild parity, canonical grant audit, linked-resource
hardening regression, security/performance baselines, and the full canonical suite.

## What was delivered (M5.6 scope only)

- **src/access/rebuild.py** (NEW) — `rebuild_policy_state(conn, jsonl_paths)`:
  reconstructs the M5 DERIVED policy tables (`zm_access_grants`, `zm_policy_audit`)
  from their canonical source events (`access_grant`, `policy_decision` JSONL lines).
  - Narrow scope: only the two M5 policy tables are cleared/rebuilt; all M0-M4
    derived tables, M4 project memory, artifacts, FTS, relations/scopes, verification
    records, and the canonical JSONL itself are preserved untouched.
  - Reuses the EXACT projection functions (`project_grant_event`,
    `project_policy_decision`) used by the incremental admin/audit paths, so
    incremental projection and full rebuild are parity-equivalent by construction.
  - `normalize_grants` / `normalize_audit` provide order-independent tuple comparison.
- **tests/unit/test_m5_policy_rebuild.py** (NEW) — 16 focused tests.
- No product-code change to M5.1-M5.5 behavior; no schema v9; no M6 behavior.

## Acceptance criteria proven

- **Policy rebuild API** (`rebuild_policy_state`) reconstructs M5 derived state from
  canonical JSONL.
- **Grant rebuild result**: rebuilt `zm_access_grants` equals incremental projection
  (same rows, order-independent).
- **Audit rebuild result**: rebuilt `zm_policy_audit` equals incremental projection.
- **Incremental/rebuild parity**: structural (shared projection functions); proven by
  test (`test_incremental_vs_rebuild_grants`, `test_incremental_vs_rebuild_audit`).
- **Repeated rebuild determinism**: rebuild #1 == #2 == #3; identical normalized rows,
  no duplicates, no drift, no `now()`-based state.
- **Grant lifecycle result**: only `active` + non-revoked + otherwise-valid grants
  authorize; `raw/observed/candidate/confirmed/superseded/conflicted/archived/deleted`
  do not; `state='revoked'` is domain-only (never a lifecycle value).
- **Revocation result**: `revoke` sets `state='revoked'`; non-authorizing.
- **Supersession result**: explicit G1 <- G3 chain preserved (`supersedes`/`replaced_by`
  + old `lifecycle_status='superseded'`); no timestamp winner; superseded grant does
  not authorize.
- **Conflict result**: `conflicted` grant fails closed (`DENY_POLICY_CONFLICT`
  semantics preserved deterministically).
- **WRITE verification result**: after rebuild, WRITE grants still require
  `verification_ref` + resolved M4 `verification_status == 'verified'` (read-only);
  presence of reference alone is insufficient; unverifiable ref denied.
- **READ/WRITE result**: `READ != WRITE`; READ grant cannot authorize WRITE; isolated
  default WRITE denied; cross-profile WRITE requires valid WRITE grant.
- **Isolation result**: `isolated_mode=True` still prevents implicit global/project/
  profile/space/relation expansion; explicit authorized scope exact.
- **Cross-profile result**: combined A-local + B/P + C/K READ grants yield deterministic
  EffectiveReadScope; no B/Q, C/P, or unrelated-space leakage.
- **Authorization-before-retrieval**: `AccessRequest -> policy -> grant resolution ->
  EffectiveReadScope -> restrictive query -> defensive validation` intact.
- **Authorization-before-mutation**: `WriteRequest -> WRITE policy -> grant resolution
  -> AccessDecision -> writer only if allow`; denied WRITE invokes writer 0 times;
  allowed exact WRITE invokes 1 time.
- **Linked-resource result**: full M5.5 matrix re-confirmed (relation/parent-child/
  source_event/supersession/verification/artifact/resource-type/profile-project-space/
  global/isolated); every linked target independently scope-checked.
- **Grant-admin boundary**: normal `AccessRequest` cannot CREATE/REVOKE/SUPERSEDE;
  valid WRITE grant cannot administer; `is_admin`/`trusted`/`grant_admin`/`verified`/
  `allow_grant_creation` confer no authority; `GrantAdminService` remains separate.
- **Caller self-elevation impossible**: `AccessRequest` has no admin/authority fields.
- **Audit persistence semantics**: persistent canonical `policy_decision` events; derived
  `zm_policy_audit`; ONLY DENY + grant-using ALLOW persisted (ordinary local ALLOW READ
  remains ephemeral — not persisted); SQLite is derived, not canonical.
- **Audit safety**: DENY audit records requested normalized target scope only; no
  discovered protected record ID, count, snippet, verification detail, or artifact name.
- **Secret safety**: synthetic secrets absent from AccessDecision, resolver output, audit
  rows, reason codes, relation/FTS/M4 results, artifact refs, cursors, errors, logs.
- **TRUE READ-ONLY result**: M3/M4 retrieval stores remain `mode=ro + query_only`;
  audit events go through a separate canonical sink.
- **JSONL authority/immutability**: routine ops (grant resolution, authorized/linked
  reads, verification resolution, performance queries) do not mutate JSONL; only trusted
  `access_grant` admin events + approved `policy_decision` audit events append.
- **SQLite integrity**: READ workloads leave M5/M4/M3/M2 tables unchanged (row counts
  stable); only explicit rebuild mutates M5 derived tables.
- **Transaction/idempotence**: repeated processing of same canonical event does not
  duplicate grants/revocations/supersessions/audit rows (PK + UPSERT idempotence).
- **Zero-LLM/network proof**: `rebuild.py` imports no socket/requests/http/openai/llm;
  policy evaluation, scope normalization, grant resolution, audit projection, rebuild,
  and READ/WRITE authorization require 0 LLM + 0 network calls.
- **Performance baseline**: recorded (grant resolution, scope composition, authorized
  M3/M4 read, relation boundary, grant/audit rebuild) on deterministic synthetic corpus;
  no pathological behavior; no caching added solely to improve benchmark.
- **Clean isolated canonical suite**: 0 failed.

## Files changed

- `src/access/rebuild.py` (NEW)
- `tests/unit/test_m5_policy_rebuild.py` (NEW)
- `acceptance-m5.6.md`, `project-state.yaml`, `implementation-plan.json` (state binding)

## Boundaries respected

- NO schema v9 (migration v8 untouched).
- NO redesign of M3/M4.
- NO ranking/semantic/vector selection, LLM query rewriting, context injection, or
  prompt assembly.
- NO M6 behavior; M6 remains untouched.
- JSONL canonical + append-only; SQLite zm_access_grants / zm_policy_audit derived.

## Test results

- M5.6 focused: **16 passed** (tests/unit/test_m5_policy_rebuild.py)
- Combined M5.1-M5.6: **244 passed**
- M3/M4 regressions: green
- Full canonical under clean isolated HOME: **1104 passed, 3 skipped, 0 failed**
- Fresh OS-safe ad-hoc verifier: **26/26 PASS** (run, then removed)

## Final-HEAD hard gate

M5.6 VERIFIED and M5 VERIFIED because all hard-gate criteria hold; canonical suite at
final HEAD has 0 failed; working tree clean; M6 not started.

M5: VERIFIED
M5.6: VERIFIED
Schema version: 8
Next: M6 — MCP/Hermes read-only integration
