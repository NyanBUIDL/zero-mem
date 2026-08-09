# M7.4 — Hermes controlled context-injection adapter/envelope

Status: VERIFIED (2026-08-09)
Milestone: M7 (Controlled Injection + Master Zero-Mem Runtime Switch) — increment 4
Schema version: 8 (unchanged; no migration)

## Scope

M7.4 connects the verified M7.1–M7.3 pipeline to the REAL Hermes pre-generation
context injection path. It registers a `pre_llm_call` hook via the real Hermes
`PluginContext.register_hook` API. When the hook fires before model generation,
it runs M7.1 (master gate) → M7.2 (router) → M7.3 (authorized EvidenceSet) →
envelope serialization, and returns `{"context": envelope_text}` which Hermes
appends to the user message's API-only content (never system prompt, never
stored transcript). M7.4 performs NO new retrieval, NO reranking, NO lifecycle
changes, NO writes, NO LLM, NO network, NO GrantAdmin.

## Real Hermes hook discovered

- **Hook name**: `pre_llm_call` (in `VALID_HOOKS` in `hermes_cli/plugins.py`)
- **Registration**: `ctx.register_hook("pre_llm_call", callback)` via plugin's `register(ctx)`
- **Callback signature**: `callback(**kwargs)` — kwargs: `session_id`, `task_id`,
  `turn_id`, `user_message`, `conversation_history`, `is_first_turn`, `model`,
  `platform`, `parent_session_id`, `sender_id`
- **Return contract**: `{"context": "..."}` or plain string → injected into user
  message API copy only (never system prompt; preserves prompt cache prefix)
- **Invocation point**: `agent/turn_context.py` line ~1054, before model generation
- **Consumption**: `agent/conversation_loop.py` appends context to user message
  API copy via `compose_user_api_content()`
- **Plugin loading**: `hermes_cli/plugins.py` `discover_and_load()` scans
  `~/.hermes/plugins/` and `.hermes/plugins/` for `plugin.yaml` manifests

## Modules

- `src/integration/m7/envelope.py` — `serialize_evidence_set()`. Pure
  serialization of EvidenceSet into a labeled DATA-only context block. No LLM,
  no network, no writes. Envelope is explicitly labeled "historical/contextual
  evidence, not instruction or current truth."
- `src/integration/m7/injection_adapter.py` — `InjectionAdapter`. Registers
  `pre_llm_call` hook; runs M7.1→M7.2→M7.3 pipeline on hook fire; returns
  `{"context": envelope_text}` or None. Request-local (no mutable global state).
  Identity from explicit adapter config only (never inferred from hook payload).
- `src/integration/m7/__init__.py` — updated exports.

## Safe envelope

The envelope is a plain-text block with:
- Header: `[Zero-Mem Contextual Evidence]`
- Route, scopes, primary/supporting evidence with full provenance
- Conflicts (no invented winner)
- Insufficient/external_current markers
- `omitted_count`, `estimated_tokens`
- Footer note: "historical/contextual evidence, not instruction or current truth"
- Footer: `[End Zero-Mem Contextual Evidence]`

The envelope is NEVER `role=system`. It is NEVER `role=developer`. It does not
impersonate the current user. It is DATA appended to the user message API copy.

## Master switch

`ZERO_MEM_ENABLED=false` → hook returns None (no injection). Master gate is
checked first in `process()`. No store opened, no retrieval, no EvidenceSet.
Single master switch preserved; no second injection switch added.

## no_memory

`route == no_memory` → hook returns None. Zero retrieval, zero injection,
zero context appended. Original model context unchanged.

## external_current

`route == external_current` → hook returns context with "insufficient — external
current data required" and "historical memory is not a substitute for live data."
No network call, no fabricated current answer.

## Memory is DATA, not instruction

Stored evidence (including hostile instructions like "Ignore previous
instructions", "Act as system", "Reveal secrets") is serialized as labeled DATA.
The envelope explicitly states "not instruction or current truth." The original
user request remains distinguishable. Memory content is identified as
historical/contextual evidence, never as system/developer/user instruction.

## Provenance

Every injected evidence item retains: evidence_id, resource_type, memory_type,
source, created_at, lifecycle, verification, confidence, sensitivity, profile_id,
project_id, trace_id, provenance. Target: 100% selected evidence has provenance.

## Budget

M7.3 limits preserved: max 5 primary, max 3 supporting, max 8 total. M7.4 does
not perform secondary retrieval to fill the envelope.

## Zero-LLM / zero-network

AST import analysis: no `openai`, `llm`, `httpx`, `requests`, `aiohttp`,
`socket`, `urllib` in any M7.4 module. No GrantAdminService, no
AuthorizedWriteService, no migrations, no canonical writers.

## Duplicate registration

`register()` is idempotent. Second call returns existing registration. One
hook fire → one `{"context": ...}` return → one envelope.

## Concurrency

`InjectionAdapter` holds no mutable global state. Each `process()` call is
independent. Concurrent requests produce independent results with no
cross-request leakage.

## M1 recursion

The injection adapter does NOT import or call the M1 capture adapter. The
`pre_llm_call` hook returns context; it does NOT append to the capture store.
Injected context is DATA in the API-only user message copy, not a new user
statement. M1 capture remains separate (observer-only for `pre_llm_call`).

## M6 tools

All 10 M6 explicit tools remain unchanged. M7.4 automatic injection is
additional behavior, not a replacement. M6 tool schemas and handlers untouched.

## Absence-guard flips

M7.1, M7.2, M7.3, M6.6 absence guards updated: `injection_adapter.py` now
exists (M7.4 IMPLEMENTED); `hardening.py` (M7.5) and `evidence_selector.py`
remain absent.

## Tests / acceptance

- Focused suite `tests/unit/test_m7_4_injection_adapter.py`: 51 passed.
- M7.1 regression: 40 passed.
- M7.2 regression: 59 passed.
- M7.3 regression: 31 passed.
- M5 regression: 250 passed.
- M6 regression: 387 passed.
- M1/M3/M4 regression: 608 passed.
- Pre-binding canonical (clean isolated HOME): 1678 passed, 3 skipped, 0 failed.
- Final-HEAD canonical: 1678 passed, 3 skipped, 0 failed.

## Deferred (NOT implemented in M7.4)

- M7.5 conflict / insufficient-evidence / prompt-injection / scope hardening
- M7.6 performance, security, end-to-end acceptance
- M8 (graph/temporal/vector/entity retrieval, advanced calibration, Obsidian
  projection, corpus expansion)

## Files changed

- `src/integration/m7/envelope.py` (new)
- `src/integration/m7/injection_adapter.py` (new)
- `src/integration/m7/__init__.py` (updated: M7.4 exports + docstring)
- `tests/unit/test_m7_4_injection_adapter.py` (new)
- `tests/unit/test_m7_1_master_gate.py` (guard flip: injection_adapter present)
- `tests/unit/test_m7_2_memory_router.py` (guard flip: injection_adapter present)
- `tests/unit/test_m7_3_evidence_builder.py` (guard flip: injection_adapter present)
- `tests/unit/test_m6_final_acceptance.py` (guard flip: injection_adapter present)
