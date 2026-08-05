# M1 Increment 4.4 Acceptance Evidence

**Increment:** Verified hook registration
**Status:** VERIFIED
**Starting commit:** `239f765b0ec1004b76da915e99ecdd8e0527fd10`
**Hermes:** v0.19.1 (2026.7.30)
**Hermes upstream:** `1be70d63` reported by installed CLI; local source HEAD `0a62610f` with pre-existing `package-lock.json` modification
**Registration mechanism:** project-local context-compatible adapter using the verified `register_hook(hook_name, callback)` surface; no installed Hermes source modification
**Implementation commit:** `38f97eb29de8670b5ea7527c88f58b03afa808ae`
**Tested commit:** `735f7600ba15de0b02c1ec620e456093f04193c1`
**Corrected ad-hoc verifier commit:** `735f7600ba15de0b02c1ec620e456093f04193c1`
**Rerun required:** Yes — the canonical suite was rerun after the state assertion update; focused and canonical results below are bound to the tested commit.

| Criterion | Status | Objective evidence |
|---|---|---|
| Registration mechanism | PASS | Fake public `register_hook` context fixture registers the exact approved hook set |
| Approved hooks only | PASS | 8 verified-supported hooks register; conditional/deferred hooks are absent |
| Disabled by default | PASS | Disabled config registers no callbacks |
| Explicit enablement | PASS | Enabled config registers approved hooks only |
| Idempotent registration | PASS | Repeated registration does not duplicate callbacks |
| Callback routing | PASS | Callback copies payload and routes observation through Increment 4.3 adapter path |
| Neutral return | PASS | Callback returns `None` for observer-only behavior |
| Payload non-interference | PASS | Positional/nested payload remains structurally unchanged |
| Failure isolation | PASS | Callback and registration failures are caught and converted to fixed diagnostics |
| Temporary-home safety | PASS | Integration fixtures use temporary capture/Hermes-home paths; no real-home capture file created |
| Installed source safety | PASS | Installed Hermes source was inspected only; no project operation modified it |
| No LLM/network | PASS | Registration adapter uses local project modules only |
| Future behavior excluded | PASS | No conditional hooks, retries, dead letters, capture-rate harness, SQLite, retrieval, MCP, Obsidian, or injection implemented |

## Exact registered hooks

- `on_session_start`
- `on_session_end`
- `on_session_finalize`
- `pre_tool_call`
- `post_tool_call`
- `kanban_task_claimed`
- `kanban_task_completed`
- `kanban_task_blocked`

Conditional hooks remain unregistered: `on_session_reset`, `pre_llm_call`, `post_llm_call`, `pre_api_request`, `post_api_request`, `api_request_error`, `subagent_start`, `subagent_stop`.

Deferred hooks/classes remain unregistered: generic file operations, skill usage, generic task transitions, behavior-transforming hooks, approval hooks, and dispatch-control hooks.

## Commands

Focused registration tests:

```text
.venv/bin/python -m pytest tests/unit/test_hermes_registration.py tests/integration/test_hermes_registration_v0191.py tests/integration/test_hermes_registration_non_interference.py -q
12 passed in 0.03s
```

Canonical regression suite:

```text
.venv/bin/python -m pytest tests/ -q
121 passed in 0.09s
```

The first canonical run exposed a stale baseline state assertion after advancing project state to Increment 4.4. The baseline assertion was updated to the verified state, then the canonical suite passed. This was test-state maintenance, not a product failure.

## Corrected ad-hoc verification

The first verifier attempt failed because it incorrectly treated the fake context callback list as callable. This was a verifier-script defect, not a product-code failure; no product-code modification resulted. The corrected verifier passed:

```text
PASS
exit_code=0
cleaned=True
```

## Incidents

No real Hermes source or real Hermes-home file was modified. Generated caches and temporary artifacts were removed.

**M1 INCREMENT 4.4: VERIFIED**

# End of file
