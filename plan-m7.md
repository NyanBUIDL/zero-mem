# M7 — Controlled Injection + Master Zero-Mem Runtime Switch

**Status:** PLAN READY — awaiting approval (planning only; no product code implemented)
**Authoritative starting HEAD:** `3cfd2aa4060d97254fe4cd1b59081b203f451f10`
**Schema:** v8 (unchanged; M7 plans no persistent schema change)
**Final M6 canonical:** 1497 passed, 3 skipped, 0 failed
**Working tree at planning time:** clean
**Preceding milestones:** M0–M6 VERIFIED; M7 NOT STARTED; M8 NOT STARTED

This document is the committed M7 implementation plan only. It introduces NO
product code, NO tests, NO schema change, NO M8 code. It defines the smallest
safe increments, the single master switch, the deterministic router, evidence
gating, the injection envelope, and the full security/acceptance matrix.

---

## 1. Starting state reconciliation

- HEAD `3cfd2aa` confirmed.
- `git status` clean; `git log -20` shows M6.6 bound (`75859f0`) above M6.5/M6.4/.../M0.
- Schema v8 (canonical store after migration; `migrate_8.py` present). M7 plans **no migration**.
- Config architecture inspected: `BridgeConfig` (frozen dataclass) is the
  existing carrier; identity resolves from explicit value then `HERMES_PROJECT_ID`
  / `HERMES_PROFILE_ID` env, never inferred. No config file loader exists yet —
  config is constructed in-process and passed explicitly. `_safe_root` rejects the
  real HOME as a capture root.
- M6 runtime uses module-level `_default_runtime` set via `m6.configure(store_path)`.
  M6 dispatcher is stateless (`dispatch(raw)`). `HermesReadAdapter` already returns
  `CAPABILITY_UNAVAILABLE` when its own `enabled` is false, but that flag is the
  **per-bridge opt-in**, NOT the master Zero-Mem switch.
- M5 `AccessRequest` already carries `target_profile_ids`, `project_ids`,
  `knowledge_space_ids`, `resource_type`, `include_global`, `isolated_mode`,
  `requesting_profile_id` — exactly the fields M7 needs to build an authorized
  scope. The resolver enforces `lifecycle_status==active`, exact target match, and
  **resource_type coverage** (the M6.6 fix is in `compose_effective_scope` /
  `_resource_allowed`). M7 reuses this untouched.
- No memory-need router exists (`grep` confirms). M7.2 adds a deterministic one.
- M1 capture entry: `RegistrationAdapter._observe` → `adapt_mapped_event` →
  `store.append`. M1 gate point is the `_observe` early-return.
- No Hermes-core modification has occurred for M0–M6; the M6 adapter and M1
  registration use the **supported external plugin context** (`register_tool`,
  `register_hook`). The same surface is the M7 injection extension point.

---

## 2. User decision — ONE master switch

Per authoritative user decision there is exactly ONE user-facing master boolean:

- Canonical field: **`ZERO_MEM_ENABLED`** (boolean), owned by the Zero-Mem
  runtime configuration, consistent with the existing `BridgeConfig` carrier.
- NOT split into `capture_enabled` / `retrieval_enabled` / `injection_enabled` /
  `mcp_enabled` / `routing_enabled`. One switch only.

### Single source of truth

- `ZERO_MEM_ENABLED` is the canonical authority.
- The existing `BridgeConfig.enabled` (per-bridge opt-in observer) remains a
  **separate, narrower** flag: it controls whether this project's bridge wires
  hooks/tools at all. The master switch is layered **above** it.
- Relationship (no double authority):
  - `ZERO_MEM_ENABLED == false` → Zero-Mem fully bypassed (master gate short-circuits).
  - `ZERO_MEM_ENABLED == true` AND `BridgeConfig.enabled == true` → normal operation.
  - `ZERO_MEM_ENABLED == true` AND `BridgeConfig.enabled == false` → Zero-Mem not
    wired for this project (no-op), but the switch itself is ON (other projects /
    processes may use it). This preserves "one master switch" semantics: the master
    controls whether Zero-Mem *participates globally*; the bridge flag is a
    project-local wiring choice already established by M1/M6.
- No alias. If a future env name is needed for compatibility it MUST resolve to
  `ZERO_MEM_ENABLED` and be documented as an alias only.

### Default and restart

- **Default when absent: `ZERO_MEM_ENABLED = true`** (fail-safe: existing verified
  M0–M6 behavior is preserved; turning the switch OFF is an explicit opt-out, so a
  missing/garbled config never silently disables memory).
- Resolution: read once per process start from the runtime config object
  (`BridgeConfig.zero_mem_enabled`, defaulting to `True`). The current
  architecture has **no live config watcher**; changing the switch therefore
  **requires adapter/Hermes restart**. This is explicitly documented and accepted
  (no hot-reload subsystem invented).
- Per-operation consumers ask ONE resolver: `zero_mem_runtime.is_enabled()` —
  not scattered env parsing.

---

## 3. Master gate locations (minimum safe entrypoints)

Add one small shared gate module `src/integration/zero_mem_runtime.py`
(planning name; final path TBD in M7.1) owning the single state:

- `ZeroMemRuntime` holds `enabled: bool` (parsed from `BridgeConfig.zero_mem_enabled`).
- `is_enabled() -> bool` is the ONE authority.
- All three active entrypoints consult it (no env parsing elsewhere):
  1. **M1 capture entry** (`RegistrationAdapter._observe`): if not enabled →
     deterministic no-op (return immediately, no append, no "disabled" event).
  2. **M6 read-tool entry** (`HermesReadAdapter.call` / `_make_handler`): if not
     enabled → return `CAPABILITY_UNAVAILABLE` / `ZERO_MEM_DISABLED` envelope for
     **all 10** tools identically (no tool bypasses the gate).
  3. **M7 injection entry** (`MemoryNeedRouter.route` / `inject`): if not enabled →
     `0` routing/retrieval/injection; return empty envelope.
- M5 authorization is **unchanged** and still enforced after the gate. The master
  switch is NOT an authorization mechanism.

### Storage safety under OFF

- OFF performs zero writes. Tests hash JSONL, SQLite, artifacts, grants, and
  `project-state.yaml` before/after an OFF request to prove: no deletion, no reset,
  no migration, no purge, no lifecycle change.
- OFF → ON: existing memory remains readable; no rebuild required (current
  architecture needs none); grants/project state intact.
- ON → OFF: subsequent request respects OFF; no stale per-request enabled state
  (gate is consulted per call / per process start, not cached per request).

---

## 4. Deterministic memory-need router (M7.2)

No LLM. Pure structural decision from the request/context shape.

### Route taxonomy and supportability (current M0–M6 data model)

- `no_memory` — **fully supported**. Determined structurally (e.g., request
  explicitly declines memory, or route context is a pure compute/coding action
  with no project/profile scope and `include_memory=false`). Returns 0 retrieval /
  0 injection. **No query merely to "confirm" no memory is needed.**
- `session_memory` — **supported** via `project_id`/`profile_id` + session scope
  using existing M3/M4 read APIs scoped to the active profile/project.
- `project_memory` — **supported** via M4 project-memory reads (charter,
  requirements, decisions, state, verifications, artifacts).
- `user_memory` — **supported** as profile-scoped M3/M4 reads
  (`target_profile_ids=[active_profile]`).
- `research_memory` — **supported** via M3 `memory_search` (FTS) scoped to
  project/profile; treats stored content as historical (see external_current rule).
- `global_memory` — **supported** only when an active grant explicitly allows
  global read (`include_global` + authorizing grant); default profile-first.
- `external_current` — **supported as HISTORICAL ONLY**. The router may return this
  route, but M7 must NOT present stored historical memory as fresh external truth
  and must NOT add web/network search. Category meta-flag `is_historical=True`
  travels with the envelope; Hermes is told the content is past evidence, not
  current fact.

### Deferred routes (explicitly NOT implemented in M7)

- Any route requiring graph propagation, temporal hierarchy, entity graph, vector/
  dense retrieval, or cross-corpus reasoning → **deferred to M8+**. The router
  returns `insufficient_evidence` / `no_memory` for those intents rather than faking
  support.

### Route decision inputs (deterministic, testable)

`MemoryNeedRouter.decide(context) -> Route` where `context` is a small struct:
`{active_profile, project_id, requested_scope, include_memory_flag, action_class}`.
Decision is a fixed priority table (no ML). Fully unit-testable.

---

## 5. Authorized evidence eligibility + bounded set (M7.3)

### Step order (security-invariant)

request → route → **explicit scope construction** → **M5 authorization** →
restricted retrieval (M3/M4) → evidence gating → injection.

Forbidden: retrieve globally → rank → filter unauthorized afterward.

### Explicit scope construction

Build an `AccessRequest` with:
- `requesting_profile_id = explicit_or_unbound` (NEVER inferred from cwd/HOME/
  session/project/MCP/client).
- `target_profile_ids`, `project_ids`, `knowledge_space_ids` from the route + caller
  scope.
- `resource_type` set per retrieval call (event/relation/requirement/decision/
  verification/artifact) — **propagated through** so the M6.6 resource_type
  isolation fix is preserved (artifact-only grant must NOT authorize event/relation
  reads).
- `include_global`, `isolated_mode` honored from caller intent.

### Candidate evidence (current APIs only)

- M3: `memory_query`, `memory_search`, `memory_get_event`, `memory_get_related`.
- M4: `project_get_charter`, `project_list_requirements`, `project_list_decisions`,
  `project_get_state`, `project_list_verifications`, `project_list_artifacts`.
- All called through the verified M5 `AuthorizedReadService` (same path M6 uses).

### Eligibility (deterministic; no LLM)

Drop candidates that fail ANY:
- lifecycle NOT in `{active, confirmed}` for "current truth" claims (superseded/
  conflicted/archived/deleted excluded);
- verification required for claims presented as verified (use existing
  `verification_status`);
- sensitivity above the caller's ceiling (use existing sensitivity metadata;
  authorized != automatically injectable);
- conflicted record without an existing active authoritative winner → represented,
  not silently chosen;
- provenance incomplete (missing trace/event id or source) → excluded;
- scope mismatch vs authorized request → excluded (M5 already enforces; M7 re-checks
  at injection as defense-in-depth).

### Confidence / threshold representation

No new calibration subsystem. Reuse existing `confidence` + `verification_status`
metadata as the eligibility signal. No score invented.

### Bounded evidence set (deterministic budget)

- max **5 primary** evidence items (default);
- max **3 supporting** evidence items;
- target evidence context **3,000–6,000 tokens**; enforcement via the project's
  existing local deterministic tokenizer if available, else a documented
  conservative estimator (char-count / ~4 chars-per-token). **No LLM token count.**
- When over budget: select/omit deterministically (stable sort by
  provenance recency then verification then lifecycle). Emit `omitted_count`.
  Prefer whole items; never truncate content in a way that removes provenance or
  changes factual meaning without clearly marking the omission.

---

## 6. Conflict / insufficient-evidence / lifecycle handling (M7.5)

- **Conflicts**: if relevant evidence conflicts, the envelope carries a
  `conflicts` list with structured pointers (trace ids + state), and does NOT pick
  a winner. Where current verified active state exists, the distinction
  (current verified vs historical/conflicting) is preserved.
- **Insufficient evidence**: explicit `insufficient_evidence: true` (or structured
  indicator). No fabrication; empty evidence is a valid result.
- **Lifecycle**: never inject `deleted`; never treat `superseded` as current truth;
  never silently pick a `conflicted` winner without an existing verified policy
  identifying the authoritative active state.

---

## 7. Structured injection envelope (M7.4)

Reuse M6 typed/sanitized conventions. Stable shape:

```json
{
  "route": "<route>",
  "active_profile": "<profile|null>",
  "used_scopes": ["..."],
  "evidence": [ { provenance..., payload, eligibility } ],
  "conflicts": [ { trace_id, state } ],
  "insufficient_evidence": false,
  "omitted_count": 0,
  "token_estimate": 0,
  "master_disabled": false
}
```

Names adjusted to match M6 contract conventions if needed; provenance (trace/event
id, type, source, timestamp, lifecycle, verification, scope, eligibility) is
attached to every evidence item.

---

## 8. Hermes context-injection extension point (M7.4)

- **Preferred**: reuse the verified external plugin-context surface already used by
  M1/M6 — `register_hook` / `register_tool` on the plugin context. M7 registers a
  `pre_llm_call` (currently `CONDITIONAL_FIXTURE_REQUIRED`) callback that, when the
  host provides it, augments the outgoing LLM payload with the structured envelope
  as **data only**.
- **If no safe external augmentation hook exists** (objective evidence at M7.4
  implementation time): M7 PLAN DEVIATION — no supported external context-injection
  extension point: <evidence>. In that case M7 exposes an explicit read-only tool
  `zero_mem_recall` (same vein as M6 tools: forwarded through M5, no write, no core
  patch) that Hermes can call deliberately. Automatic routing remains gated behind
  the available hook; the tool path is always available.
- **No Hermes-core modification.** The plan does NOT patch Hermes core. If
  implementation proves no supported hook can satisfy the requirement, the deviation
  above is raised for approval — Hermes core is not silently patched.

### Injection position / prompt-injection defense

- Clearly delimited, structured section marked as EVIDENCE (not instructions).
- Cannot masquerade as system/developer policy; cannot override system instructions.
- Stored content (user text, assistant claims, tool output, docs) is injected as
  **DATA**. Structural delimiting + escaping ensures text such as
  "ignore previous instructions" remains inert evidence.
- Tests inject malicious stored content attempting instruction override, secret
  disclosure, profile/identity change, scope widening, raw SQL, GrantAdminService
  invocation, and master-switch change — all must remain evidence-only, none
  executed as authority.

---

## 9. Authorization, isolation, zero-LLM/zero-network invariants

- M7 NEVER bypasses M5. Injection evidence is exactly what the same caller could
  retrieve via M6. Automatic injection is at least as restrictive as explicit reads.
- Resource-type isolation (M6.6 fix) preserved: every retrieval call carries its
  exact `resource_type`; artifact-only grant cannot authorize event/relation/etc.
- Profile/project/space semantics preserved exactly: same-project does NOT bypass
  profile isolation; relations/artifacts/verifications/source-links/supersession
  links grant NO authorization.
- Identity: `requesting_profile_id` explicit or unbound per M5/M6; no cross-request
  identity retention.
- **Zero LLM**: routing, eligibility, ranking, filtering, conflict detection,
  sufficiency, and envelope formatting use 0 LLM calls. Hermes's own final-response
  LLM is outside this restriction.
- **Zero external network**: M7 memory ops use only local SQLite/MCP/in-process. No
  remote retrieval, no web search (external_current stays historical).
- **No write-back**: M7 adds no memory write semantics (no confirm/promote/resolve/
  grant changes/state changes). GrantAdminService unreachable from M7.
- **Failure isolation**: injection failure → bounded sanitized failure, no fake
  evidence; Hermes continues without memory where safe. Authorization uncertainty →
  do not inject (fail closed).

---

## 10. Performance plan (M7.6)

Measure separately (median/p95, bounded reproducible fixture):
- master-gate overhead;
- route-decision overhead;
- authorized retrieval overhead (per resource_type call);
- evidence gating/budget overhead;
- injection-preparation overhead;
- end-to-end Zero-Mem pre-LLM overhead.
Avoid pathological retrieval on obvious `no_memory` requests (router returns
immediately). No arbitrary ms thresholds invented; record observed medians/p95.

---

## 11. Observability

MinIMAL structured metrics (no content/secrets/raw grant rows/unrestricted paths):
`route`, `injection_performed`, `evidence_count`, `omitted_count`,
`insufficient_evidence`, `conflict_count`, `latency_buckets`, `master_enabled`.

---

## 12. Proposed increments (smallest safe)

### M7.1 — Master runtime gate + shared configuration/contracts
- Objective: one `ZERO_MEM_ENABLED` authority + gate module.
- Scope: `zero_mem_runtime.py` (`ZeroMemRuntime`, `is_enabled`), extend
  `BridgeConfig` with `zero_mem_enabled: bool = True`; wire gate checks into M1
  `_observe`, M6 `HermesReadAdapter.call`/`_make_handler`, and M7 entry (later).
- Non-goals: no injection logic, no router.
- Invariants: one switch; default true; OFF = clean bypass; no storage mutation.
- Tests: ON capture works; OFF capture no-op (JSONL unchanged); OFF M6 tools all
  return `CAPABILITY_UNAVAILABLE`; OFF storage hashes unchanged; existing data
  preserved; restart-required documented.
- Regression gates: full M0–M6 canonical green.
- Acceptance: OFF→ON persistence; ON→OFF respected; no core patch.
- Deferred: hot reload (restart required).
- Rollback: revert `zero_mem_runtime.py` + `BridgeConfig` field; behavior returns to
  pre-M7 (master always-on).

### M7.2 — Deterministic memory-need router
- Objective: `no_memory`/`session`/`project`/`user`/`research`/`global`/
  `external_current` routing, no LLM.
- Scope: `memory_router.py` (`MemoryNeedRouter.decide`, `Route` enum, eligibility
  struct).
- Non-goals: graph/dense/vector routes (deferred to M8).
- Invariants: deterministic; `no_memory` → 0 retrieval; `external_current` →
  historical-only, no network.
- Tests: each route resolves from structural context; `no_memory` retrieves nothing;
  unsupported intents → `insufficient_evidence`/`no_memory` (no fake support).
- Regression gates: M0–M6 canonical green.
- Acceptance: router unit tests + integration via explicit recall.
- Deferred: advanced route taxonomy.
- Rollback: remove `memory_router.py`; M7.3+ depend on it.

### M7.3 — Authorized evidence eligibility + bounded evidence-set construction
- Objective: build explicit `AccessRequest`, run M5 auth, retrieve via M3/M4, gate,
  bound to 5 primary / 3 supporting / 3k–6k tokens.
- Scope: `evidence_selector.py` (eligibility filter, budget enforcer, `omitted_count`,
  token estimator).
- Non-goals: no new ranking architecture; no calibration subsystem.
- Invariants: auth before retrieval; resource_type propagated; lifecycle/verification/
  sensitivity/conflict/provenance enforced; deterministic omission.
- Tests: exact grant allow; wrong-resource grant deny; revoked grant deny;
  superseded not current; deleted absent; top-5 primary; max-3 supporting; token
  budget; `omitted_count`; provenance completeness.
- Regression gates: M0–M6 canonical green + M6.6 resource_type regression.
- Acceptance: cross-profile denial; same-profile allow; isolated mode.
- Deferred: M8 retrieval architectures.
- Rollback: remove `evidence_selector.py`.

### M7.4 — Hermes controlled context-injection adapter/envelope
- Objective: produce envelope; inject via supported hook or explicit `zero_mem_recall`
  tool (read-only, M5-forwarded); position as data.
- Scope: `injection_adapter.py` (envelope builder, hook callback, optional tool).
- Non-goals: no core patch; no write-back.
- Invariants: envelope structured; memory as data not authority; prompt-injection
  containment; provenance attached.
- Tests: envelope shape; malicious stored instruction remains data; fake-authority
  request cannot widen scope; GrantAdminService unreachable; no raw SQL/JSONL.
- Regression gates: M0–M6 canonical green.
- Acceptance: injection via available hook OR explicit tool; no core modification
  (or documented deviation).
- Deferred: richer hook payloads if host unsupported.
- Rollback: remove `injection_adapter.py` + tool registration.

### M7.5 — Conflict / insufficient-evidence / prompt-injection / scope hardening
- Objective: conflict representation, insufficient_evidence signal, prompt-injection
  tests, scope hardening across automatic path.
- Scope: hardening in `evidence_selector.py` + `injection_adapter.py`; test suite.
- Non-goals: no winner-invention; no new policy engine.
- Invariants: conflicts visible; insufficient_evidence explicit; injected content
  inert.
- Tests: conflicted evidence represented; insufficient evidence represented;
  sensitivity ceiling; relation/source/artifact/verification links grant no auth;
  malicious content containment matrix.
- Regression gates: M0–M6 canonical green.
- Acceptance: full security matrix green.
- Deferred: none.
- Rollback: revert hardening changes.

### M7.6 — Performance, security, end-to-end acceptance + final M7 closure
- Objective: performance baselines; full M7 acceptance; bind state; final-HEAD
  canonical.
- Scope: benchmarks + `test_m7_*.py` + `acceptance-m7.md` + state binding.
- Non-goals: M8.
- Invariants: 0 LLM, 0 network, 0 failed canonical, clean tree.
- Tests: master ON/OFF/OFF→ON; M1 disabled capture; M6 disabled tools; M7 disabled
  injection; no_memory empty; same-profile allow; cross-profile deny; all
  resource_type isolation cases; conflict/insufficient; budget; provenance;
  prompt-injection; GrantAdminService unreachable; zero-LLM; zero-network; failure
  isolation; concurrency/request-state isolation; real `~/.hermes` safety; schema v8.
- Regression gates: complete canonical `pytest tests/ -q` under clean isolated HOME:
  **0 failed**, no deselection, no added skip/xfail. `test_no_real_hermes_home_writes`
  not weakened.
- Acceptance: implementation green → commit → state/evidence bind → commit → run
  canonical AGAIN on final binding HEAD → 0 failed → clean tree.
- Deferred: M8.
- Rollback: revert M7 implementation commits; state file entries to NOT_STARTED.

---

## 13. Final M7 acceptance protocol (mandatory)

implementation green → commit implementation → commit state/evidence binding → run
**full canonical again on the final evidence/state-binding HEAD** → 0 failed → clean
working tree. M7 VERIFIED only after the post-binding canonical, never from a
pre-binding run.

---

## 14. After M7

STOP. Do NOT begin M8 automatically. Next milestone separately authorized.

---

## 15. M8 hard boundary (deferred)

M7 implements NONE of: graph retrieval, temporal hierarchy, dense/vector retrieval,
advanced calibration, Obsidian projection, corpus expansion. Only M0–M6
capabilities + the minimum M7 controlled-injection layer.

---

## 16. Required security test plan (M7)

master ON; master OFF; OFF→ON persistence; M1 disabled capture; M6 disabled tools;
M7 disabled injection; no_memory retrieves nothing; same-profile injection;
cross-profile denial; same-project/different-profile denial; exact grant allow;
wrong-resource grant deny; revoked grant deny; conflicted grant behavior; isolated
mode; include_global false; knowledge-space boundary; relation target independently
authorized; source_event independently authorized; artifact independently
authorized; verification independently authorized; superseded evidence not treated
current; deleted evidence absent; conflicted evidence represented; insufficient
evidence represented; sensitivity ceiling; top-5 primary; max-3 supporting; evidence
token budget; omitted_count; provenance completeness; malicious stored instruction
remains data; fake authority request cannot widen scope; GrantAdminService
unreachable; no raw SQL; no raw JSONL; no arbitrary artifact content; zero LLM; zero
external network; failure isolation; concurrency/request-state isolation; real
`~/.hermes` safety; schema v8.

---

## 17. Plan answers to the 36 required questions

1. **Module owning single state:** `src/integration/zero_mem_runtime.py` →
   `ZeroMemRuntime.is_enabled()` (planning path; finalized in M7.1).
2. **Canonical config representation:** `ZERO_MEM_ENABLED` boolean on
   `BridgeConfig.zero_mem_enabled` (default `True`).
3. **Default when absent:** `True` (fail-safe; preserves M0–M6 behavior).
4. **Restart vs hot-toggle:** no live config watcher exists → **restart required**;
   documented, accepted.
5. **M1 checks gate:** `RegistrationAdapter._observe` early-returns no-op when
   `not ZeroMemRuntime.is_enabled()`; no M7 coupling beyond the gate call.
6. **M6 checks it:** `HermesReadAdapter.call`/`_make_handler` consult the gate
   before forwarding; M5 auth still applied after.
7. **M7 checks it:** router/inject entry consults gate first → 0 retrieval/injection.
8. **Existing data while OFF:** untouched (no delete/reset/migration/purge); proven
   by before/after hashes.
9. **Deterministic router:** added in M7.2 (`memory_router.py`).
10. **Fully supported routes:** no_memory, session, project, user, research, global
    (grant-gated), external_current (historical-only).
11. **Deferred routes:** graph/temporal/vector/entity/dense → M8+.
12. **no_memory without LLM:** structural decision table on request/context shape.
13. **Authorized scope construction:** explicit `AccessRequest` from route + caller
    scope, `requesting_profile_id` explicit/unbound.
14. **Candidate evidence source:** M3/M4 verified read APIs via M5.
15. **Eligibility:** lifecycle/verification/sensitivity/conflict/provenance/scope.
16. **Confidence/threshold:** reuse existing `confidence`+`verification_status`; no
    new score.
17. **Superseded/conflicted/deleted:** excluded from "current truth"; conflicted
    represented, not chosen.
18. **Conflicts without fake winner:** `conflicts` list with trace/state pointers.
19. **Insufficient evidence:** explicit `insufficient_evidence` flag; empty valid.
20. **Budgets:** max 5 primary, max 3 supporting.
21. **Token target:** existing local tokenizer or documented char/4 estimator; no LLM.
22. **Provenance:** attached per evidence item (trace/event id, type, source, time,
    lifecycle, verification, scope, eligibility).
23. **Prompt-injection containment:** structured delimited DATA section; inert text.
24. **Hermes hook:** supported plugin-context `register_hook`/`register_tool`
    (`pre_llm_call` if provided) or explicit `zero_mem_recall` tool.
25. **Core modification?** No; if impossible, raise M7 PLAN DEVIATION for approval.
26. **No M5/M6 bypass:** same `AuthorizedReadService` path; auth before retrieval.
27. **Resource_type isolation preserved:** every call carries exact `resource_type`;
    M6.6 fix reused.
28. **isolated_mode/global:** honored via `AccessRequest` fields.
29. **M5/retrieval/DB unavailable:** fail-closed → bounded sanitized failure, no
    injection.
30. **Zero-LLM proof:** routing/eligibility/budget/envelope use 0 LLM calls (assert
    in tests via import/static scan + no LLM client in path).
31. **Zero-network proof:** static import scan (no requests/httpx/aiohttp/urllib/
    socket) + no outbound calls in M7 modules.
32. **Performance metrics:** gate/route/retrieval/gating/injection/e2e medians+p95.
33. **Wrong-scope test:** cross-profile denial + resource_type mismatch deny.
34. **OFF→0 retrieval test:** assert retrieval handler invocation count == 0 when OFF.
35. **OFF no delete/reset test:** before/after hashes of JSONL/SQLite/artifacts/
    grants/state unchanged.
36. **Final-HEAD acceptance:** run `pytest tests/ -q` on binding HEAD → 0 failed.

---

## 18. Files expected to change (implementation phases only — not this plan)

- `src/integration/zero_mem_runtime.py` (new, M7.1)
- `src/integration/bridge_config.py` (add `zero_mem_enabled`, M7.1)
- `src/integration/hermes_read_adapter.py` (gate consult, M7.1)
- `src/integration/capture_adapter.py` / `hermes_registration.py` (M1 gate, M7.1)
- `src/integration/m7/memory_router.py` (new, M7.2)
- `src/integration/m7/evidence_selector.py` (new, M7.3)
- `src/integration/m7/injection_adapter.py` (new, M7.4)
- `tests/unit/test_m7_*.py` (new)
- `acceptance-m7.md` (new, M7.6)
- `implementation-plan.json`, `project-state.yaml` (state binding, M7.6)

No schema migration. No Hermes-core modification. No M8 code.

---

## 19. Planning verification (this commit only)

- schema remains v8: YES.
- no product source changed: YES (plan artifact only).
- no tests changed: YES.
- no M8 code: YES.
- no master-switch implementation: YES (only planned).
- no controlled-injection implementation: YES (only planned).
- working tree contains planning/state files only: YES.

This plan is committed as a separate planning checkpoint. M7 implementation does
not start until approved.
