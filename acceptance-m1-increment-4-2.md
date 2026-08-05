# M1 Increment 4.2 Acceptance Evidence

**Increment:** Pure payload mapping
**Status:** VERIFIED
**Starting commit:** `6696f0d95da2934b6dfdfa34d6835280a5bf584d`
**Implementation commit:** `1e89ae28bec9368323983adf332af8137eaaa0b8`
**Tested commit:** `0366afb82f5c4034024c9f1e4d382107cff12ead`
**Ad-hoc verification commit:** `0366afb82f5c4034024c9f1e4d382107cff12ead`
**Latest evidence review:** Current HEAD was documentation/state-only after executable implementation; fresh tests below are bound to `0366afb82f5c4034024c9f1e4d382107cff12ead`.
**Rerun required:** Yes; focused mapping tests and canonical suite were rerun against the Increment 4.2 executable state.

| Criterion | Status | Objective evidence | Evidence location |
|---|---|---|---|
| All verified-supported fixtures map | PASS | 8 supported hook parametrizations map to sanitized results | `tests/unit/test_hermes_payload_fixtures.py` |
| Conditional hooks remain `conditional_fixture_required` | PASS | All 8 conditional hooks return fixed conditional status | Same fixture tests |
| Deferred hooks remain unsupported | PASS | File/skill/task/transform/approval classes return deferred | Same fixture tests |
| Security-safe structural normalization | PASS | Mappings/lists/tuples/scalars copy; unsupported/cyclic values reject | `src/integration/payload_mapping.py` |
| Redaction before semantic mapping | PASS | Redactor spy runs before mapped result construction | `test_mapping_calls_redaction_before_semantic_mapping` |
| Nested-secret absence | PASS | Synthetic secret absent from mapped result | `test_minimal_session_and_complete_tool_payloads` |
| Source-payload immutability | PASS | Success and failure inputs remain unchanged | Mapping fixture tests |
| Explicit identity/correlation preservation | PASS | Session, turn, task, request, trace, parent, relation, project, profile preserved | `test_explicit_identity_and_relation_fields_are_preserved` |
| Missing optional identifiers are null | PASS | Minimal session mapping produces null optional fields | `test_minimal_session_and_complete_tool_payloads` |
| No identity inference | PASS | Message text does not populate identity fields | `test_identity_is_explicit_and_missing_values_are_null` |
| No heuristic pre/post pairing | PASS | Distinct turns remain distinct and event IDs are not paired by tool name | `test_pre_post_events_do_not_pair_heuristically` |
| Malformed/unsupported/cyclic fail closed | PASS | Unsafe object and cycle return fixed rejection codes | Mapping fixture tests |
| Sanitized mapping failures | PASS | Diagnostics contain fixed codes only; no raw repr/payload | `test_mapping_failure_has_fixed_sanitized_diagnostic` |
| Deterministic mapping | PASS | Equivalent key insertion order yields equivalent mapped results | `test_mapping_is_deterministic` |
| No raw payload in output/diagnostics | PASS | Mapping outputs and errors contain no raw secret or object repr | Focused mapping tests and ad-hoc verification |
| No LLM calls | PASS | Pure local mapper has no model dependency | Source inspection and tests |
| No network calls | PASS | Pure local mapper has no network dependency | Source inspection and tests |
| No persistence/CaptureStore append | PASS | Result has no store/append behavior; no filesystem side effect | `test_mapping_result_has_no_persistence_fields` |
| No real hook registration | PASS | No Hermes runtime registration or callback invocation added | Git diff and scope boundary |
| Future Increment 4 behavior remains unimplemented | PASS | No runtime integration, capture-rate harness, retry, dead-letter, SQLite, retrieval, MCP, Obsidian, or injection | Scope boundary |

## Focused automated tests

```text
.venv/bin/python -m pytest tests/unit/test_hermes_payload_mapping.py tests/unit/test_hermes_payload_fixtures.py -q
42 passed in 0.04s
```

## Canonical regression suite

```text
.venv/bin/python -m pytest tests/ -q
95 passed in 0.10s
```

## Ad-hoc evidence

```text
Increment 4.2 focused ad-hoc verification: PASS
exit_code=0
cleaned=True
```

The ad-hoc verifier used only synthetic content and a temporary `hermes-verify-` file. It checked supported/conditional/deferred classifications, nested-secret absence, payload immutability, and explicit session/turn correlation. It is ad-hoc evidence, not a replacement for automated tests.

## Exact mapping registries

Verified-supported:

- `on_session_start`
- `on_session_end`
- `on_session_finalize`
- `pre_tool_call`
- `post_tool_call`
- `kanban_task_claimed`
- `kanban_task_completed`
- `kanban_task_blocked`

Conditional-fixture-required:

- `on_session_reset`
- `pre_llm_call`
- `post_llm_call`
- `pre_api_request`
- `post_api_request`
- `api_request_error`
- `subagent_start`
- `subagent_stop`

Deferred:

- generic file operations;
- skill usage;
- generic task transitions;
- behavior-transforming hooks;
- approval and dispatch-control hooks.

No real Hermes hooks were registered or invoked. No persistence, retry, dead-letter, runtime integration, SQLite, retrieval, MCP, Obsidian, or prompt/context injection was implemented.

**M1 INCREMENT 4.2: VERIFIED**

# End of file
Each mapping result has a stable event ID policy: directly supplied event IDs are preserved; absent IDs use a deterministic unassigned hook/turn placeholder solely for this pure mapping result and are not persisted by 4.2.