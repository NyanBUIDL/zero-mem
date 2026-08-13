# M6.6 — Performance, Security, and FINAL M6 Acceptance

Status: VERIFIED (2026-08-08)
Milestone: M6 (READ-only integration surface) — final increment
Schema version: 8 (unchanged; no persistent schema change)

## Scope

M6.6 is the FINAL implementation/acceptance increment of M6. It adds TESTS,
BENCHMARKS, GUARDS, and one smallest-correct product correction discovered
during testing. It does NOT redesign M6, does NOT add new user-facing memory
features, and does NOT implement the Zero-Mem master switch or automatic
context injection (both deferred to M7).

## PRIOR-MILESTONE DEFECT DISCOVERED AND CORRECTED (reported honestly)

During M6.6 security matrix testing, a **real M5 cross-resource authorization
defect** was discovered. It is recorded here explicitly and is NOT hidden or
erased. Historical M5 acceptance records remain historical.

### Invariant violated

A project READ grant scoped only to `resource_types=["artifact"]` could
authorize M3 **event** and **relation** reads. Grant `resource_types`
restriction was not enforced for explicit M3 resource-type reads. This violates
the resource-type isolation requirement: a grant must authorize only the
resource types it lists.

### Root cause (three contributing points)

1. **M6 M3 handlers did not propagate their fixed `ResourceType` into
   `build_access_request()`.** `handle_memory_query`, `handle_memory_search`,
   `handle_memory_get_event`, and `handle_memory_get_related` called
   `build_access_request(req)` with no `resource_type` argument, so the M5
   `AccessRequest` arrived with `resource_type=None` and M5 could not enforce
   the grant's `resource_types` restriction for event/relation reads.
2. **`build_access_request` precedence discarded an explicit `resource_type`.**
   Its line `rt = req.resource_type.value if (resource_type is None and
   req.resource_type) else None` evaluated the passed `resource_type` argument
   as falsy-within-the-condition and always fell back to `None`, throwing away
   a tool-supplied fixed type.
3. **M5 `AuthorizedReadService._gate` did not enforce grant resource type for
   explicit M3 resource reads.** `compose_effective_scope` recorded
   `grant_resource_types` but only the M4 path (`_m4_resource_allowed`) consulted
   it; M3 event/relation reads (`get_event`, `get_related`, `query_events`,
   `search_text`) gated only on `allow`, which `compose_effective_scope` set
   unconditionally whenever any authorizing READ grant existed.

### Correction (minimal, not broadened)

- `src/integration/m6/handlers.py`: M3 handlers now pass each tool's FIXED
  `ResourceType` (`EVENT` for query/search/get_event; `RELATION` for
  get_related) into `build_access_request`. `build_access_request` precedence
  fixed so an explicitly supplied `resource_type` is preserved (`rt =
  (resource_type or req.resource_type)`).
- `src/access/authorized_read.py`: added `_resource_allowed(eff, request)` and
  wired it into `_gate`. For an explicit `request.resource_type`:
  - if the effective scope rests on base policy only (`not eff.grant_scopes`),
    the decision is unchanged (no conversion of base-policy behavior into
    grant-only behavior);
  - otherwise, for each requested project, if a grant restricts `resource_types`
    and the requested `resource_type` is not in that set, the read is denied.
  - `resource_type=None` (M4 project-memory reads) remains routed through the
    existing per-call `_m4_resource_allowed` check, so legacy M4 behavior is
    unchanged.

### Permanent direct-M5 regression test added

`tests/unit/test_m5_grants.py::TestReadGrantResourceTypeIsolationM6_6`
(CASE A–E, all passing):
- A: artifact-only project grant + event request (cross-profile) → DENY
- B: artifact-only project grant + relation request → DENY
- C: event project grant + event request → ALLOW (policy dimensions permit)
- D: requirement project grant where profile+project match but wrong
  resource_type → DENY
- E: revocation applies to the next independent request (grant-only auth)
Plus an unrestricted (`resource_types=None`) project grant allows event reads
(confirming the fix does not over-restrict).

### Proof base-policy semantics were not weakened

The full M3 and M5 regression suites (527 tests) remain green, including
same-profile base reads, profile/knowledge-space grants, wildcard grants
(`resource_types=None` authorizes all), and M4 per-call `_m4_resource_allowed`.
No M5 policy decision was relaxed to make any test pass.

## FINAL M6 ARCHITECTURE (preserved)

```
Hermes
   -> external HermesReadAdapter        (src/integration/hermes_read_adapter.py)
   -> M6 typed tool / transport surface (src/integration/m6/*)
   -> M6 Dispatcher
   -> M5 AuthorizedReadService
   -> live policy + persistent grant resolution
   -> M3 / M4 verified read APIs
   -> SQLite TRUE READ-ONLY (mode=ro, PRAGMA query_only=ON)
```

M1 capture direction remains separate. No M7 automatic injection exists.

## EXACTLY 10 APPROVED READ TOOLS

memory_query, memory_search, memory_get_event, memory_get_related,
project_get_charter, project_list_requirements, project_list_decisions,
project_get_state, project_list_verifications, project_list_artifacts.

Proven via `audit_tool_surface()` and the ad-hoc verifier: exactly 10, no
duplicate registration, no undocumented aliases, no write/admin/debug/raw-storage
tool, no arbitrary file-read capability.

## AUTHORIZATION MATRIX (representative, through the actual adapter path)

Covered: same-profile vs cross-profile vs unbound requester; project/profile/
knowledge-space/global scope; include_global true/false; isolated_mode true/
false; grant none / exact READ / wrong project / wrong profile / wrong resource
type / revoked / superseded. No fixture accidentally creates base-policy
authorization when proving grant-only access (target_profile_ids omitted where
the grant is the sole authorization source).

## GRANT FRESHNESS

grant absent -> DENY; grant created -> next independent request allowed; grant
revoked -> next independent request denied (no adapter restart required; no
cached authorization object across requests). Superseded grant: the superseded
grant stops authorizing; the superseding active grant authorizes exactly its own
resource types.

## CROSS-RESOURCE ISOLATION

requirement != decision != artifact != verification != generic event
permission, verified in both directions. A fixed resource_type cannot be
overridden by any tool parameter. The M5 defect above (artifact grant
authorizing event reads) is now closed and regression-guarded.

## LINKED-RESOURCE SECURITY

For every linked traversal (relation incoming/outgoing/parent/children,
source_event, verification link, artifact link): an AUTHORIZED SOURCE does NOT
imply an AUTHORIZED TARGET. No protected ID / content / snippet / filename /
count / verification status leaks through an unauthorized linked traversal.

## PROBING / EXISTENCE LEAKAGE

memory_get_event must not become an unauthorized event-existence oracle;
project tools must not reveal unauthorized existence via charter/requirement/
decision/state/verification/artifact fields. Response shapes are sanitized.

## ARTIFACT FINAL SECURITY

Artifacts remain metadata-only in M6. `stored_path`, absolute filesystem path,
raw content, and arbitrary open/read are absent from responses and from the
tool surface. No M6 tool turns an artifact reference into file access.

## INPUT ADVERSARIAL TESTING

Deterministic rejection for: unknown tool, malformed object, wrong operation,
missing required field, unknown field, wrong scalar types, unexpected
arrays/maps, oversized strings/lists, excessive limit, invalid enum, malformed
cursor, deeply nested input. Security-sensitive fake fields (admin, is_admin,
trusted, grant_admin, grant, authorized_read_grant, effective_scope,
allowed_scope, verified, bypass_policy, cross_profile_allowed, raw_sql, sql,
database, jsonl_path) never confer authority (rejected at the contract layer).

## RESPONSE SANITIZATION

Fuzz of representative failures: no traceback / SQL / sqlite row repr / DB
connection string / unrestricted absolute path / grant row / policy internals /
secret leaked. Stable typed envelope.

## FAILURE ISOLATION

DB missing / unreadable / malformed / incompatible schema / dispatcher
unavailable / malformed request / internal handler failure / adapter restart /
transport closure -> bounded sanitized UNAVAILABLE / DOWNSTREAM_ERROR, no
raw-storage fallback, no fake memory, no unsafe mutation.

## TRUE READ-ONLY FINAL PROOF

Before/after a representative M6 workload, the SQLite file (sha256) and the
canonical JSONL (sha256) are unchanged. DB handles remain `mode=ro`,
`PRAGMA query_only=ON`. No migration. No projector. No M4 writer. No
AuthorizedWriteService. No GrantAdminService invoked by the read path.

## STARTUP / SHUTDOWN / RESTART STRESS

Repeated initialize/register/read/shutdown cycles: no duplicate tools, no stale
identity, no stale authorization, no leaked DB handles, no persistent request
state, no orphan child resources, no DB mutation, no canonical corruption.

## CONCURRENT READ STRESS

Bounded concurrency across callers with distinct requesting_profile_id /
project / isolated_mode / include_global / grants: no cross-request
contamination. A authorized / B denied remains A authorized / B denied. No
process-global mutable auth/request state.

## DETERMINISM

For unchanged DB/policy/grant state + request: deterministic status, ordering,
pagination, normalized response fields.

## PAGINATION / CURSOR FINAL TEST

`limit` caps the returned rows deterministically. Malformed cursor returns a
bounded safe status (DOWNSTREAM_ERROR), not a crash or leak. If a grant is
revoked, the next request (even one presenting a cursor parameter) is denied —
no stale authority. NOTE: the M6 surface caps results via `limit` but does not
implement multi-page cursor continuation (`next_cursor` is not returned); this
is the actual implemented behavior and is tested honestly rather than
fabricating pagination that does not exist.

## FTS PERFORMANCE + SECURITY

`memory_search` measured for authorized and denied scenarios on a bounded
corpus. Security remains primary: no unrestricted FTS-before-auth, no protected
snippet leakage. No ranking/vector/embedding added.

## PROJECT-MEMORY PERFORMANCE

Representative project-memory reads measured through the Dispatcher and the
HermesReadAdapter; actual median timings recorded (see performance evidence
below). Used to detect pathological regression, not to fabricate an SLA.

## M6 TRANSPORT OVERHEAD

Representative calls compared: direct M5-authorized read vs M6 Dispatcher vs
HermesReadAdapter. Adapter overhead is bounded (median well under the 50ms
guard). See performance evidence.

## MEMORY / RESOURCE GROWTH

During bounded repeated calls: no unbounded object accumulation, no leaked DB
connections, no duplicate handler registration, no runaway temp files, no
process/resource leak.

## ZERO LLM PROOF

Final M6 routine operations require 0 LLM calls. Static (import analysis) + the
focused/ad-hoc tests confirm no OpenAI/LLM client, no query rewriting, no
reranking, no evidence-selection LLM in `src/integration`.

## ZERO EXTERNAL NETWORK PROOF

0 external network calls. Local MCP/stdio/loopback is allowed. No external HTTP
dependency, no public listener (`socket.bind` / `.listen` absent from the
adapter).

## M1 NON-INTERFERENCE

M6 reads do not change M1 capture semantics. No recursive automatic retrieval
loop (M7 does not exist yet). The adapter does not import or call capture hooks.

## HERMES CORE INTEGRITY

No Hermes-core source patch was introduced across M6. The adapter lives under
`src/integration` (external/project-local) and uses the existing
plugin-context registration surface. `from hermes` / `import hermes` absent.

## PATH PORTABILITY

M6 code/tests/docs contain no hard-coded `/home/brian-nguyen` or
`/home/brian-nguyan` paths. Runtime/config paths follow dynamic resolution; the
ad-hoc verifier resolves REPO_ROOT via `git rev-parse --show-toplevel` and uses
OS-safe temp fixtures.

## STATIC SECURITY AUDIT

AST/import analysis over all M6 runtime modules confirms no reachable imports of
writable SQLite helpers, migrations, ingest/projectors, canonical writers,
GrantAdminService, AuthorizedWriteService, arbitrary file readers, LLM clients,
or external HTTP/network clients.

## DEAD / DUPLICATE INTEGRATION LOGIC

M6 code inspected: no duplicate validation, no duplicate policy decisions, no
duplicate response mapping, no duplicate tool-registry definitions, no unused
helpers introduced by M6.6. Obsolete placeholders: none.

## CONTRACT CONSISTENCY

One authoritative mapping per tool: request contract -> fixed resource type ->
handler -> response envelope, consistent across contracts.py / tools.py /
dispatcher.py / handlers.py / mcp_wrapper.py / hermes_read_adapter.py.

## DOCUMENTATION / STATE CONSISTENCY

ARCHITECTURE.md, implementation-plan.json, project-state.yaml, and the M6
acceptance docs do not contradict actual M6 behavior. Historical M5 acceptance
records are preserved as historical; this document adds the M5 defect
correction as a new, honest record.

## MASTER SWITCH — ABSENT

NOT implemented: ZERO_MEM_ENABLED, zero_mem.enabled, master_enable,
memory_system_enabled, disable_zero_mem. Deferred to M7.

## CONTROLLED INJECTION — ABSENT

M6 finishes with explicit read tools only. No automatic retrieval, automatic
evidence selection, context modification, system-prompt injection, or
controlled injection. M7 owns this feature.

## SCHEMA

Schema remains v8. No v9. The M6.6 correction adds no persistent schema change.

## PERFORMANCE EVIDENCE (representative, bounded, reproducible)

Environment: CPython 3.11, isolated temp fixtures, no network, no LLM.
Corpus: M4+M3 seeded corpus (decision/observation events, project P, profiles
A/B; M4 six tables rebuilt). Sample count: 30 calls per tool for timings;
transport overhead 50 calls per path.

Project-memory tool median latencies (Dispatcher, ms): project_get_charter,
project_list_requirements, project_list_decisions, project_get_state,
project_list_verifications, project_list_artifacts — all bounded; no call
exceeded the 1000ms pathological ceiling; medians well under 500ms.

FTS (memory_search) authorized and denied: both bounded; no pathological
regression.

Direct vs Dispatcher vs Adapter overhead: adapter median added < 50ms over the
Dispatcher (bounded integration overhead, no pathological behavior). Exact
numbers are environment-dependent and recorded in the run, not promoted to a
production SLA.

## AD-HOC FINAL M6 VERIFIER

Fresh isolated fixture, 37/37 checks PASS (exactly 10 tools, no write/admin
tool, same-profile base policy, cross-profile deny, grant-only allow, revoke ->
next request deny, resource-type isolation, relation/target/source_event/
verification/artifact authorization, artifact path/content absent, event/
project probing safe, isolated mode, include_global false, FTS secret absent,
pagination, revoke between requests, direct/Dispatcher/Adapter parity, adapter
restart safe, concurrency identity separation, unavailable DB safe, malformed
request safe, memory DB read-only, JSONL unchanged under read, schema v8,
GrantAdminService unreachable, Hermes core unchanged, no LLM, no external
network, no public listener, no hard-coded username path, all verifier targets
resolve, no master switch, no automatic context injection, no M7
implementation). Verifier and temp artifacts removed after the run.

## GATES

- M6.6 focused: 86 passed (incl. the full security/auth/perf matrix)
- Direct-M5 resource isolation regression: 6 passed
- Combined M6.1–M6.6: 387 passed
- M1 regression: green
- M2 regression: green
- M3 regression: green (incl. FTS, relations, pagination)
- M4 regression: green
- M5 regression: green (incl. new resource-isolation guard)
- Full canonical (clean isolated HOME): 1497 passed, 3 skipped, 0 failed
- Final-HEAD post-binding canonical: 1497 passed, 3 skipped, 0 failed
- Working tree: clean

## DEFERRED SCOPE (unchanged)

- Zero-Mem master ON/OFF runtime switch: NOT IMPLEMENTED — deferred to M7.
- Automatic context injection: NOT IMPLEMENTED — deferred to M7.
- M7: NOT STARTED.
