# M5.5 — Acceptance Evidence (VERIFIED)

**Milestone:** M5.5 — Authorization integration and linked-resource boundary hardening.
**Status:** VERIFIED (M5 overall remains IN PROGRESS — M5.6 not started).
**Starting commit:** 4a1b6c5
**Implementation commit:** a0919140af4dabb9cafa4d551be315af0846d3c7
**Tested commit:** a0919140af4dabb9cafa4d551be315af0846d3c7
**Evidence/state-binding commit:** <filled on commit>
**Schema version:** 8 (unchanged; NO migration v9)
**Working tree:** clean

---

## Objective

Systematically harden every existing linked-resource and composed-read path so
authorization cannot be bypassed through references.

**Core invariant:** AUTHORIZED SOURCE does NOT imply AUTHORIZED TARGET.

Every linked lookup (relation traversal, parent/child, source_event, supersession,
verification/artifact links) must independently remain inside the effective
authorized scope.

---

## What was delivered (M5.5 scope only)

- **src/access/linked.py** — linked-authorization helpers (derived, TRUE READ-ONLY):
  - `view_in_scope` — per-target scope recheck across the requester's ordered
    EffectiveReadScope (reuses `_scope_allows` / `_ordered_scopes` from M5.3).
  - `authorize_relation` — wraps M3 `get_related`/`get_incoming`/`get_outgoing`;
    prechecks the SOURCE event is itself in scope (you cannot traverse FROM an
    unauthorized source), then rechecks EVERY target; fail-closed
    (`_boundary_violation`) on any out-of-scope target — no content/ID/count leak.
  - `authorize_source_event` / `harden_m4_source_event` — rechecks an M4
    `source_event_id` resolution against scope; withholds the source EventView
    when unauthorized (no leak).
  - `authorize_m4_link` — resolves M4 linked verification/artifact by
    project + resource_type (no link authorizes a resource type not granted).
  - `authorize_supersession_link` — historical chains obey current scope.
- **authorized_read.py** — facade exposure of linked paths:
  - `get_related` / `get_incoming` / `get_outgoing` / `get_parent` / `get_children`
    — all target-scope rechecked, fail-closed.
  - M4 `m4_*` source-event hardening: `include_source_event` content withheld when
    the source event is out of scope.
  - `m4_requirement_verifications` / `m4_requirement_artifacts` — link resolution
    scoped by project + resource_type (requirement link does not authorize
    verification/artifact).
- **authorized_write.py** — `authorize_linked_write` / `AuthorizedWriteService
  .authorize_linked_write`: a WRITE whose target is reached through a linked object
  independently resolves the target's WRITE grant (no transitive/indirect mutation
  permission). READ grant cannot authorize linked WRITE.

## Authorization matrix coverage

| Dimension | Behavior | Tested |
|---|---|---|
| Profile (A→B) | denied without grant; allowed with exact READ grant for B | ✓ |
| Project (B/P→B/Q) | grant for B/P never exposes B/Q | ✓ |
| Knowledge-space | link in K2 not returned via K1/same profile | ✓ (scope recheck) |
| Global/isolation | global source cannot bridge protected profile; isolated_mode stays closed | ✓ |
| Relation type | relation type irrelevant to auth; target scope governs | ✓ |
| Parent/child | authorized parent→unauthorized child denied; child→parent denied | ✓ |
| source_event | M4 authorized + M3 source unauthorized → withheld; existence not leaked | ✓ |
| Supersession | historical predecessor/successor must independently authorize | ✓ |
| Verification | link cannot bypass; verified status ≠ global readability | ✓ |
| Artifact | safe reference ≠ authorization; resource-type gated | ✓ |
| Resource types | requirements grant cannot expose decisions/artifacts | ✓ |
| Grant state | revoked/superseded/deleted/conflicted deny; active allows exact | ✓ |
| Linked WRITE | requires independent exact WRITE authorization; denied never invokes writer | ✓ |
| Grant admin | resource links / WRITE grants cannot reach GrantAdminService | ✓ |
| Denial safety | no target existence/ID/count/lifecycle/snippet/secret leak; no raw SQLite errors | ✓ |

## Secret safety

Synthetic secrets (`SK-M5L-DONTLEAK-7a1b2c3d`) placed in unauthorized linked
targets (b1 PR2 content, b2 PR2/Q content). Proven absent from: direct results,
relation results, source-event resolution, verification/artifact metadata, errors,
and cursors. Verifier never prints the secret.

## TRUE READ-ONLY proof

Linked authorization performs only SELECTs. Verified: no migration, projector,
lifecycle writer, grant administration, or canonical append is invoked. JSONL
canonical hash unchanged before/after linked authorization.

## Determinism

Same (database + policy state + AccessRequest + query) → same AccessDecision,
EffectiveReadScope, linked results, ordering, cursor, and denial reason. No LLM,
no network.

## Regression gates (all green)

- M5.1 focused: 50 passed
- M5.2 focused: 35 passed
- M5.3 focused: 38 passed
- M5.4 focused: 70 passed
- M5.5 focused: **35 passed** (tests/unit/test_m5_linked.py)
- Combined M5.1–M5.5: **228 passed**
- M3 query / relations / pagination: green
- M4 read / schema / verification-artifact: green
- M5.4 migration+grant regressions: green
- Full canonical under clean isolated HOME: **1088 passed, 3 skipped, 0 failed**
- Fresh OS-safe ad-hoc verifier: **23/23 PASS** (run, then removed)

## Files changed

- `src/access/linked.py` (NEW)
- `src/access/authorized_read.py` (MODIFIED: relation/parent/child facade + source-event hardening + M4 link resolution)
- `src/access/authorized_write.py` (MODIFIED: `authorize_linked_write`)
- `tests/unit/test_m5_linked.py` (NEW: 35 focused boundary-matrix tests)

## Boundaries respected

- NO schema v9; migration v8 untouched.
- NO redesign of M3/M4.
- NO semantic ranking, context injection, final rebuild/performance acceptance.
- NO new authentication.
- NO M5.6 / M6 behavior.
- JSONL canonical and append-only; SQLite zm_access_grants / zm_policy_audit derived.

## Acceptance criteria

M5.5 is VERIFIED because:
- M5.1–M5.4 remain VERIFIED;
- every linked target is independently scope-checked;
- relations / parent-child / source_event / supersession / verification / artifacts
  cannot grant authorization;
- resource-type and profile/project/space boundaries survive traversal;
- global cannot bridge protected scope; isolated mode survives traversal;
- revoked/superseded/conflicted/deleted grants do not authorize;
- linked WRITE requires independent exact WRITE authorization;
- grant administration remains unreachable from normal policy path;
- denied targets leak no protected existence;
- TRUE READ-ONLY preserved; schema remains v8;
- canonical suite 0 failed; working tree clean.

M5 overall: IN PROGRESS
Next: M5.6 — Policy rebuild, audit, security/performance, and final M5 acceptance
