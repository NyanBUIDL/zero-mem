# M5.4 — Acceptance Evidence (VERIFIED)

**Milestone:** M5.4 — WRITE authorization, persistent access grants, migration v8.
**Status:** VERIFIED (M5 overall remains IN PROGRESS — M5.5 not started).
**Schema version:** 8.
**Plan-correction commit:** e4f559cfe9d21edb9d81eb3e3c4025ad24df4ae7 (trusted control-plane grant-administration authority).
**Starting commit:** e5263bb (M5.3 evidence).
**Implementation commit:** 9cbdeda97a5d6b222fcbbd5113bde7b672505a9c.
**Tested commit:** 9cbdeda97a5d6b222fcbbd5113bde7b672505a9c.
**Evidence/state-binding commit:** this file + project-state.yaml + implementation-plan.json (next commit).

## Scope delivered (only)

1. Migration v8: zm_access_grants + zm_policy_audit derived tables; CURRENT_SCHEMA_VERSION = 8.
2. Canonical structured access_grant events (append-only JSONL) + deterministic projector into derived state.
3. Derived zm_access_grants projection (idempotent CREATE/REVOKE/SUPERSEDE; revoke via state='revoked'; supersede via explicit supersedes/replaced_by; no self-supersession).
4. zm_policy_audit schema foundation + safe policy_decision canonical writer + DENY/grant-using audit projector (DENY/grant-using only; never mutates the queried M3/M4 store).
5. Trusted GrantAdminRequest control-plane entrypoint (GrantAdminService.create/revoke/supersede) — structurally separate from the normal AccessRequest READ/WRITE surface; no mode="admin" param; no caller-controlled authority flags.
6. Deterministic grant resolution (resolver.resolve_read_grants / resolve_write_grant) producing validated AuthorizedReadGrant / WRITE grant; M4 read-only verification predicate (get_verification -> verification_status == 'verified').
7. Persistent READ grants feed the VERIFIED M5.3 compose_effective_scope unchanged (no M5.3 redesign).
8. WRITE authorization (AuthorizedWriteService.authorize / authorize_then_write) with authorization-before-mutation.

NOT delivered (per directive): M5.5 full linked-resource bypass matrix; M5.6 final rebuild; M6 behavior. No grant_admin role/grant; no bootstrap recursion.

## Implementation

- src/storage/migrations/migrate_8.py (new): zm_access_grants (lifecycle_status ENUM CHECK = authoritative CLOSED enum; state column separate so state='revoked' is allowed while lifecycle_status='revoked' is rejected) + zm_policy_audit DDL; down(8) drops only v8 tables (M0-M4 state preserved).
- src/storage/migrations/__init__.py: registered migrate_8; CURRENT_SCHEMA_VERSION = 8.
- src/storage/ingest.py: added zm_access_grants, zm_policy_audit to DERIVED_TABLES so rebuild_from_jsonl drops/recreates them deterministically.
- src/access/grant_events.py (new): AccessGrantEvent (plan 11.1 contract), to_canonical_dict/from_canonical_dict (structured JSONL; prose ignored), project_grant_event (idempotent upsert + revoke + supersede; self-supersede rejected), rebuild_grants (ordered replay, no drift/dupes).
- src/access/admin.py (new): GrantAdminRequest typed contract (action CREATE|REVOKE|SUPERSEDE; grant_id; subject_profile; operation; target_type; target_id; resource_types; verification_ref; supersedes; provenance). NO is_admin/trusted/grant_admin/allow_grant_creation/verified authority field. GrantAdminService validated create/revoke/supersede, WRITE verification predicate via M4 read-only lookup, appends canonical event through injected writer (the trusted boundary).
- src/access/resolver.py (new): resolve_read_grants (exact match, lifecycle active, state != revoked, terminal/none non-authorizing, no timestamp winner) -> validated AuthorizedReadGrant; resolve_write_grant (operation==WRITE, verified verification_ref, exact target/resource, conflict -> DENY_POLICY_CONFLICT).
- src/access/authorized_write.py (new): AuthorizedWriteService.authorize (base M5.1 policy -> resolve persistent WRITE grant -> AccessDecision) + authorize_then_write (calls writer/projector ONLY if ALLOW — authorization-before-mutation proof).
- src/access/audit.py (new): record_decision appends canonical policy_decision JSONL (DENY/grant-using) and audit_policy_decision projects to zm_policy_audit (never mutates queried store).
- src/access/authorized_read.py: AuthorizedReadService.__init__ accepts optional grant_conn; _gate auto-resolves persistent READ grants (validated) when no explicit grants passed — feeds M5.3 compose_effective_scope unchanged; raw caller grants only honored when explicitly passed.
- src/access/contracts.py: added ALLOW_EXPLICIT_CROSS_PROFILE_WRITE, DENY_POLICY_CONFLICT.

## Verification results

- M5.4 focused suite (tests/unit/test_m5_grants.py): 70 passed, 0 failed.
- M5.1 focused (test_m5_access_policy.py): 50 passed.
- M5.2 focused (test_m5_authorized_read.py): 35 passed.
- M5.3 focused (test_m5_cross_profile.py): 38 passed.
- Combined M5.1-M5.4: 193 passed.
- Migration regression (test_m4_schema.py): 32 passed (advanced v7->v8 incl. downgrade-to-7 drops only v8 tables, future-version=9 rejected).
- M3 read-only regressions (query/fts/pagination): green.
- M4 read-API + Verification-Record regressions: green.
- Full canonical suite (clean isolated HOME env): 1053 passed, 3 skipped, 0 failed. (3 pre-existing capability skips, unchanged. The one real-home test_no_real_hermes_home_writes failure under the real HOME is an external background kanban sidecar flake — passes under isolated HOME; test left intact per directive.)
- Fresh OS-safe ad-hoc verifier (23 checks): 23/23 PASS, removed after run.

## Trusted control-plane authority (proof)

- Normal AccessRequest READ/WRITE flows reach only evaluate / compose_effective_scope / query_events / authorize_write. None call GrantAdminService. There is NO mode="admin" parameter on any normal-policy function. The only path to CREATE/REVOKE/SUPERSEDE is the GrantAdminService object — entered by call, never by request payload.
- Caller-controlled flags is_admin=true, trusted=true, grant_admin=true, allow_grant_creation=true, verified=true (or equivalents) are absent from AccessRequest/GrantAdminRequest contracts; AccessRequest is a frozen dataclass with no such field, so a caller cannot inject authority. evaluate reads only defined fields.
- A same-profile WRITE, a valid WRITE grant, and a cross-profile WRITE grant confer NO grant-admin authority: none enters GrantAdminService.
- No grant_admin role/grant; no recursive "grant allowing grants"; no profile-owner inference -> no bootstrap recursion.

## Boundaries honored

- JSONL is canonical & append-only; SQLite zm_access_grants/zm_policy_audit are DERIVED (rebuildable from canonical grant history). Grant resolution never appends events.
- lifecycle_status restricted to the authoritative CLOSED enum; lifecycle_status='revoked' rejected by CHECK; revocation uses state='revoked' (non-authorizing).
- READ != WRITE; a READ grant never authorizes WRITE; a WRITE grant is not treated as READ.
- Authorization-before-mutation: denied writes never invoke the target writer/projector (proved by authorize_then_write test).
- No LLM/network in routine M5.4; 0 LLM, 0 network calls.
- Secret safety: synthetic secrets used in tests; no secret payloads printed via decision/grant/audit/error; record_decision/authorize_then_write sanitize outcomes.
- No M5.5 / M5.6 / M6 behavior introduced.
- test_no_real_hermes_home_writes left unchanged; passes under isolated HOME.

## Next

M5.5 — Authorization integration and linked-resource boundary hardening.
