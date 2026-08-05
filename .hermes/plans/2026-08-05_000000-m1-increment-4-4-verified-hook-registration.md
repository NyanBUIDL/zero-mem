# M1 Increment 4.4 — Verified Hook Registration Plan

**Status:** READY FOR APPROVAL

## Objective

Add a project-local, opt-in registration adapter for the exact Hermes Agent v0.19.1 lifecycle/plugin mechanism verified during planning. Register only hooks with verified payload fixtures, route callbacks through the verified Increment 4.3 adapter, preserve callback return-value neutrality, and isolate all bridge failures from Hermes control flow.

## Registration boundary

```text
BridgeConfig(enabled=True)
  -> project-local registration adapter
  -> verified Hermes v0.19.1 plugin/lifecycle registration
  -> callback receives hook payload
  -> Increment 4.3 adapter
  -> sanitized append/duplicate result
  -> original callback result unchanged
```

No installed Hermes source modification is allowed. Conditional hooks remain unregistered until direct fixture verification passes.

## Exact Hermes mechanism

Planning verified the Hermes v0.19.1 dispatch surface:

- `hermes_cli.lifecycle.invoke_hook(hook_name, **kwargs)` dispatches built-in observability and then `hermes_cli.plugins.invoke_hook`.
- `hermes_cli.plugins.VALID_HOOKS` is the hook registry.
- Directory plugins require a `plugin.yaml` manifest and `__init__.py` with `register(ctx)`.
- Project plugin discovery is opt-in through Hermes project-plugin configuration.

Implementation must confirm the exact registration callback signature against a temporary v0.19.1 fixture before enabling any hook. The project may use a project-local plugin/registration adapter only; it must not edit `/home/brian-nguyen/.hermes/hermes-agent`.

## Registration sets

### Register only after verified fixtures

- `on_session_start`
- `on_session_end`
- `on_session_finalize`
- `pre_tool_call`
- `post_tool_call`
- `kanban_task_claimed`
- `kanban_task_completed`
- `kanban_task_blocked`

### Remain unregistered

Conditional until fixture verification:

- `on_session_reset`
- `pre_llm_call`
- `post_llm_call`
- `pre_api_request`
- `post_api_request`
- `api_request_error`
- `subagent_start`
- `subagent_stop`

Deferred permanently for this increment:

- generic file operations;
- skill usage;
- generic task transitions;
- behavior-transforming hooks;
- approval and dispatch-control hooks.

## Bridge behavior

- Disabled by default.
- Enable/disable is independently controlled through verified `BridgeConfig`.
- Registration is idempotent per process and hook name.
- Disabled bridge registers nothing and captures nothing.
- Each callback copies payload and invokes Increment 4.3 only.
- Callback return value is always neutral (`None` or the exact observer-neutral value required by the verified Hermes registration API).
- The adapter result is never returned as a Hermes control response.
- No prompt, message, tool argument, model context, action, or result is rewritten.

## Failure isolation

Registration failure, callback mapping failure, redaction rejection, envelope failure, and CaptureStore failure produce sanitized bridge metrics/diagnostics only. They never propagate uncontrolled exceptions, veto tools, rewrite requests, alter session lifecycle, alter agent exit status, or change callback return values.

No retry, backoff, or dead-letter behavior is added in 4.4.

## Runtime isolation

Integration tests must create temporary directories with `tempfile`, use a temporary `HERMES_HOME`, a temporary capture root, explicit project/profile IDs, and synthetic payloads only. They must not write the real `~/.hermes`, modify the installed Hermes source, use real secrets, or run destructive commands.

Tests must compare installed-Hermes source status/hash before and after runtime verification where practical.

## Files

Create:

```text
src/integration/hermes_registration.py
src/integration/plugin_entry.py  # only if the verified project-plugin API requires it
 tests/unit/test_hermes_registration.py
 tests/integration/test_hermes_registration_v0191.py
 tests/integration/test_hermes_registration_non_interference.py
 runbooks/m1-increment-4-4-hermes-registration.md
 acceptance-m1-increment-4-4.md  # after verification only
```

Modify after verification only:

```text
implementation-plan.json
project-state.yaml
```

Must not modify:

```text
/home/brian-nguyen/.hermes/hermes-agent/**
/home/brian-nguyen/.hermes/**
src/capture/**
src/redaction/**
src/storage/**
src/integration/bridge_config.py
src/integration/payload_mapping.py
src/integration/capture_adapter.py
```

## Acceptance criteria and tests

| Criterion | Evidence |
|---|---|
| Exact v0.19.1 registration mechanism | Fixture/integration test proves registration through verified lifecycle/plugin API |
| Only verified hooks registered | Registry test asserts supported set; conditional/deferred hooks absent |
| Idempotent registration | Repeated enable/init creates one callback per hook |
| Enable/disable behavior | Disabled registers zero; enabled registers only approved hooks |
| Callback routing | Callback reaches Increment 4.3 with copied payload and returns neutral value |
| Return-value neutrality | Hermes-visible callback/control result is unchanged and never contains adapter result |
| Observer non-interference | Prompt/message/tool args/results/session/action comparisons remain unchanged |
| Failure isolation | Injected registration/callback/adapter/store failures do not propagate |
| Temporary-home safety | Runtime tests write only to temporary `HERMES_HOME` and capture root |
| Installed source unchanged | Source status/hash remains unchanged |
| Regression/exclusions | Increment 1–4.3 tests pass; no retry/dead-letter/SQLite/retrieval/MCP/Obsidian/injection |

## Commands

Focused registration tests:

```bash
.venv/bin/python -m pytest tests/unit/test_hermes_registration.py -q
```

Hermes v0.19.1 isolated integration tests:

```bash
.venv/bin/python -m pytest tests/integration/test_hermes_registration_v0191.py tests/integration/test_hermes_registration_non_interference.py -q
```

Canonical regression suite:

```bash
.venv/bin/python -m pytest tests/ -q
```

## Rollback

Create a checkpoint before implementation. Disable the bridge, then revert only the 4.4 registration commit if any registration, non-interference, or failure-isolation criterion fails. Do not modify Hermes installation or real Hermes state. Preserve all existing JSONL traces. Re-run Increment 1–4.3 focused and canonical suites after rollback.

Do not implement Increment 4.4 until separately approved.

**Increment 4.4 plan: READY FOR APPROVAL**

# End of file
``` in code 
    