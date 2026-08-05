# M1 Increment 4.2 — Pure Payload Mapping Plan

**Status:** READY FOR APPROVAL

## Objective

Implement a pure project-owned mapper that converts copied, security-normalized, redacted Hermes hook fixtures into Increment 1-compatible event inputs. It must not register real Hermes hooks, execute callbacks against Hermes, persist records, or alter Hermes behavior.

## Exact processing boundary

1. Copy the incoming hook payload.
2. Perform security-safe structural normalization only.
3. Redact or reject sensitive content through Increment 2.
4. Map the sanitized structure into the normalized event type.
5. Resolve only explicitly supplied identity and correlation metadata.
6. Hash only sanitized content.
7. Construct and validate the Increment 1 envelope-shaped mapping result.
8. Do not append; persistence is excluded from 4.2.

Structural normalization may copy approved mappings, lists, tuples, and supported scalars. It must not stringify unknown objects, call `repr()`, log raw values, hash raw values, or persist temporary raw representations.

## Hook fixtures

### Verified-supported fixtures

- `on_session_start`
- `on_session_end`
- `on_session_finalize`
- `pre_tool_call`
- `post_tool_call`
- `kanban_task_claimed`
- `kanban_task_completed`
- `kanban_task_blocked`

Each fixture will declare expected event class, source, directly supplied IDs, and expected null fields.

### Conditional fixtures

These remain unsupported until payload fixtures and registration behavior are separately verified:

- `on_session_reset`
- `pre_llm_call`
- `post_llm_call`
- `pre_api_request`
- `post_api_request`
- `api_request_error`
- `subagent_start`
- `subagent_stop`

They must return a fixed `conditional_fixture_required` result or sanitized rejection, never an operational mapping.

### Deferred fixtures

Remain unsupported:

- generic file operations;
- skill usage;
- generic task transitions;
- `transform_terminal_output`;
- `transform_tool_result`;
- `transform_llm_output`;
- `pre_verify`;
- `pre_gateway_dispatch`;
- approval hooks.

## Mapping result

Create a result type with only sanitized fields:

```python
@dataclass(frozen=True)
class MappingResult:
    status: Literal["mapped", "conditional_fixture_required", "deferred", "rejected"]
    hook: str
    event_class: str | None
    event_type: str | None
    source: str
    payload: Mapping[str, Any] | None
    diagnostic_code: str | None
```

Diagnostics are fixed codes only. No raw exception text, secret values, payload representations, or reversible secret data may appear.

## Correlation and identity

Preserve directly supplied:

- `session_id`;
- `turn_id`;
- `task_id`;
- `request_id`;
- `trace_id`;
- `parent_trace_id`;
- relation IDs;
- explicit `profile_id` and `project_id`.

Missing optional values remain null or empty according to Increment 1. Never infer identity from cwd, repository name, Git metadata, prompt text, session text, tool name, or unrelated Hermes state. Pair pre/post events only with directly supplied IDs.

## Immutability and security

- Use the verified Increment 2 redactor.
- Prove redaction precedes semantic mapping.
- Fail closed for cycles, unsupported values, and malformed content.
- Preserve the source payload byte/value structure by deep equality.
- No LLM, network, filesystem persistence, or Hermes runtime import.

## Files

Create:

```text
src/integration/payload_mapping.py
tests/unit/test_hermes_payload_mapping.py
tests/unit/test_hermes_payload_fixtures.py
acceptance-m1-increment-4-2.md  # after verification only
```

Modify after verification only:

```text
implementation-plan.json
project-state.yaml
```

Do not modify the installed Hermes source, real Hermes state, Increment 1 contract, Increment 2 redactor, or Increment 3 store.

## Acceptance criteria

| Criterion | Evidence |
|---|---|
| Verified-supported fixtures map correctly | Each supported fixture produces expected event class/source/status |
| Conditional hooks remain unsupported | Conditional hooks return fixed conditional status/rejection |
| Deferred hooks remain unsupported | Deferred and behavior-changing hooks never map |
| Safe structural normalization | Containers are copied; unsupported/cyclic values fail closed |
| Redaction precedes mapping | Spy test proves redactor runs before semantic mapping |
| Correlation preservation | Explicit IDs survive unchanged |
| Null handling | Missing optional fields are null/empty as specified |
| Explicit identity only | No unrelated state inference |
| Source immutability | Success and rejection preserve source payload |
| Sanitized diagnostics | Fixed codes contain no raw payload or secrets |
| No persistence | No CaptureStore append or filesystem side effect |
| No LLM/network/Hermes runtime | Pure local tests/static inspection |
| Increment 1/2 compatibility | Contract and redaction regressions remain passing |

## Test commands

Focused:

```bash
.venv/bin/python -m pytest tests/unit/test_hermes_payload_mapping.py tests/unit/test_hermes_payload_fixtures.py -q
```

Canonical:

```bash
.venv/bin/python -m pytest tests/ -q
```

No generic ad-hoc verifier is planned. A narrowly scoped temporary check is allowed only if a criterion cannot be expressed in automated tests; use `tempfile`, prefix `hermes-verify-`, synthetic values only, and remove it afterward.

## Rollback

Create a Git checkpoint before implementation. Revert only the 4.2 mapping commit if criteria fail. Do not modify Hermes installation or real Hermes state, and do not rewrite Increment 3 JSONL. Re-run Increment 1–3 focused and canonical tests after rollback.

Do not implement Increment 4.2 until separately approved.
