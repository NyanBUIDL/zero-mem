# M5 — Profile, project, knowledge-space access policy and isolation

**Plan status:** APPROVED — READY FOR IMPLEMENTATION (grant-admin authority resolved via trusted control plane; M5.4 may proceed)
**Authority:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` (master spec); `AGENTS.md`, `IDEA.md`, `ARCHITECTURE.md` (derived).
**Reconciled starting state:** M0–M4 all VERIFIED; HEAD `9153372`; schema v7; working tree clean; next incomplete milestone = M5; M5 not started; final canonical 860 passed, 3 skipped, 0 failed.
**Deliverable:** This plan only. No product code, tests, `project-state.yaml`, `implementation-plan.json`, or M0–M4 evidence are modified by this document.

---

## 1. Phase 1 reconciliation result

| Check | Result |
|---|---|
| M4 fully VERIFIED | ✅ (M4.1–M4.7 VERIFIED; final canonical 860/3/0) |
| Schema v7 | ✅ (`CURRENT_SCHEMA_VERSION == 7`; six M4 tables carry `project_id`, `profile_id`, `lifecycle_status`) |
| HEAD matches final M4 state | ✅ `9153372` |
| Next incomplete milestone = M5 | ✅ |
| M5 not started | ✅ (no M5 code, no M5 plan existed before this file) |
| No M6 behavior | ✅ |
| Working tree clean | ✅ (only this plan file added) |

No conflict → planning proceeds.

---

## 2. Authoritative access model (reconciled from spec + derived docs)

The master spec's intent is captured verbatim in the derived architecture and is the basis for M5:

- **AGENTS.md:** "Reads are global by default but **profile-first** and evidence-bounded; isolated/source-restricted modes must not leak scope." and "**Cross-profile writes require explicit authorization** and review/verification gates."
- **IDEA.md §4.8:** "Allow **global read access by default** with profile-first ranking." §4.9: "**Restrict cross-profile writes unless explicitly authorized.**"
- **ARCHITECTURE.md §6:** default profile `general-assistant` with **global read access, profile-first ranking, global fallback, bounded evidence, and no implicit cross-profile writes**. Supported access modes: `profile_first`, `explicit_union`, `isolated`, `global`, `source_restricted`.
- **ADR-M1-006:** `profile_id` and `project_id` resolve **only** from explicit value (`HERMES_PROFILE_ID` / `HERMES_PROJECT_ID` / caller-supplied) or `null`/`unassigned`. **Never inferred** from cwd, repo name, session text, prompt, or unrelated Hermes state.

### Consequence: AUTHENTICATION is out of scope for M5
Hermes does **not** currently provide authenticated caller identity to the sidecar. M5 therefore defines a **policy contract** that consumes an explicit `requesting_profile_id` (or `null`) supplied by the caller/integration layer. M5 must **NOT** invent identity from profile name, project name, session text, cwd, or environment guesses. When `requesting_profile_id` is `null`, the caller is treated as **unbound/anonymous** and subject to the global-read-only default (below) — never promoted to a specific profile's private scope.

### Layer separation (must not blur)
| Layer | Owner | In M5? |
|---|---|---|
| AUTHENTICATION (who claims to be) | Caller / future Hermes auth | ❌ defined as explicit input only |
| AUTHORIZATION (what allowed) | **M5 policy** | ✅ |
| RETRIEVAL (fetch approved records) | M3/M4 read APIs | ❌ M5 only emits scope filters |
| RANKING (relevance order) | Later milestone | ❌ |
| CONTEXT INJECTION | Later milestone | ❌ |

M5 produces an **`AccessDecision`** (allow/deny + normalized allowed scopes + reason code). M3/M4 then query **only** those scopes. M5 never fetches rows and filters sensitive ones afterward as the primary defense.

---

## 3. Default-deny vs default-allow matrix

Legend: **A**=allow by default, **D**=deny by default, **G**=grant-required, **iso**=behavior under `isolated_mode=true`.

### READ matrix
| Cell | Default | Condition | Isolated mode |
|---|---|---|---|
| same profile | **A** | requesting==target profile | A (explicit local scope) |
| global/default | **A** | `include_global=true` (default true) | **D** unless global explicitly selected+authorized |
| different profile | **D** | requires explicit cross-profile read grant | D always |
| same project (other profile) | **D** | project membership ≠ profile access; requires explicit grant | D |
| different project | **D** | requires explicit project grant | D |
| explicitly requested knowledge space | **A** | space in authorized set | A if authorized |
| unrequested knowledge space | **D** | not in requested set | D |

### WRITE matrix
| Cell | Default | Condition | Isolated mode |
|---|---|---|---|
| same profile | **A** | requesting==target profile, same project | A (explicit local scope) |
| global | **D** | global is **read-default, write-restricted** | D |
| different profile | **D** | explicit cross-profile WRITE grant | D |
| same project (other profile) | **D** | explicit grant (project ≠ profile) | D |
| different project | **D** | explicit project write grant | D |
| knowledge space | **D** | explicit space write grant | D |

**Key fixed rules:**
1. **READ access ≠ WRITE access.** A granted read never implies write.
2. **global is READ-default, WRITE-restricted** by architecture (global readable memory ≠ globally writable memory).
3. **Relations never grant access.** A→B via relation does not expose B.
4. **Project membership never grants profile access**, and vice-versa.
5. **Isolated mode wins over implicit global fallback** (precedence §8).

---

## 4. Policy input contract (`AccessRequest`)

Typed, deterministic, no unverifiable fields:

```
AccessRequest:
  operation:            "READ" | "WRITE"          # required
  requesting_profile_id: str | None               # explicit or None (unbound)
  target_profile_ids:   list[str] | None          # None => derive from op
  project_ids:          list[str] | None
  session_id:           str | None                # context only; not auth
  knowledge_space_ids:  list[str] | None
  isolated_mode:        bool          = False
  include_global:       bool | None   = None      # None => policy default (True)
  resource_type:        str | None     # charter|requirement|decision|state|
                                        # verification|artifact|event|trace|...
  resource_id:          str | None
  explicit_grants:      list[GrantRef] | None  # caller-supplied grant IDs (optional)
```

Only fields justified by the spec are present. **No** `cwd`, `env_guess`, `secret_token`, or `relevance_score` fields.

---

## 5. Policy result contract (`AccessDecision`)

```
AccessDecision:
  allow:            bool
  normalized_scope:                       # non-secret, query-ready, NEVER mutated by relations
    profiles:        list[str]            # explicit allowed profile IDs ("global" NOT used as a profile id)
    projects:        list[str]            # explicit allowed project IDs
    knowledge_spaces: list[str]          # explicit allowed knowledge-space IDs
    include_global:   bool                # global/default READ permission granted?
    operation:        "READ" | "WRITE"   # the operation this scope authorizes
    resource_types:   list[str] | None   # None = all; else restricted to these
    isolated:         bool
  denied_scopes:  list[str]
  reason_code:    str                     # fixed enum (§7)
  grant_refs:     list[str]              # safe IDs only, when used
  audit:
    decision_id:  str
    operation:    str
    requester:    str | "unbound"
    target_scope: str                     # normalized, no secrets
    allow:        bool
    reason_code:  str
    timestamp:    str
    source_event_id: str | None
  # NEVER includes: secrets, raw SQL, unrestricted local paths, raw policy internals
```

**AllowedScope non-expansion invariants (§4 contract):**
- A **project** permission adds only that project to `projects`; it does **NOT** add any
  profile to `profiles` (a project may span multiple profiles; membership is not transitive to profile access).
- A **profile** permission adds only that profile to `profiles`; it does **NOT** implicitly
  add all of that profile's projects or knowledge spaces unless the authoritative policy
  explicitly grants them (default: profile-local read does not auto-include every project).
- **Relations NEVER expand** `normalized_scope`. Relation traversal results are filtered
  DOWN to the already-allowed scope; a relation to an out-of-scope entity is dropped, never
  used to widen the scope.
- `include_global` is set only by the global-READ rule (§8 rule 5) or an explicit global grant;
  it is **not** implied by any project/space/profile permission.

Reason codes (fixed vocabulary; do not invent):
`ALLOW_LOCAL_PROFILE_READ`, `ALLOW_GLOBAL_READ`, `ALLOW_EXPLICIT_CROSS_PROFILE_READ`,
`ALLOW_PROJECT_READ`, `ALLOW_KNOWLEDGE_SPACE_READ`, `ALLOW_LOCAL_WRITE`,
`ALLOW_EXPLICIT_CROSS_PROFILE_WRITE`, `ALLOW_EXPLICIT_CROSS_PROJECT_WRITE`,
`DENY_CROSS_PROFILE_WRITE`, `DENY_CROSS_PROJECT_WRITE`, `DENY_ISOLATED_SCOPE_ESCAPE`,
`DENY_UNKNOWN_PROFILE`, `DENY_UNKNOWN_PROJECT`, `DENY_UNAUTHORIZED_SPACE`,
`DENY_UNKNOWN_SPACE`, `DENY_UNAUTHORIZED_CROSS_PROFILE_READ`, `DENY_INVALID_REQUEST`,
`DENY_REVOKED_GRANT`, `DENY_POLICY_CONFLICT`.

---

## 6. Profile-first read normalization (authorization-before-retrieval)

Conceptual order M5 normalizes a READ before M3/M4 execution:

1. **requesting profile** (caller identity; may be `unbound`)
2. **explicitly requested project(s)**
3. **explicitly requested knowledge space(s)**
4. **global/default space** if policy permits (`include_global` and not isolated-blocked)
5. **explicitly authorized cross-profile space(s)** (via grants)

Output = `normalized_scope` filters. M3/M4 query **only** those filters:
- M3: `query_events` gets `profile_id IN (...)`, `project_id IN (...)`; relations filtered to authorized endpoints; `get_event`/`get_trace` re-checked against scope.
- M4: `list_*`/`get_*` get `project_id IN (...)` and, where applicable, `profile_id IN (...)`; source-event resolution (M3) re-checked; artifact safe-reference allowed but **content access** gated separately (§10).

M5 must **not** open a writer/projector; it composes with the existing `ReadonlyStore` + reader APIs.

---

## 7. Read/write default semantics (resolved decisions)

1. **Same-profile READ** → ALLOW (profile-first). `ALLOW_LOCAL_PROFILE_READ`.
2. **Global READ** → ALLOW by default (`include_global=True`). `ALLOW_GLOBAL_READ`. No write.
3. **Isolated-mode precedence** → `isolated_mode=True` disables implicit global fallback AND implicit profile/project/space expansion. Explicitly selected authorized scope only. `isolated_mode` **wins** over `include_global` unless global is itself explicitly selected **and** authorized. Deterministic: `isolated=True AND include_global=True AND global not in explicit_grants → DENY_ISOLATED_SCOPE_ESCAPE`.
4. **Explicit cross-profile READ** → DENY unless an explicit cross-profile read grant exists. `ALLOW_EXPLICIT_CROSS_PROFILE_READ` / `DENY_UNAUTHORIZED_CROSS_PROFILE_READ`.
5. **Cross-profile WRITE** → **DENY by default**. `DENY_CROSS_PROFILE_WRITE` / `ALLOW_EXPLICIT_CROSS_PROFILE_WRITE` only with explicit WRITE grant.
6. **Explicit persistent grants** → **YES required** (§11). Minimal deterministic model; no delegation/expiry unless spec defines it (it does not → omit expiry).
7. **Project boundaries** → project-local read/write = profile-local when profile owns project; cross-project read/write = DENY unless explicit project grant.
8. **Knowledge-space boundaries** → membership explicit; shared profile ≠ every space visible; relation ≠ space permission.
9–18 → see §8 precedence, §9 conflict, §12 missing identity, §13 lifecycle, §14 schema, §15 audit.

---

## 8. Policy precedence (ONE unambiguous table)

Evaluated top-down; first match wins. **No "explicit deny" record type exists in M5**
(see §8b explicit-deny model) — revocation is expressed via the generic `state`
field, not a deny record, so the precedence below contains no deny-record rule.

| # | Rule | Result |
|---|---|---|
| 1 | Request structurally invalid (missing operation / bad enum) | `DENY_INVALID_REQUEST` |
| 2 | `isolated_mode=True` and target scope ⊄ explicitly selected authorized scope | `DENY_ISOLATED_SCOPE_ESCAPE` |
| 3 | Matching grant exists with `state='revoked'` or `lifecycle_status IN (deleted)` | `DENY_REVOKED_GRANT` (grant is non-authorizing; see §8b) |
| 4 | **Same-profile** rule (requesting_profile == target profile, same project when project scoping applies) matches → ALLOW read or write | `ALLOW_LOCAL_PROFILE_READ` / `ALLOW_LOCAL_WRITE` |
| 5 | **Global READ** permitted (`include_global=True` and not isolated-blocked) → ALLOW read only | `ALLOW_GLOBAL_READ` |
| 6 | Explicit narrow **grant** matches (active, state≠revoked, verification satisfied for WRITE) → ALLOW read or write in exactly its target scope | `ALLOW_EXPLICIT_*` |
| 7 | **Project permission NEVER adds a profile**; a profile permission NEVER adds projects/spaces implicitly (§4 AllowedScope) | (constraint, not a rule) |
| 8 | Otherwise | `DENY_*` (fail closed) |

**Critical: rule 4 is profile-local only.** A profile that shares a project with
another profile does NOT gain access to that other profile's scope. "same-project"
is never a standalone allow rule. The only path from profile A to profile B's
scope is an explicit cross-profile grant (rule 6).

### §8a. Same-profile / cross-profile evaluation order

`requesting_profile=A`, `target_profile=B`, `project=P`, both A and B associated
with P:

- **Without cross-profile grant:**
  - READ targeting B's scope → rule 4 fails (A≠B) → rule 5 (global) N/A to B's
    private scope → rule 6 fails (no grant) → rule 8 → **DENY**
    (`DENY_UNAUTHORIZED_CROSS_PROFILE_READ`).
  - WRITE targeting B's scope → same path → **DENY** (`DENY_CROSS_PROFILE_WRITE`).
  - READ/WRITE targeting A's own scope within P → rule 4 → **ALLOW**.
- **With explicit cross-profile READ grant** (subject=A, op=READ, target=B):
  - READ targeting B → rule 6 → **ALLOW READ only** (`ALLOW_EXPLICIT_CROSS_PROFILE_READ`).
  - WRITE targeting B → grant op=READ ≠ WRITE → rule 6 fails for WRITE → rule 8 → **DENY WRITE** (`DENY_CROSS_PROFILE_WRITE`). READ grant does NOT imply WRITE.
- **With explicit cross-profile WRITE grant** (subject=A, op=WRITE, target=B):
  - WRITE targeting B → rule 6 → **ALLOW WRITE** (`ALLOW_EXPLICIT_CROSS_PROFILE_WRITE`).
  - READ targeting B → READ still requires its own match; if no READ grant, falls to
    rule 8 → **DENY READ** unless global/read-local covers it. WRITE grant does NOT imply READ.

### §8b. Explicit-deny model

M5 defines **allow grants only**. There is **no persistent explicit-deny record
type**. Revocation/non-authorization is expressed by:
- `state = 'revoked'` on an otherwise-active grant (domain state, never a lifecycle value), or
- `lifecycle_status = 'deleted'` / `'archived'` (authoritative enum).

`revoked` is a **domain state**, NOT an event and NOT a lifecycle_status. A denied
outcome is the *result* of policy evaluation (a `DENY_*` reason code), not a stored
record. "suspended" is unsupported and is not modeled. A revoked grant does NOT
deny *other* valid grants — it merely becomes non-authorizing for itself (rule 3).

### §8c. Policy-conflict model

Without deny records, a "conflict" is narrowly: two or more **active, non-revoked**
grants match the same `(subject_profile, operation, target)` but resolve to
**contradictory normalized scopes with no deterministic tie-break** (e.g. one
grants `target_id='B'`, another grants `target_id='*'` while a third is
`state='revoked'` on `'B'` — the revocation must win deterministically per §8b,
so this is NOT a conflict; only genuine equal-specificity contradiction is). When
such irreducible ambiguity occurs → `DENY_POLICY_CONFLICT` and surface it. No
timestamp-based resolution. Fail closed only for real deterministic ambiguity.

---

## 9. Unknown / missing identity & fail-closed

- `requesting_profile_id is None` → **unbound** caller. Gets **global READ-default only** (architecture §6 global read access by default) when `include_global` permits; **never** inferred to any specific profile; **all cross-scope WRITE denied**.
- Target profile unknown (not in canonical scope registry / not resolvable) → `DENY_UNKNOWN_PROFILE`.
- Project unknown → `DENY_UNKNOWN_PROJECT`.
- Knowledge space unknown/unrequested → `DENY_UNKNOWN_SPACE` / `DENY_UNAUTHORIZED_SPACE`.
- Grant reference invalid (not found / revoked) → `DENY_REVOKED_GRANT`.
- Security-sensitive ambiguity → **fail closed** (deny). Ordinary profile-local/global reads that the policy explicitly allows are NOT blocked.

---

## 10. Boundary rules (relations / source-event / artifact)

- **Relation does not grant authorization.** Authorized event A → relation → unauthorized event B must NOT expose B. Relation traversal results are re-checked against `normalized_scope`; endpoints outside scope are dropped. `DENY_*` if traversal would leak.
- **Source-event composition boundary.** An authorized M4 object referencing `source_event_id` does not authorize the referenced M3 event if its scope is unauthorized. M5 re-applies policy on the resolved source event. Provenance references never bypass profile/project boundaries.
- **Parent/child, supersession, verification linkage, artifact linkage** — same rule: every linked endpoint is independently policy-checked; no link implies permission.
- **Artifact boundary.** Metadata (safe_reference, artifact_id, type) follows policy like any resource. **Artifact content access is NOT automatically granted by metadata access.** M5 defines only the authorization contract for this milestone; arbitrary file-content access belongs to a later milestone. `safe_reference != permission`.

---

## 11. Explicit grant model — canonical JSONL + derived SQLite

### 11.1 Canonical source (append-only JSONL) — the source of truth

Cross-profile access must be auditable and deterministic across restarts, so the
**canonical** record is a structured access-grant event appended to the canonical
JSONL stream (same store as other canonical events). A SQLite row is **never**
canonical.

Canonical grant event contract (`m4`-style typed operation, consistent with M4):

```
event_type: "access_grant"
m4:
  domain: "access_grant"
  identity: <grant_id>
  op: "create" | "supersede" | "revoke"   # revoke sets state='revoked' on active
  grant_id:        str                      # stable primary identity
  subject_profile: str                      # requesting_profile_id the grant applies to
  operation:       "READ" | "WRITE"
  target_type:     "profile" | "project" | "knowledge_space" | "global"
  target_id:       str                      # profile/project/space id, or "*" for global
  resource_types:  list[str] | None        # None = all
  state:           str | None              # generic domain state, e.g. "revoked"
  lifecycle_status:"raw"|"observed"|"candidate"|"confirmed"|"active"|"superseded"|"conflicted"|"archived"|"deleted"
  supersedes:      str | None              # explicit supersession only
  verification_ref:str | None              # required for WRITE grants (see §11.3)
  source_event_id: str                      # provenance
  created_at:      str
provenance (event top-level): event_id, trace_id, session_id, profile_id, created_at
```

Replaying these canonical events reproduces the derived grant projection exactly
(incremental == rebuild). No SQLite row is ever treated as canonical.

### 11.2 Derived projection (`zm_access_grants`, SQLite, disposable/rebuildable)

`zm_access_grants` is a **derived** table, rebuilt from the canonical grant events.
It is NOT the source of truth. Its columns mirror the canonical event:
`grant_id PK, subject_profile, operation, target_type, target_id, resource_types,
state, lifecycle_status, supersedes, verification_ref, source_event_id, created_at`.
`lifecycle_status` CHECK uses **only** the authoritative closed enum
(`raw/observed/candidate/confirmed/active/superseded/conflicted/archived/deleted`).
`state` is a free-form generic column (holds `"revoked"`); it is **not** a lifecycle value.

### 11.3 Grant verification predicate (WRITE only)

- `verification_ref` is **required only for WRITE grants** (per AGENTS.md
  "review/verification gates" for cross-profile writes). For READ grants it is
  optional metadata.
- Mere presence of `verification_ref` does **NOT** imply verification.
- When `operation='WRITE'`, the grant authorizes ONLY if the deterministic predicate
  holds:

  ```
  grant.lifecycle_status == 'active'
  AND grant.state != 'revoked'
  AND grant.verification_ref IS NOT NULL
  AND verification_record(verification_ref).status == 'verified'
  ```

  (No LLM evaluation; `verification_record` is the M4 verification lookup, read-only.)
  If the predicate fails, the WRITE grant is treated as non-authorizing → `DENY_*`.

### 11.4 Revocation / lifecycle (no new enum)

- `revoked` is a **domain state** set on the canonical event (`state='revoked'`),
  never a `lifecycle_status`. The approved deterministic representation for a
  withdrawn grant is `state='revoked'` **with** `lifecycle_status` retained as
  `active` (so the row/event stays visible for audit) — OR, if the grant is to be
  fully retired, `lifecycle_status='archived'`. Both make the grant non-authorizing
  (§8 rule 3). Choose `state='revoked', lifecycle_status='active'` as the primary
  revocation representation (audit-preserving); `archived`/`deleted` are also valid
  terminal states.
- Supersession: a newer grant with `supersedes=<old_grant_id>` and
  `lifecycle_status='superseded'` on the old row is the explicit replacement path.
- Revoked/deleted grants must NOT authorize new access (rule 3).

Grant provenance: every authorization that uses a grant identifies its `grant_id`
in `AccessDecision.grant_refs` (safe ID only).

### 11.5 Rebuild

Grants are canonical events; the derived `zm_access_grants` table is rebuilt like
other M4 state (incremental == rebuild). Deleting/dropping the SQLite table loses
nothing — replay of canonical grant events reproduces it.

---

### 11.6 Grant-administration authority — trusted control plane (M5.4 plan correction)

Grant administration is a **distinct trusted control-plane operation**, separated
from ordinary memory READ/WRITE policy. The authority to create / revoke /
supersede canonical `access_grant` events is NOT derived from any ordinary
memory permission.

**Two separate entry surfaces (conceptual):**

- **NORMAL POLICY SURFACE** (`AccessRequest`): READ / WRITE authorization only.
  It **cannot** administer grants. A normal `AccessRequest` is structurally unable
  to reach the grant-admin path.
- **TRUSTED GRANT-ADMIN SURFACE**: a trusted local/operator control-plane
  entrypoint. It validates a structured `GrantAdminRequest`, appends the canonical
  `access_grant` event, and updates the derived projection. This surface is NOT
  reachable by passing fields inside a normal `AccessRequest`.

**No bootstrap grant recursion.** M5 does NOT introduce:

- a `grant_admin` role;
- a `grant_admin` access grant;
- any recursive "grant allowing creation of grants";
- profile-owner / project-owner inference for grant authority.

Grant administration uses a trusted control-plane boundary, not another grant
type. This avoids the bootstrap question of who grants the first
grant-administration grant.

**These caller-controlled inputs MUST NOT confer authority** (no privilege
escalation):

- `is_admin=true`
- `trusted=true`
- `grant_admin=true`
- `allow_grant_creation=true`
- `verified=true`

or any equivalent caller-controlled boolean. Authority comes from *entering
through the trusted control-plane API boundary*, never from request-payload
claims.

**`GrantAdminRequest` contract (separate typed request for the trusted path):**

```
GrantAdminRequest:
  action:           CREATE | REVOKE | SUPERSEDE
  grant_id:         str                      # stable explicit identity
  subject_profile:  str
  operation:        "READ" | "WRITE"
  target_type:      "profile" | "project" | "knowledge_space" | "global"
  target_id:        str
  resource_types:   list[str] | None
  verification_ref: str | None               # required for WRITE CREATE
  supersedes:       str | None               # required for SUPERSEDE
  provenance / source event fields
```

No caller-controlled `trusted` / `admin` boolean is part of the contract.

**Authority rules:**

- **CREATE** (trusted control plane only): may append a canonical structured
  `access_grant` event only after contract validation, stable explicit `grant_id`,
  valid operation, valid target, valid resource types, lifecycle/domain-state
  validation, and (for WRITE) the §11.3 verification predicate. Grant creation does
  NOT require the target subject to already possess grant-administration authority
  — the trust comes from the control-plane entrypoint.
- **REVOKE** (trusted control plane only): only the grant-admin entrypoint may
  create a canonical revoke event. Normal READ/WRITE requests cannot revoke grants.
  Revocation remains `state = "revoked"`, never `lifecycle_status = "revoked"`.
  Canonical history is preserved (no physical deletion).
- **SUPERSEDE** (trusted control plane only): requires an existing source grant,
  an explicit replacement, no self-supersession, and no invalid cycle; the
  projection update is atomic. Normal resource WRITE permission cannot supersede
  grants.

**No privilege inheritance from WRITE.** A valid WRITE grant does NOT imply
grant-administration authority. A same-profile WRITE does NOT imply it. Project
ownership/membership does NOT imply it. Cross-profile permissions do NOT imply it.

**Authentication boundary (trust-boundary assumption).** M5 does NOT implement
authentication. Therefore M5 does NOT cryptographically prove the human/operator
identity. The contract is: the hosting/control-plane layer decides *who* may
invoke the trusted grant-administration entrypoint; M5 guarantees that ordinary
agent policy paths cannot reach that entrypoint. Recorded explicitly as a
trust-boundary assumption. Future authentication/identity hardening may strengthen
this boundary without changing grant semantics.

**Canonical authority.** The trusted control-plane operation appends a canonical
JSONL `access_grant` event; SQLite remains only the derived `zm_access_grants`
projection. Control-plane configuration and SQLite are NOT canonical.

**Audit.** A trusted grant-administration action should produce safe audit
provenance per the §15 audit plan (canonical `policy_decision` event where
applicable). Do not log secrets, raw payloads, or unrestricted paths. Do not
require every ordinary memory READ to mutate its read store.

**Required security properties (must be guaranteed by the corrected plan):**

1. normal `AccessRequest` cannot create a grant;
2. normal `AccessRequest` cannot revoke a grant;
3. normal `AccessRequest` cannot supersede a grant;
4. same-profile WRITE cannot administer grants;
5. a valid WRITE grant cannot administer grants;
6. a cross-profile WRITE grant cannot administer grants;
7. a caller-controlled admin/trusted boolean cannot escalate privileges;
8. relations cannot confer grant-admin authority;
9. project membership cannot confer grant-admin authority;
10. the trusted control-plane path is separate from the normal policy path.

## 12. Write-time canonical behavior

- Unauthorized write → **deny before canonical mutation**. No successful domain event appended.
- No JSONL non-canonical behavior; no silent rewrite.
- When an authorization decision is **persisted** (per §15.2), it is appended as a **canonical `policy_decision` event** to the canonical JSONL stream — NOT written into the M3/M4 store being authorized. M5 never fabricates domain state.
- Never fabricate domain state to "satisfy" a denied write.
- The derived `zm_policy_audit` row (if any) is produced by replaying canonical
  `policy_decision` events, never as the primary record.

---

## 13. Lifecycle / archived-deleted scope

- `archived` profile/project/space → readable only if an explicit grant or global-read covers it AND not isolated-excluded; not auto-visible.
- `deleted` profile/project/space → **excluded** from normal reads (consistent with M3 `deleted` exclusion); deleted grants do not authorize.
- No access invented from raw historical relations to deleted/archived scopes.

---

## 14. Schema impact & proposed version (v8)

Inspected v7: `zm_scopes` (generic scope registry, not a profile→space authority), M4
tables carry `profile_id` (present, not yet a scoping key). No existing table is an
authorization store. **Proposed: migration v8** adds two **derived, rebuildable**
tables. Both have canonical JSONL sources (§11.1 grant events; §15.1 audit events).

### 14.1 `zm_access_grants` (derived from canonical grant events)

- **canonical source event type:** `access_grant` (§11.1)
- **primary identity:** `grant_id` (TEXT PRIMARY KEY)
- **domain state:** `state` TEXT (generic; holds `"revoked"`; NOT a lifecycle value)
- **lifecycle_status:** TEXT CHECK restricted to the **authoritative closed enum only**
  (`raw/observed/candidate/confirmed/active/superseded/conflicted/archived/deleted`)
- **provenance:** `source_event_id`, `created_at`, top-level event provenance
- **indexes:** `idx_grants_subject_op (subject_profile, operation)`;
  `idx_grants_target (target_type, target_id)`
- **uniqueness:** PK only (multiple active grants allowed; precedence §8)
- **supersession:** `supersedes` TEXT → `zm_access_grants(grant_id)` self-FK; old row
  set `lifecycle_status='superseded'`
- **downgrade:** `down()` drops both v8 tables/indexes (returns to v7; M0–M3/M4 tables
  untouched)
- **rebuild:** full replay of canonical `access_grant` events (incremental == rebuild)

```sql
CREATE TABLE zm_access_grants (
  grant_id         TEXT PRIMARY KEY,
  subject_profile  TEXT NOT NULL,
  operation        TEXT NOT NULL CHECK (operation IN ('READ','WRITE')),
  target_type      TEXT NOT NULL CHECK (target_type IN ('profile','project','knowledge_space','global')),
  target_id        TEXT NOT NULL,
  resource_types   TEXT,                -- JSON list or NULL=all
  state            TEXT,                -- generic domain state, e.g. 'revoked'
  lifecycle_status TEXT NOT NULL DEFAULT 'candidate'
                      CHECK (lifecycle_status IN ('raw','observed','candidate','confirmed',
                             'active','superseded','conflicted','archived','deleted')),
  supersedes       TEXT,
  verification_ref TEXT,
  source_event_id  TEXT,
  created_at       TEXT NOT NULL,
  FOREIGN KEY (supersedes) REFERENCES zm_access_grants(grant_id)
);
```

### 14.2 `zm_policy_audit` (derived from canonical policy-decision/audit events)

- **canonical source event type:** `policy_decision` (§15.1) — persisted ONLY for the
  subset defined in §15.2
- **primary identity:** `decision_id` (TEXT PRIMARY KEY)
- **domain state:** n/a (decision is immutable once recorded)
- **lifecycle_status:** n/a (audit records are append-only; not lifecycled)
- **provenance:** `source_event_id` (the canonical `policy_decision` event id)
- **indexes:** `idx_audit_requester (requester, timestamp)`
- **uniqueness:** PK only
- **supersession:** none
- **downgrade:** `down()` drops the table (returns to v7)
- **rebuild:** full replay of persisted canonical `policy_decision` events

```sql
CREATE TABLE zm_policy_audit (
  decision_id    TEXT PRIMARY KEY,
  operation      TEXT NOT NULL,
  requester      TEXT NOT NULL,         -- profile id or 'unbound'
  target_scope   TEXT NOT NULL,         -- normalized, no secrets
  allow          INTEGER NOT NULL,      -- 0/1
  reason_code    TEXT NOT NULL,
  grant_refs     TEXT,                 -- JSON list of safe grant ids or NULL
  timestamp      TEXT NOT NULL,
  source_event_id TEXT
);
```

If implementation review finds grants can be satisfied by extending `zm_scopes`
instead, v8 MAY be narrowed — but the audit table remains. Decision finalized at
M5.4 implementation, not here. **No duplication** of existing `zm_scopes`/profile
metadata.

---

## 15. Auditability & read-side-effect isolation

### 15.1 Canonical audit event (`policy_decision`)

`AccessDecision.audit` is **NOT** written only to SQLite. To survive SQLite rebuild,
the persisted decisions are emitted as **canonical `policy_decision` JSONL events**
(source of truth); `zm_policy_audit` is their derived projection.

```
event_type: "policy_decision"
m4:
  domain: "policy_decision"
  identity: <decision_id>
  decision_id:      str
  operation:        "READ" | "WRITE"
  requester:        str | "unbound"
  target_scope:     str            # normalized, no secrets
  allow:            bool
  reason_code:      str            # fixed enum
  grant_refs:      list[str] | None
  timestamp:        str
  source_event_id:  str | None
provenance: event_id, trace_id, session_id, profile_id, created_at
```

### 15.2 Audit persistence policy (which decisions are canonical)

Not every read decision is persisted canonically (volume). Deterministic rule:

- **Persisted canonically (→ `policy_decision` event → `zm_policy_audit`):**
  - Every **DENY** decision (security-critical; must be reconstructable).
  - Every decision that **used an explicit grant** (allow or deny via grant) — for auditability of cross-scope access.
  - Every **`DENY_POLICY_CONFLICT`** decision.
- **Ephemeral (NOT persisted canonically):** ordinary **ALLOW** local-profile / global
  READ decisions with no explicit grant and no conflict. These remain in the in-process
  `AccessDecision` result only.
- This keeps the canonical audit stream bounded while guaranteeing every
  security-relevant or grant-using decision is reconstructable via SQLite rebuild.

### 15.3 Read side-effect isolation

Authorization is **strictly separated** from data retrieval:

- Evaluating `AccessRequest` produces an `AccessDecision` (+ optional canonical
  `policy_decision` event per §15.2). The **M3/M4 stores being queried remain
  `ReadonlyStore` (mode=ro + `PRAGMA query_only=ON`)** — never mutated.
- The canonical `policy_decision` event, when persisted, is appended to the **canonical
  JSONL stream** (the same append-only store as other events), **not** into the M3/M4
  SQLite being read. M5 never opens a writer against the queried M3/M4 database.
- Therefore routine `query memory` does **not** mutate the memory being queried. Audit
  is a side-channel: a separate canonical event sink + derived `zm_policy_audit`
  projection. If a deployment requires zero write even to the canonical audit stream
  for routine reads, only the ephemeral class (§15.2) is used and no `policy_decision`
  event is emitted for those reads.

Secrets, raw SQL, unrestricted paths, and raw policy internals are NEVER logged.

---

## 16. Determinism & zero-token

Same `AccessRequest` + same policy state (grants) ⇒ same `AccessDecision`. No LLM call, no network lookup, no semantic similarity, no cwd inference, no wall-clock dependence (expiry omitted). Routine authorization = **zero LLM calls**.

---

## 17. Proposed M5 increment structure

Smallest independently verifiable increments (preferred over a monolith):

- **M5.1 — Policy contracts + authoritative access matrix.** `AccessRequest`, `AccessDecision`, reason-code enum, `evaluate(request, policy_state)` core with the §8 precedence, NO persistence yet (policy_state from in-memory grant list / canonical read). Files: `src/access/policy.py`, `src/access/contracts.py`. Tests: matrix unit tests (all cells), isolation, cross-profile deny, fail-closed. Acceptance: 100% matrix green; no M3/M4 regression.
- **M5.2 — Profile/project/knowledge-space READ authorization.** Wire `normalized_scope` into M3 `query_events`/`get_event`/`get_trace`/`list_*` and M4 reader filters. Same-profile + global-read + explicit space. Tests: authorized M3/M4 query returns identical rows to pre-M5 equivalent (compatibility). Acceptance: compatibility proof + negative tests.
- **M5.3 — Isolated mode + explicit cross-profile READ composition.** `isolated_mode` precedence; `explicit_union` of authorized cross-profile scopes via grants; relation/source-event/artifact boundary re-checks. Tests: isolated blocks implicit global/profile/space; explicit cross-profile read allowed only with grant. Acceptance: boundary tests pass.
- **M5.4 — WRITE authorization + explicit grants (v8).** `zm_access_grants` migration; canonical grant events; WRITE deny-by-default; cross-profile/project/space WRITE only via active grant + verification_ref; revocation/supersession. Files: `migrate_8.py`, `src/access/grants.py`. Tests: write denied by default; authorized write allowed; revoked grant blocks; no JSONL non-canonical mutation. Acceptance: write policy green + rebuild parity.
- **M5.5 — M3/M4 authorization integration + relation/artifact boundary checks.** Full integration; deny-before-retrieval enforced end-to-end; relation traversal, verification/artifact/source-event linkage re-checked. Tests: comprehensive negative authorization (every §"Security properties" case). Acceptance: integration green.
- **M5.6 — Rebuild / audit / security regression / performance / final acceptance.** Grant rebuild parity; `zm_policy_audit` populated; secret-leak checks; no-LLM/no-network guards; performance baseline; full canonical suite 0 failed; working tree clean; M6 not started. Acceptance: final M5 gate.

Each increment: objective, files, schema impact, policy rules, tests, acceptance criteria, rollback (revert commit + `down` migration), dependencies (M5.n depends on M5.n-1), explicit exclusions (no ranking, no context injection, no M6).

---

## 18. Required acceptance matrix (positive + negative; subset shown, full suite in M5.5/5.6)

| Scenario | Expected | Allowed normalized scope | Reason code | Test | Increm. |
|---|---|---|---|---|---|
| same profile + same project | ALLOW | profile=A, project=P | ALLOW_LOCAL_PROFILE_READ | test_same_profile_same_project | 5.2 |
| same-profile read | ALLOW | profile=P | ALLOW_LOCAL_PROFILE_READ | test_same_profile_read | 5.2 |
| global read (default) | ALLOW | global | ALLOW_GLOBAL_READ | test_global_read_default | 5.2 |
| global disabled | DENY (implicit) | — | DENY_ISOLATED_SCOPE_ESCAPE* | test_global_disabled | 5.2 |
| isolated local read | ALLOW | profile=P | ALLOW_LOCAL_PROFILE_READ | test_isolated_local_read | 5.3 |
| isolated blocks implicit global | DENY | — | DENY_ISOLATED_SCOPE_ESCAPE | test_isolated_blocks_global | 5.3 |
| isolated blocks implicit cross-profile | DENY | — | DENY_ISOLATED_SCOPE_ESCAPE | test_isolated_blocks_xprofile | 5.3 |
| **different profile + same project, no grant** | **DENY** | — | DENY_UNAUTHORIZED_CROSS_PROFILE_READ (read) / DENY_CROSS_PROFILE_WRITE (write) | test_diff_profile_same_project_no_grant | 5.2/5.4 |
| **different profile + same project + READ grant** | **ALLOW READ only** | profiles=[A,B] | ALLOW_EXPLICIT_CROSS_PROFILE_READ | test_diff_profile_same_project_read_grant | 5.3 |
| **different profile + same project + WRITE grant** | **ALLOW WRITE only** | profiles=[A,B] | ALLOW_EXPLICIT_CROSS_PROFILE_WRITE | test_diff_profile_same_project_write_grant | 5.4 |
| **READ grant does NOT imply WRITE** | DENY (write) | — | DENY_CROSS_PROFILE_WRITE | test_read_grant_not_write | 5.4 |
| **project relation does NOT imply profile permission** | DENY | — | DENY_UNAUTHORIZED_CROSS_PROFILE_READ | test_project_relation_not_profile_perm | 5.5 |
| explicit cross-profile read (grant) | ALLOW | profiles=[P,Q] | ALLOW_EXPLICIT_CROSS_PROFILE_READ | test_xprofile_read_grant | 5.3 |
| unauthorized cross-profile read | DENY | — | DENY_UNAUTHORIZED_CROSS_PROFILE_READ | test_xprofile_read_denied | 5.3 |
| cross-profile write (no grant) | DENY | — | DENY_CROSS_PROFILE_WRITE | test_xprofile_write_denied | 5.4 |
| authorized cross-profile write | ALLOW | profiles=[P,Q] | ALLOW_EXPLICIT_CROSS_PROFILE_WRITE | test_xprofile_write_grant | 5.4 |
| same-project ≠ cross-profile write | DENY | — | DENY_CROSS_PROFILE_WRITE | test_project_not_xprofile_write | 5.4 |
| relation does not bypass | DENY (B dropped) | scope only | DENY_* | test_relation_boundary | 5.5 |
| supersession link no bypass | DENY | — | DENY_* | test_supersession_boundary | 5.5 |
| verification link no bypass | DENY | — | DENY_* | test_verification_boundary | 5.5 |
| artifact link no bypass | DENY | — | DENY_* | test_artifact_boundary | 5.5 |
| source_event no bypass | DENY | — | DENY_* | test_source_event_boundary | 5.5 |
| cross-project isolation | DENY | — | DENY_UNAUTHORIZED_PROJECT | test_cross_project_isolation | 5.2/5.5 |
| knowledge-space isolation | DENY (unrequested) | — | DENY_UNAUTHORIZED_SPACE | test_space_isolation | 5.2 |
| unknown profile | DENY | — | DENY_UNKNOWN_PROFILE | test_unknown_profile | 5.2 |
| unknown project | DENY | — | DENY_UNKNOWN_PROJECT | test_unknown_project | 5.2 |
| unknown space | DENY | — | DENY_UNKNOWN_SPACE | test_unknown_space | 5.2 |
| **revoked grant does NOT authorize** (state='revoked') | DENY | — | DENY_REVOKED_GRANT | test_revoked_grant | 5.4 |
| **SQLite grant projection rebuilt from canonical grant events** | reproduces | — | — | test_grant_rebuild_parity | 5.6 |
| **policy audit projection rebuilt from canonical policy_decision events** | reproduces | — | — | test_audit_rebuild_parity | 5.6 |
| conflicting grant policy | DENY | — | DENY_POLICY_CONFLICT | test_grant_conflict | 5.4 |
| read ≠ write | DENY (write) | — | DENY_CROSS_PROFILE_WRITE | test_read_not_write | 5.4 |
| deleted scope excluded | DENY | — | DENY_UNKNOWN_* | test_deleted_scope | 5.5 |
| safe reason codes | ALLOW/DENY | — | fixed enum | test_reason_codes | 5.1 |
| no secret leakage | pass | — | — | test_no_secret_leak | 5.6 |
| deterministic repeat | same | — | — | test_deterministic | 5.1 |
| no LLM/network | pass | — | — | test_no_llm_network | 5.6 |
| no real ~/.hermes writes | pass | — | — | test_no_real_home_writes | 5.6 |

(*`DENY_ISOLATED_SCOPE_ESCAPE` reused for global-disabled-under-isolation; if a distinct `DENY_GLOBAL_DISABLED` code is preferred, add at implementation.)

---

## 19. Compatibility requirement

For every authorized query, M5-wrapped M3/M4 result MUST equal the equivalent pre-M5 query result (same rows, same order) — the only difference is the enforced boundary. Tests in M5.2/5.5 prove this; policy enforcement is at the boundary, not via post-hoc row stripping.

---

## 20. Unresolved decisions (NONE blocking)

All 18 required M5 plan decisions (§"Required M5 plan decisions" in directive) are resolved above:
1–6 default read/global/isolated/cross-profile-read/cross-profile-write/grants ✅
7–8 project & knowledge-space boundaries ✅
9–11 relation / artifact / source-event boundaries ✅
12 read≠write ✅
13 deny/allow precedence ✅ (§8)
14 policy-conflict behavior ✅ (DENY_POLICY_CONFLICT, no timestamp resolution)
15 missing requester ✅ (unbound→global-read-only, fail closed on cross-scope)
16 archived/deleted scope ✅ (§13)
17 v8 required ✅ (proposed, §14)
18 audit model ✅ (§15)

**No NEEDS DECISION / BLOCKED items.** Plan is ready for approval.

---

## 21. State/commit protocol (for future implementation)

plan → review → plan commit → smallest increment → focused tests → compatibility tests → canonical suite → acceptance evidence → state binding → clean commit → next increment. Do not combine unverified M5 increments. Final M5 acceptance requires 0 failed canonical suite; do not weaken environmental-isolation tests.

## 22. Grant-administration authority decision (M5.4 plan correction — APPROVED)

This section records the approved architecture decision that resolves the M5.4
plan gap "authority to create canonical access_grant events is undefined".

**Decision.** Canonical `access_grant` administration (create / revoke /
supersede) is a trusted control-plane operation, separated from ordinary
`AccessRequest` READ/WRITE policy. Only an explicit trusted local/operator
control-plane entrypoint may perform those operations. Ordinary agent/user
`AccessRequest` flows can NEVER reach them. The authority predicate is:

> authority(grant_admin_action) == True  IFF  the call enters through the
> trusted control-plane `GrantAdminRequest` boundary (validated contract).
> Otherwise authority == False, regardless of any caller-supplied claim.

No `grant_admin` role, no `grant_admin` access grant, no recursive grant-permitting
grant, and no profile/project-owner inference. This prevents bootstrap recursion.

**Trust-boundary assumption (explicit).** M5 does not implement authentication.
The hosting/control-plane layer is responsible for deciding *who* may invoke the
trusted grant-admin entrypoint. M5 guarantees ordinary agent policy paths cannot
reach it. Future auth/identity hardening strengthens the boundary without changing
grant semantics.

**Schema impact.** No new table beyond the already-approved v8
(`zm_access_grants`, `zm_policy_audit`). No admin table, role table, or bootstrap
grant table. Schema target remains **v8**.

**Acceptance tests to add to the M5.4 matrix (plan level):**

- normal caller CREATE grant -> denied/unreachable;
- normal caller REVOKE grant -> denied/unreachable;
- normal caller SUPERSEDE grant -> denied/unreachable;
- WRITE-authorized caller still cannot CREATE grant;
- WRITE-authorized caller still cannot REVOKE grant;
- WRITE-authorized caller still cannot SUPERSEDE grant;
- `is_admin=true` cannot escalate;
- `trusted=true` cannot escalate;
- trusted `GrantAdminRequest` CREATE succeeds;
- trusted `GrantAdminRequest` REVOKE succeeds;
- trusted `GrantAdminRequest` SUPERSEDE succeeds;
- malformed trusted request fails before canonical append;
- failed grant-admin operation leaves no partial canonical/derived state;
- canonical event projection remains deterministic;
- grant history remains append-only.

Plan status updated: **APPROVED — READY FOR M5.4 IMPLEMENTATION** (grant-admin
gap resolved via trusted control-plane authority).
