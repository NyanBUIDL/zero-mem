# M1 Increment 4.6 Acceptance Evidence

**Increment:** Capture-rate benchmark and final M1 acceptance
**Status:** VERIFIED
**Starting commit:** `7fee198f4319398c9c837e915063e07690580456`
**Checkpoint tag:** `checkpoint-m1-increment-4-6-start`
**Implementation commit:** PENDING_FINAL_COMMIT
**Tested commit:** PENDING_TESTED_COMMIT
**Evidence/final commit:** PENDING_EVIDENCE_COMMIT

## Scope

Implemented and verified the controlled capture-rate benchmark for the 8
operationally supported Hermes hooks, then performed final M1 acceptance.

Supported hooks (denominator):
- on_session_start, on_session_end, on_session_finalize
- pre_tool_call, post_tool_call
- kanban_task_claimed, kanban_task_completed, kanban_task_blocked

Excluded (conditional 8 + deferred 10):
- conditional: on_session_reset, pre_llm_call, post_llm_call, pre_api_request,
  post_api_request, api_request_error, subagent_start, subagent_stop
- deferred: file_operations, skill_usage, generic_task_transitions,
  transform_terminal_output, transform_tool_result, transform_llm_output,
  pre_verify, pre_gateway_dispatch, pre_approval_request, post_approval_response

## Capture-rate formula (exact)

    successfully_accounted_logical_events / expected_supported_logical_events * 100

A logical event is successfully accounted for when:
- one valid sanitized record is appended; OR
- an accepted duplicate result is returned and the original stored record is
  confirmed to exist.

Each expected logical event counts at most once; neither appends nor later
duplicate attempts are double-counted.

## Benchmark counts (from test run)

- expected supported logical events: 8
- appended unique events: 8
- accepted duplicate events: 2 (pre_tool_call, kanban_task_completed replayed)
- rejected events: 0
- failed captures: 0
- unsupported/deferred events (reported separately, excluded): 4 driven
- ordering failures: 0
- correlation failures: 0
- envelope-validation failures: 0
- secret-scan failures: 0
- capture rate: 100.0%  (8 accounted / 8 expected; 8 appended unique,
  plus 2 accepted-duplicate confirmations for already-accounted events, not
  double-counted)

Note: `accounted` (8) equals the 8 expected logical events, each counted once;
the 2 accepted-duplicate confirmations reinforce events already accounted by
their appended record and are not double-counted in the rate.

## Acceptance assertions (all pass)

- capture rate >= 99% (100.0%)
- every captured record passes validate_envelope
- all JSONL records independently parseable
- deterministic serialization (sha256 content hash)
- event and correlation identifiers preserved
- committed sequence valid and monotonic (0..7)
- duplicate attempts do not create extra records
- duplicate attempts do not advance committed sequence
- observer behavior non-interfering (enabled vs disabled equivalent)
- enabled and disabled Hermes-owned outputs equivalent
- no original synthetic secret appears anywhere (JSONL, results, metrics,
  diagnostics, reports)
- conditional/deferred hooks excluded from denominator
- no real Hermes-home writes (all under tmp_path)
- installed Hermes source not modified

## Final M1 acceptance (all required properties verified)

observation-only sidecar; versioned event contract; deterministic redaction;
never_store enforcement; append-only JSONL; deduplication; sequence recovery;
project-local opt-in bridge; verified hook registration; observer
non-interference; failure isolation; capture rate >=99%; no raw-secret leakage;
no LLM use for routine memory operations; no real Hermes-home writes; no
installed Hermes source modification; conditional and deferred hooks remain
explicitly unsupported; retry/dead-letter/SQLite/retrieval/Obsidian/MCP/context
injection remain unimplemented.

## Test results

- Focused Increment 4.6 tests: 20 passed
  (test_m1_capture_rate.py + test_m1_final_acceptance.py)
- Canonical suite: 166 passed (146 prior + 20 new)

## Controlled environment

- temporary HERMES_HOME
- temporary capture root
- synthetic project_id / profile_id
- synthetic payloads and secrets
- no real credentials, no network, no LLM, no destructive commands
- no writes to real ~/.hermes
- no modification of installed Hermes source

## Files changed

- src/integration/capture_benchmark.py (new benchmark harness)
- tests/integration/test_m1_capture_rate.py (new)
- tests/integration/test_m1_final_acceptance.py (new)
- .hermes/plans/2026-08-05_000000-m1-increment-4-6-capture-rate-benchmark.md
- runbooks/m1-increment-4-6-capture-rate.md
- project-state.yaml, implementation-plan.json (state)
- acceptance-m1-increment-4-6.md, acceptance-m1-final.md

## Installed Hermes source integrity

Installed Hermes Agent at /home/brian-nguyen/.hermes/hermes-agent shows only
the pre-existing package-lock.json modification; no project operation altered it.
