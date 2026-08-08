# M5.3 — Acceptance Evidence (VERIFIED)

**Milestone:** M5.3 — Isolated mode + explicit cross-profile READ composition.
**Status:** VERIFIED (M5 overall remains IN PROGRESS — M5.4 not started).
**Schema version:** 7 (unchanged; no migration v8).
**Implementation commit:** 8d967acfb77932f1022bb6bdfab61857484ad4a9
**Tested commit:** 8d967acfb77932f1022bb6bdfab61857484ad4a9

## Scope

M5.3 is the READ-only composition layer between caller intent and the M3/M4 read
surfaces. It decides AUTHORIZED SCOPE only — it does NOT retrieve, rank, select,
inject, mutate, infer identity, or authenticate. It consumes an explicit
requesting_profile_id (or null) and optional pre-validated in-memory
AuthorizedReadGrant objects of the approved plan section 11.1 shape.

## Implementation

- src/access/grants.py (new): AuthorizedReadGrant dataclass (plan 11.1 in-memory
  shape, no persistence), EffectiveReadScope dataclass, and compose_effective_scope()
  implementing Requested AND PolicyAllowed AND ExplicitGrant with deterministic
  intersection. READ-only; all-or-nothing for uncovered cross-profile targets;
  profile/project/space/resource-type grant handling. No persistent grant state,
  no migration v8, no audit events, no LLM/network.
- src/access/authorized_read.py (rewritten facade): decomposes EffectiveReadScope
  into base + per-grant atomic scopes; runs one restrictive query per scope; merges,
  sorts by (created_at, event_id), de-duplicates by event_id, then keyset-slices the
  MERGED set (deterministic pagination, no duplicate/skipped IDs). _profile_predicate /
  _scope_allows fold requester into implicit-local scopes (preserving M5.2) while
  project/space grant scopes stay profile-unrestricted. FTS decomposed across
  authorized profiles. Cursor fingerprint bound to EffectiveReadScope.
- src/access/policy.py: isolated knowledge-space-only request = DENY_ISOLATED_SCOPE_ESCAPE.
- src/access/contracts.py: added ALLOW_EXPLICIT_CROSS_PROFILE_READ,
  DENY_CROSS_PROFILE_READ, DENY_UNAUTHORIZED_CROSS_PROFILE_READ.

## Test corrections (documented)

1. M5.3 fixture test_m4_cross_profile_requirements: P and P2 corpora reused duplicate
   canonical identities (R1/D1/S1/V1). zm_requirements PK is requirement_id alone, so
   the P2 rebuild R1 collided with P R1, triggering a ConflictError that rolled back
   P2 row. M4 reader (list_requirements) is CORRECT (filters project_id=? AND
   lifecycle_status<>deleted). Fix: distinct P2 identities (R2/D2/S2/V2), assert R2.
   This is a fixture defect, not an M4 regression.
2. test_fts_across_authorized_profiles_only: FTS highlighter wraps the matched term
   in brackets (SK-M5-3-[SECRET]-XYZ) so the literal SECRET constant is not a
   substring. PR2 is explicitly authorized, so its content should appear. Fixed to
   assert highlighted token [SECRET] and that M-E2 is returned.
3. test_knowledge_space_does_not_expand_profile (M5.2 unit): updated to the new
   predicate contract — space-only scope has no profile predicate and never infers
   a cross-profile id (PR2).
4. test_isolated_mode_blocks_knowledge_space_expansion (M5.1 VERIFIED test): body
   asserted allow=True for isolated knowledge-space-only, contradicting its own name
   and the M5.3 authoritative isolated-mode spec. Corrected to DENY_ISOLATED_SCOPE_ESCAPE.
   M5.1 core contract unchanged.

## Verification results

- M5.3 focused suite (tests/unit/test_m5_cross_profile.py): 38 passed, 0 failed.
- M5.1 focused (tests/unit/test_m5_access_policy.py): passes (1 edge assertion corrected).
- M5.2 focused (tests/unit/test_m5_authorized_read.py): 35 passed.
- Combined M5.1+M5.2+M5.3: 73 passed.
- M3 regressions (query/fts/pagination): green.
- M4 regressions (test_m4_read): green; no M4 reader regression.
- Full canonical suite (clean isolated HOME): 983 passed, 3 skipped, 0 failed.
  (3 pre-existing capability skips, unchanged from M5.2 baseline.)
- Fresh OS-safe ad-hoc verifier: 21/21 checks passed covering all 19 required
  behaviors; verifier removed after run.

## Boundaries honored

NO persistent grants; NO migration v8 (zm_access_grants/zm_policy_audit absent);
NO audit persistence; NO WRITE authorization; NO M5.4; NO M6; TRUE READ-ONLY preserved
(mode=ro + query_only); no LLM/network; caller cannot self-authorize; fail-closed.

## Next

M5.4 — WRITE authorization, persistent grants, and migration v8.
