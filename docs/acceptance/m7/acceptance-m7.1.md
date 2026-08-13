# M7.1 — Master runtime gate + shared configuration/contracts

Status: VERIFIED (2026-08-09)
Milestone: M7 (Controlled Injection + Master Zero-Mem Runtime Switch) — increment 1
Schema version: 8 (unchanged; no migration v9)

## Scope

M7.1 establishes the ONE authoritative master Zero-Mem runtime switch and the
shared configuration/contracts. It introduces no retrieval, no authorization, no
SQLite/JSONL/M7 routing/injection logic. Controlled retrieval/injection (M7.2–7.5)
and M8 are explicitly deferred.

## Single master switch

- Canonical representation: `ZERO_MEM_ENABLED` (boolean), backed by
  `BridgeConfig.zero_mem_enabled: bool = True`.
- Exactly ONE user-facing master boolean. No `capture_enabled`, `retrieval_enabled`,
  `mcp_enabled`, `routing_enabled`, `injection_enabled`, `project_memory_enabled`, or
  equivalent subsystem switches.
- The pre-existing per-bridge `BridgeConfig.enabled` (opt-in observer wiring) is a
  SEPARATE, narrower flag. Master OFF dominates adapter-local enabled.

## Config semantics

- MISSING / absent -> default `true` (backward-compatible with M0–M6).
- Explicit valid (case-insensitive, whitespace-stripped): `true/1/yes/on`,
  `false/0/no/off`.
- INVALID / garbled (`maybe`, `2`, empty, `enabled-ish`) -> raises typed
  `ZeroMemConfigError` at supported initialization. NOT silently true, NOT silently
  false.
- Single source of truth: consumers call `ZeroMemRuntime.is_enabled()`; no scattered
  `os.getenv("ZERO_MEM_ENABLED")` parsing anywhere in M1/M6/gate modules.

## Restart semantics

- No config watcher / polling / filesystem watcher / signal reload / per-request
  env re-read. The setting is resolved during supported runtime/configuration
  initialization (`configure(enabled=...)`). Runtime behavior is deterministic for
  that instance. Changing the switch requires adapter/Hermes restart.

## Shared runtime gate module

`src/integration/zero_mem_runtime.py`:
- `ZeroMemRuntime` (frozen/immutable) holding only the resolved `enabled` boolean.
- `is_enabled()`, `disabled_reason()` (returns `"ZERO_MEM_DISABLED"` when off).
- `configure(enabled)`, `get_runtime()`.
- Contains NO retrieval, authorization, SQLite, JSONL, routing, or injection logic.
  Static import audit: imports only `dataclasses`/`typing`/`__future__`.

## M1 capture gate

`RegistrationAdapter._observe` returns immediately (deterministic no-op) when the
master is OFF: no redaction, no schema processing, no JSONL append, no derived-state
update, no "disabled" event persisted, no error into Hermes. M1 behavior when ON is
unchanged. Verified: append invocation count == 0 when OFF.

## M6 read gate

`HermesReadAdapter.call` / `_make_handler` consult the master gate first. When OFF,
every one of the 10 approved M6 tools returns:
```
{"status": "CAPABILITY_UNAVAILABLE", "reason_code": "ZERO_MEM_DISABLED", ...}
```
without opening the memory DB, resolving grants, or querying M3/M4. Disabled is
distinct from `EMPTY`, `POLICY_DENIED`, `INVALID_REQUEST`, and the generic
`adapter_not_ready` (distinguished by reason_code). Malformed-request validation
still occurs where current contracts require it before the gate.

## Master gate is NOT authorization

When ON, `is_enabled() == true` authorizes nothing; M5 remains mandatory. The gate
only controls whether Zero-Mem participates.

## M6.6 resource-type fix preserved

M3 handlers still propagate fixed ResourceType; M5 `_resource_allowed` still
enforces grant resource_types. Artifact-only grants cannot authorize event/relation
reads. Re-verified via the M5 direct regression class.

## M2 / background runtime audit

No independent automatic/periodic/background Zero-Mem runtime path exists (no
scheduler/worker/`while True` outside tests). Manual operator rebuild/repair tools
are not normal-runtime participants and are intentionally not gated.

## Data preservation (hard requirement)

When OFF, existing durable state remains intact: canonical JSONL, SQLite DB,
artifacts, grants, and M4/project state are not deleted/truncated/reset/rebuilt/
migrated/revoked/changed. OFF -> ON: old memory remains readable, grants and project
state intact, no rebuild required solely from the toggle. ON -> OFF: subsequent
operations disabled, previous data intact. OFF + missing DB: gate bypasses cleanly
without requiring DB health. ON + missing DB: existing sanitized
`CAPABILITY_UNAVAILABLE` behavior preserved (not collapsed into ZERO_MEM_DISABLED).

## Error taxonomy (distinct)

`ZERO_MEM_DISABLED` / `CONFIG_INVALID` (ZeroMemConfigError) / `CAPABILITY_UNAVAILABLE`
(generic) / `POLICY_DENIED` / `INVALID_REQUEST` / `EMPTY` — not collapsed into one.

## Tests / acceptance

- Focused suite `tests/unit/test_m7_1_master_gate.py`: 40 passed.
- Updated M6.6 absence guards (`test_single_master_switch_only`) in
  `test_m6_final_acceptance.py` and `test_m6_hermes_adapter.py` to reflect the
  approved single-switch design (asserts exactly one canonical switch present; all
  redundant/alias/per-subsystem switches absent).
- Required security test matrix covered: config defaults/invalid forms, single
  authority, adapter.enabled truth table, M1 ON/OFF, M6 all-10 OFF, OFF≠policy/empty,
  downstream-invocation-zero, OFF storage/grants/project-state preservation,
  OFF->ON / ON->OFF persistence, failure isolation, M2 audit, M5 mandatory + resource
  isolation regression, GrantAdminService unreachable, deferred-work absence,
  schema v8, zero-LLM, zero-network, path safety, real-HOME untouched.
- Ad-hoc verifier (temporary, OS-temp, path-safe): 30/30 PASS, then removed.

## Regression gates

- M7.1 focused: 40 passed.
- Full canonical (clean isolated HOME): 1537 passed, 3 skipped, 0 failed
  (pre-binding); 1537 passed, 3 skipped, 0 failed (post-binding final HEAD).
- M1/M3/M4/M5/M6 suites green.
- `test_no_real_hermes_home_writes` not weakened.

## Deferred (NOT implemented in M7.1)

- M7.2 deterministic memory-need router
- M7.3 authorized evidence eligibility + bounded evidence set
- M7.4 Hermes controlled context-injection adapter/envelope
- M7.5 conflict / insufficient-evidence / prompt-injection hardening
- M7.6 performance, security, end-to-end acceptance
- M8 (graph/temporal/vector/entity retrieval, advanced calibration, Obsidian
  projection, corpus expansion)

## Files changed

- `src/integration/zero_mem_runtime.py` (new) — shared gate authority.
- `src/integration/bridge_config.py` — `zero_mem_enabled` field + validation + to_dict.
- `src/integration/hermes_read_adapter.py` — M6 gate (call/_make_handler/_disabled_response/startup).
- `src/integration/hermes_registration.py` — M1 gate (_observe early-return).
- `tests/unit/test_m7_1_master_gate.py` (new) — 40 focused tests.
- `tests/unit/test_m6_final_acceptance.py`, `tests/unit/test_m6_hermes_adapter.py` —
  updated absence guards (single-switch design).
