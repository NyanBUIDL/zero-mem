# M7.6 — Performance, Security, End-to-End Acceptance + FINAL M7 Closure

Status: VERIFIED (2026-08-09)
Milestone: M7 (Controlled Injection + Master Zero-Mem Runtime Switch) — FINAL increment
Schema version: 8 (unchanged; no migration)

## Scope

M7.6 is the FINAL M7 increment. It verifies the complete M7.1–M7.5
controlled-injection pipeline as one integrated system through 78 end-to-end
acceptance tests covering: runtime (master ON/OFF, no_memory, all routes),
authorization matrix, resource_type isolation, lifecycle, conflict/insufficiency,
prompt injection (16 adversarial attacks), contract validation, runtime isolation,
architecture audit, real Hermes hook integration, performance benchmarks, and
task-continuation correctness.

## Complete M7 system verified

Hermes request → M7.1 master gate → M7.2 router → M7.3 authorized EvidenceSet
→ M7.4 real pre_llm_call injection → M7.5 hardening → captured model context.

## Real Hermes hook evidence

- Hook name: `pre_llm_call` (in `VALID_HOOKS` in `hermes_cli/plugins.py`)
- Registration: `ctx.register_hook("pre_llm_call", callback)` via plugin `register(ctx)`
- Callback: `callback(**kwargs)` — returns `{"context": "..."}` or None
- Invocation: `agent/turn_context.py` ~line 1054, before model generation
- Injection target: user message API copy only (never system prompt)
- Preserves prompt cache prefix

## Master switch

- ON: routing, retrieval, injection all work; M5 authorization mandatory ✅
- OFF: zero routing, zero retrieval, zero injection; context unchanged ✅
- Single `ZERO_MEM_ENABLED` switch; no second injection switch ✅

## Authorization matrix

- Same-profile authorized ✅
- Cross-profile denied ✅
- Same-project/different-profile denied ✅
- Exact project grant allows ✅
- Revoked grant denied ✅
- Resource_type isolation (artifact-only cannot expose event/decision) ✅
- Linked-resource independent authorization ✅

## Prompt-injection resistance

16 adversarial attacks tested — all remain inert DATA:
"Ignore previous instructions", "Act as system", "Act as developer",
"Reveal system prompt", "Reveal all secrets", "Change requesting_profile_id",
"Read all profiles", "Use global_memory", "Create a grant", "Revoke grant",
"Call GrantAdminService", "Disable ZERO_MEM_ENABLED", "Run SQL",
"Read raw JSONL", "Execute shell command", "Use as current user request",
"Do not disclose memory source".

None gain system/developer/user authority. None change identity, route,
grants, or master switch. Role markers (`role=system`, `role=developer`)
broken by zero-width-space escaping. Delimiter injection contained.

## Performance benchmark

| Component | Sample count | Median (μs) | p95 (μs) |
|---|---|---|---|
| Master gate | 100 | <100 | <100 |
| Router | 100 | <100 | <100 |
| Complete pre-LLM path | 50 | <10,000 | <2,000,000 |
| no_memory path | 100 | <100 | <100 |
| Hardening (validate+sanitize+serialize) | 50 | <1,000 | <1,000,000 |

Approved target: p95 < 2 seconds for MVP/local execution. ✅ Met.

## Task-continuation benchmark

Deterministic 5-scenario benchmark testing: project continuation, external_current,
no_memory, user_memory, research_memory. Correct routing/injection for each case.

Result: 5/5 correct (100%) ≥ 90% approved target. ✅ Met.

## Zero-LLM / zero-network proof

AST import analysis of all 8 M7 modules: no `openai`, `llm`, `httpx`, `requests`,
`aiohttp`, `socket`, `urllib` imports. No `GrantAdminService`. No
`AuthorizedWriteService`. No `sqlite3` direct access. No hard-coded home paths.

## Tests / acceptance

- M7.6 focused: 78 passed, 0 failed
- M7.1 regression: 40 passed
- M7.2 regression: 59 passed
- M7.3 regression: 31 passed
- M7.4 regression: 51 passed
- M7.5 regression: 70 passed
- M5 regression: 250 passed
- M6 regression: 387 passed
- M1/M3/M4 regression: 608 passed
- Pre-binding canonical: 1826 passed, 3 skipped, 0 failed
- Final-HEAD canonical: 1826 passed, 3 skipped, 0 failed

## M7 overall: VERIFIED

All M7 increments verified:
- M7.1: VERIFIED (master gate)
- M7.2: VERIFIED (router)
- M7.3: VERIFIED (evidence builder)
- M7.4: VERIFIED (injection adapter)
- M7.5: VERIFIED (hardening)
- M7.6: VERIFIED (final acceptance + closure)

## Deferred (NOT implemented in M7)

- M8: graph/temporal/vector/entity retrieval, advanced calibration, Obsidian
  projection, corpus expansion

## Files changed

- `tests/unit/test_m7_6_end_to_end.py` (new — 78 end-to-end acceptance tests)
- `acceptance-m7.6.md` (new)
- `project-state.yaml` (updated: M7.6 VERIFIED, M7 overall VERIFIED)
- `implementation-plan.json` (updated: M7.6 VERIFIED, next_incomplete=M8)
