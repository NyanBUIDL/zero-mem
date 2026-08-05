# M1 Increment 4 — Verified Hermes Hook Integration Plan

> Implement only after explicit approval. Do not modify the installed Hermes source. This increment integrates the project-local opt-in bridge with the verified Hermes Agent v0.19.1 lifecycle hooks and sends only redacted, normalized events to the verified Increment 3 capture store.

## Objective

Capture officially supported Hermes lifecycle events through a project-owned, independently enabled bridge while preserving observer non-interference: the bridge must not mutate prompts, messages, tool arguments, model context, actions, or Hermes control flow. Capture failures are isolated and reported through sanitized diagnostics only.

## Verified compatibility baseline

Planning inspection verified local Hermes Agent **v0.19.1**, upstream commit `82c6acae`, under `/home/brian-nguyen/.hermes/hermes-agent`. The bridge must use public/stable lifecycle hook registration/configuration surfaces only and must not import unstable private modules or edit the installation.

Verified hooks available for integration:

- `on_session_start`
- `on_session_end`
- `on_session_finalize`
- `on_session_reset`
- `pre_tool_call`
- `post_tool_call`
- `pre_llm_call`
- `post_llm_call`
- `pre_api_request`
- `post_api_request`
- `api_request_error`
- `subagent_start`
- `subagent_stop`
- verified Kanban/task lifecycle hooks where exposed by the stable lifecycle API

The exact hook names/signatures must be confirmed from the installed v0.19.1 public registration API in the implementation tests before wiring. Unsupported or unavailable hooks fail closed and are recorded as deferred coverage; they must not be claimed as captured.

## Supported and deferred event classes

### Supported in Increment 4

- `session_lifecycle`: session start/end/finalize/reset.
- `pre_tool_call`: tool name and sanitized arguments metadata.
- `post_tool_call`: tool name, status, duration, sanitized result/error metadata.
- `llm_api_lifecycle`: pre/post LLM/API request and error lifecycle metadata.
- `subagent_lifecycle`: subagent start/stop metadata.
- `verified_task_or_kanban_lifecycle`: only the task lifecycle callbacks directly verified in v0.19.1.

### Deferred coverage

- `file_operations`: no verified generic file-operation hook.
- `skill_usage`: no verified generic skill-usage hook.
- `generic_task_transitions`: no verified universal task-transition hook.
- Any provider-specific or private hook not exposed through the verified API.

Deferred classes must be listed in bridge diagnostics/coverage metadata and excluded from the capture-rate denominator.

## Project-local opt-in bridge

Create a project-owned bridge, for example:

- `src/integration/hermes_bridge.py`
- `src/integration/bridge_config.py`
- `tests/integration/test_hermes_bridge.py`
- `tests/integration/test_hermes_bridge_non_interference.py`
- `runbooks/m1-increment-4-hermes-bridge.md`
- `acceptance-m1-increment-4.md` after verification.

Configuration must be explicit and independently enable/disable the bridge, for example:

```python
BridgeConfig(
    enabled=False,
    profile_id=None,
    project_id=None,
    capture_root=Path("data/traces"),
    hermes_home=temporary_path,
)
```

The bridge is disabled by default. Enabling/disabling it must not alter Hermes configuration globally and must not write to the real `~/.hermes` during tests. Project/profile identity is explicit only; never infer it from cwd, repository name, prompt, session text, or unrelated Hermes state.

## Hook payload to normalized envelope mapping

For each supported callback:

1. Receive hook arguments without mutation.
2. Copy the payload into an isolated structure.
3. Resolve explicit bridge/session/profile/project metadata.
4. Normalize event type/source and correlation IDs.
5. Invoke Increment 2 `redact_payload` before any storage call.
6. Build the Increment 1 normalized envelope with sanitized content, redaction audit, sensitivity, retention, and hash.
7. Append only through Increment 3 `CaptureStore.append`.
8. Return the original hook-compatible result unchanged.

Mapping requirements:

- Hermes session ID → `session_id`.
- Hook turn/request/task IDs → `turn_id`, `request_id`/relation IDs, and `task_id` when directly present.
- Bridge-generated `trace_id` per observed callback; preserve parent/relation identifiers where provided.
- Hook timestamp is source/created timestamp; observation timestamp is bridge capture time.
- Hook name maps to `source`; declared event class maps to `event_type`.
- Tool name/arguments/results are sanitized content only.
- Verification remains `none`/`observed` unless a directly verified Hermes callback explicitly declares verification; assistant claims never become verified state.

## Observer non-interference

Tests must prove:

- Hook arguments are unchanged after callbacks.
- Prompt/messages/model context are byte-for-byte unchanged.
- Tool arguments and Hermes action results are unchanged.
- Bridge return values preserve the original hook result.
- Capture exceptions cannot change Hermes control flow or convert a successful operation into failure.
- The bridge never calls an LLM, network service, retrieval API, prompt mutator, or injection mechanism.
- Disabled bridge performs no capture and has no observable behavior beyond configuration inspection.

## Failure isolation and diagnostics

- Redaction or contract rejection produces a sanitized bridge diagnostic and does not raise into Hermes.
- Capture-store append failure produces a sanitized diagnostic and does not raise into Hermes.
- No retries or dead-letter persistence are implemented here; those remain future scope.
- Diagnostics include only fixed failure class, hook/event class, sanitized path/IDs, and timestamp. Never include raw arguments, secret values, exception reprs, or sensitive payloads.
- Bridge metrics record observed, captured, rejected, deferred, and failed counts by declared event class without content.

## Capture-rate harness

The controlled harness covers only the officially supported event classes above. It must:

- generate a known event sequence for each supported hook;
- enable the bridge in an isolated temporary `HERMES_HOME` and temporary capture root;
- compare observed callbacks with captured JSONL records by trace/event IDs;
- exclude deferred event classes from the denominator;
- assert `>=99%` capture for supported classes;
- assert ordering and correlation fields;
- assert original synthetic secret corpus is absent from JSONL, audits, diagnostics, logs, exceptions, and temporary artifacts;
- assert disabled bridge captures zero records and does not mutate behavior.

The harness does not ingest a large corpus and does not test retrieval/injection.

## Temporary Hermes runtime testing

Integration tests must set an isolated temporary `HERMES_HOME` and never touch the user’s real Hermes state. Use a temporary capture root and explicit project/profile IDs. Tests must inspect runtime output and JSONL only after sanitization. The installed Hermes source is read-only and must remain unchanged; verify its Git/source hash or file status before/after tests if needed.

## Acceptance criteria and tests

| Criterion | Objective evidence |
|---|---|
| Opt-in lifecycle integration | Unit test disabled/enabled bridge and integration test verified v0.19.1 hooks |
| Supported/deferred coverage | Registry test matches verified supported classes and explicitly lists deferred classes |
| Correct envelope mapping | Integration fixtures assert event type, source, session, turn/task/request/trace correlation, timestamps, and explicit profile/project IDs |
| Redaction-before-capture | Secret fixture absent from capture output; bridge calls Increment 2 before Increment 3 append |
| Observer non-interference | Before/after payload, prompt, tool args, context, action result, and return-value assertions pass |
| Failure isolation | Inject redaction/storage failure; Hermes callback result/control flow remains unchanged and diagnostic is sanitized |
| Capture rate | Controlled supported-class harness reaches `>=99%`; deferred classes excluded from denominator |
| Temporary-home safety | Runtime tests write only to temp `HERMES_HOME`/capture root; installed Hermes remains unmodified |
| Regression/exclusions | Increment 1, Increment 2, and Increment 3 suites pass; no retries, dead letters, SQLite, retrieval, MCP, Obsidian, or injection |

## Commands

Focused bridge unit tests:

```bash
.venv/bin/python -m pytest tests/unit/test_hermes_bridge.py tests/unit/test_hermes_bridge_mapping.py -q
```

Integration and non-interference tests:

```bash
.venv/bin/python -m pytest tests/integration/test_hermes_bridge.py tests/integration/test_hermes_bridge_non_interference.py -q
```

Capture-rate harness:

```bash
.venv/bin/python -m pytest tests/benchmark/test_m1_capture_rate.py -q
```

Canonical regression suite:

```bash
.venv/bin/python -m pytest tests/ -q
```

## Rollback strategy

- Create a Git checkpoint before implementation.
- Keep bridge disabled by default and project-local.
- Revert only the Increment 4 bridge commit if non-interference, redaction, or capture-rate criteria fail.
- Do not modify or roll back installed Hermes source or real Hermes state.
- Preserve prior JSONL raw traces; do not delete or rewrite them.
- Verify Increment 1–3 focused and canonical suites after rollback.

## Explicit exclusions

Retries, backoff, 500 ms capture deadlines, dead-letter persistence/replay, SQLite metadata/indexes, retrieval, evidence routing, MCP, Obsidian, prompt/context injection, graph/temporal retrieval, large-corpus ingestion, and unsupported Hermes event classes remain unimplemented.

**Increment 4 plan: READY FOR APPROVAL**
Do not implement Increment 4 until separately approved.
